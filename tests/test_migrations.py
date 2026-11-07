"""Schema versionado: banco vazio, banco antigo (completo e parcial), idempotência e recusa segura."""
import os
import sqlite3
import subprocess
import sys

import pytest

from studio import migrations
from studio.accounts import Accounts
from studio.db import Database, connect
from studio.migrations import MigrationError, current_version, migrate


def schema_snapshot(conn):
    rows = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    return [tuple(r) for r in rows]


def test_empty_database_boots_at_latest(tmp_path):
    db = Database(tmp_path / "d" / "studio.sqlite3")
    assert current_version(db.conn) == migrations.LATEST == 1
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"productions", "scenes", "attempts", "reviews", "events", "run_state", "users", "workspaces", "memberships",
            "sessions", "login_attempts", "email_codes", "password_resets", "credit_entries", "training_state",
            "training_versions", "training_tests", "music_tracks", "music_favorites", "chat_log"} <= tables
    db.close()


def test_running_twice_changes_nothing(tmp_path):
    path = tmp_path / "s.sqlite3"
    db = Database(path)
    Accounts(db).create_user("a@example.com", "senha-forte-123")
    before = schema_snapshot(db.conn)
    assert migrate(db.conn) == []
    db.close()
    db2 = Database(path)
    assert schema_snapshot(db2.conn) == before and current_version(db2.conn) == 1
    assert db2.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    db2.close()


def test_current_schema_unversioned_is_recognized_without_data_loss(tmp_path):
    """Banco real de hoje (tabelas completas, user_version=0): vira versão 1 e mantém tudo."""
    path = tmp_path / "s.sqlite3"
    db = Database(path)
    _, wid = Accounts(db).create_user("a@example.com", "senha-forte-123")
    db.conn.execute("PRAGMA user_version=0")
    db.close()
    db2 = Database(path)
    assert current_version(db2.conn) == 1
    assert db2.conn.execute("SELECT COUNT(*) FROM workspaces WHERE id=?", (wid,)).fetchone()[0] == 1
    db2.close()


def test_partial_old_schema_is_completed_then_marked(tmp_path):
    """Banco antigo com tabelas e colunas faltando: completa, preserva linhas e preenche os legados."""
    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
                            pw_hash TEXT NOT NULL, is_platform_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner_id TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'simulated',
                                 allow_real INTEGER NOT NULL DEFAULT 0, monthly_cap_usd REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        INSERT INTO users VALUES ('u1','dono@example.com','Dono','x',1,'2026-01-01T00:00:00+00:00');
        INSERT INTO users VALUES ('u2','cli@example.com','Cli','x',0,'2026-01-02T00:00:00+00:00');
        INSERT INTO workspaces VALUES ('w1','A','u1','simulated',0,0,'t');
        INSERT INTO workspaces VALUES ('w2','B','u2','simulated',0,0,'t');
    """)
    con.commit()
    con.close()
    db = Database(path)
    assert current_version(db.conn) == 1
    assert db.conn.execute("SELECT email_verified_at FROM users WHERE id='u2'").fetchone()[0] == "2026-01-02T00:00:00+00:00"
    assert [r[0] for r in db.conn.execute("SELECT credits_exempt FROM workspaces ORDER BY id")] == [1, 0]
    assert db.conn.execute("SELECT COUNT(*) FROM credit_entries").fetchone()[0] == 0
    db.close()


def test_incompatible_schema_is_refused_and_untouched(tmp_path):
    """Coluna obrigatória sem como completar: recusa, não marca versão e não altera nada."""
    path = tmp_path / "bad.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE scenes (production_id TEXT NOT NULL, idx INTEGER NOT NULL)")
    con.execute("INSERT INTO scenes VALUES ('p',1)")
    con.commit()
    con.close()
    with pytest.raises(MigrationError, match="scenes"):
        Database(path)
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 0
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"scenes"}   # rollback total
    assert con.execute("SELECT COUNT(*) FROM scenes").fetchone()[0] == 1
    con.close()


def test_newer_database_is_refused(tmp_path):
    path = tmp_path / "new.sqlite3"
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version=99")
    con.close()
    with pytest.raises(MigrationError, match="mais nova"):
        Database(path)


def test_failure_mid_chain_rolls_back_everything(tmp_path):
    def boom(conn):
        conn.execute("CREATE TABLE half_done (x)")
        raise RuntimeError("falha")

    chain = [*migrations.MIGRATIONS, migrations.Migration(2, "quebra", boom)]
    conn = connect(tmp_path / "s.sqlite3")
    with pytest.raises(RuntimeError):
        migrate(conn, chain)
    assert current_version(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('half_done','users')").fetchone()[0] == 0
    conn.close()


def test_later_migration_applies_once_in_order(tmp_path):
    seen = []

    def m2(c):
        seen.append(2)
        c.execute("ALTER TABLE users ADD COLUMN extra TEXT")

    chain = [*migrations.MIGRATIONS, migrations.Migration(2, "a", m2), migrations.Migration(3, "b", lambda c: seen.append(3))]
    conn = connect(tmp_path / "s.sqlite3")
    assert migrate(conn, chain) == [1, 2, 3] and migrate(conn, chain) == [] and seen == [2, 3]
    assert current_version(conn) == 3
    conn.close()


def test_four_processes_booting_together(tmp_path):
    path = tmp_path / "s.sqlite3"
    code = "import sys; from pathlib import Path; from studio.db import Database; Database(Path(sys.argv[1])).close()"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    procs = [subprocess.Popen([sys.executable, "-c", code, str(path)], env=env) for _ in range(4)]
    assert [p.wait(60) for p in procs] == [0, 0, 0, 0]
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


def test_eight_processes_booting_together(tmp_path):
    path = tmp_path / "s.sqlite3"
    code = "import sys; from pathlib import Path; from studio.db import Database; Database(Path(sys.argv[1])).close()"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    procs = [subprocess.Popen([sys.executable, "-c", code, str(path)], env=env) for _ in range(8)]
    assert [p.wait(60) for p in procs] == [0] * 8
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()


class _FlakyWal:
    """Conexão falsa: o PRAGMA journal_mode=WAL falha com 'database is locked' N vezes e depois funciona."""

    def __init__(self, failures, message="database is locked"):
        self.failures, self.message, self.calls = failures, message, 0

    def execute(self, sql):
        self.calls += 1
        if self.calls <= self.failures:
            raise sqlite3.OperationalError(self.message)
        return self

    def fetchone(self):
        return ("wal",)


def test_wal_switch_retries_transient_lock(monkeypatch):
    monkeypatch.setattr("studio.db.WAL_RETRY_SLEEP_S", 0)
    conn = _FlakyWal(failures=7)
    db_module = sys.modules["studio.db"]
    db_module._enable_wal(conn)
    assert conn.calls == 8


def test_wal_switch_gives_up_and_does_not_retry_other_errors(monkeypatch):
    monkeypatch.setattr("studio.db.WAL_RETRY_SLEEP_S", 0)
    db_module = sys.modules["studio.db"]
    stuck = _FlakyWal(failures=10_000)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        db_module._enable_wal(stuck)
    assert stuck.calls == db_module.WAL_ATTEMPTS
    other = _FlakyWal(failures=10_000, message="disk I/O error")
    with pytest.raises(sqlite3.OperationalError, match="I/O"):
        db_module._enable_wal(other)
    assert other.calls == 1
