"""Conexões SQLite: WAL, synchronous=NORMAL, busy_timeout e checkpoint PASSIVE."""
from studio.db import Database, checkpoint


def test_connection_pragmas(tmp_path):
    db = Database(tmp_path / "s.sqlite3")
    pragma = {k: db.conn.execute(f"PRAGMA {k}").fetchone()[0] for k in ("journal_mode", "synchronous", "foreign_keys", "busy_timeout")}
    assert pragma == {"journal_mode": "wal", "synchronous": 1, "foreign_keys": 1, "busy_timeout": 30000}
    db.close()


def test_checkpoint_is_passive_and_safe(tmp_path):
    db = Database(tmp_path / "s.sqlite3")
    db.conn.execute("CREATE TABLE IF NOT EXISTS t(x)")
    db.conn.execute("INSERT INTO t VALUES (1)")
    busy, log, done = checkpoint(tmp_path / "s.sqlite3")
    assert busy == 0 and done <= log
    db.close()
