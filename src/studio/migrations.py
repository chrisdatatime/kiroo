"""Schema versionado do SQLite (PRAGMA user_version).

Regras:
  * `MIGRATIONS` é uma lista ordenada e numerada (1, 2, 3...). Nunca edite uma migração já publicada: acrescente outra.
  * Todas rodam dentro de UMA transação `BEGIN IMMEDIATE` (o DDL do SQLite é transacional): ou o banco chega à versão
    final, ou nada muda. O lock de escrita também serializa dois processos subindo ao mesmo tempo.
  * Cada migração é idempotente. Banco já atualizado: a chamada custa só um `PRAGMA user_version`.
  * Banco com versão MAIOR que a do código é recusado (código antigo não deve escrever em schema novo).

A migração 1 é o schema completo de hoje. Um banco anterior ao versionamento (user_version=0, com tabelas) é
reconhecido assim: cria o que falta, acrescenta as colunas que faltam (com os mesmos preenchimentos das
migrações antigas), VALIDA tabelas e colunas contra o schema esperado e só então marca a versão 1. Se algo
não puder ser completado (coluna obrigatória ausente, banco corrompido), levanta MigrationError e o banco fica intacto.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable


class MigrationError(RuntimeError):
    pass


# Schema da versão 1 (congelado: cópia do que db/accounts/credits/music/training/agent_chat criavam).
BASELINE_SCHEMA = '''
-- db
CREATE TABLE IF NOT EXISTS productions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    resume_status TEXT,
    status_reason TEXT,
    mode TEXT NOT NULL,
    format_id TEXT NOT NULL,
    product_json TEXT NOT NULL,
    sheet_json TEXT,
    script_json TEXT,
    profiles_json TEXT NOT NULL,
    budget_usd REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenes (
    production_id TEXT NOT NULL REFERENCES productions(id),
    idx INTEGER NOT NULL,
    status TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    current_image_attempt TEXT,
    approved_image_attempt TEXT,
    current_video_attempt TEXT,
    approved_video_attempt TEXT,
    image_correction TEXT,
    video_correction TEXT,
    extra_image_attempts INTEGER NOT NULL DEFAULT 0,
    extra_video_attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (production_id, idx)
);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL,
    scene_idx INTEGER,
    kind TEXT NOT NULL,              -- image | video | plan | review_image | review_video
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,            -- created | submitted | succeeded | failed
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    simulated INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    prompt TEXT,
    params_json TEXT,
    references_json TEXT,
    remote_op_id TEXT,
    output_path TEXT,
    output_sha256 TEXT,
    error TEXT,
    error_permanent INTEGER,
    transient_retries INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    confirmed_cost_usd REAL,
    pricing_source TEXT,
    usage_json TEXT,
    superseded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_attempts_prod ON attempts(production_id, scene_idx, kind);
CREATE INDEX IF NOT EXISTS ix_attempts_hash ON attempts(input_hash);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL,
    scene_idx INTEGER,
    attempt_id TEXT,
    stage TEXT NOT NULL,             -- image | video | final
    reviewer TEXT NOT NULL,          -- auto:<modelo> | human | demo-auto
    decision TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    production_id TEXT NOT NULL,
    scene_idx INTEGER,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    message TEXT,
    data_json TEXT
);
-- Estado do processo que executa a produção (não é o estado da produção): running | idle | interrupted | abandoned.
CREATE TABLE IF NOT EXISTS run_state (
    production_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    resume_attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
-- accounts
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    is_platform_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL REFERENCES users(id),
    mode TEXT NOT NULL DEFAULT 'simulated',
    allow_real INTEGER NOT NULL DEFAULT 0,
    monthly_cap_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id TEXT NOT NULL REFERENCES users(id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    role TEXT NOT NULL DEFAULT 'owner',
    PRIMARY KEY (user_id, workspace_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    csrf TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    key TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_codes (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    tries INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    used_at TEXT
);
-- credits
CREATE TABLE IF NOT EXISTS credit_entries (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount_cc INTEGER NOT NULL,
    usd REAL,
    hold_id TEXT,
    production_id TEXT,
    attempt_id TEXT,
    stage TEXT,
    note TEXT,
    ext_ref TEXT UNIQUE,
    created_by TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_credit_ws ON credit_entries(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS ix_credit_hold ON credit_entries(hold_id);
CREATE INDEX IF NOT EXISTS ix_credit_prod ON credit_entries(production_id);
-- music
CREATE TABLE IF NOT EXISTS music_tracks (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, title TEXT NOT NULL, file TEXT NOT NULL, duration_s REAL, bpm REAL, mood TEXT, genre TEXT, energy TEXT, vocal TEXT,
  collection TEXT, favorite INTEGER NOT NULL DEFAULT 0, start_s REAL NOT NULL DEFAULT 0, origin TEXT, usage_terms TEXT, authorized_at TEXT NOT NULL, reference_url TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS music_favorites (workspace_id TEXT NOT NULL, track_id TEXT NOT NULL, PRIMARY KEY (workspace_id, track_id));
-- training
CREATE TABLE IF NOT EXISTS training_state (
  workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, draft_json TEXT, active_version INTEGER NOT NULL DEFAULT 0, updated_at TEXT,
  PRIMARY KEY (workspace_id, agent_id));
CREATE TABLE IF NOT EXISTS training_versions (
  workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, version INTEGER NOT NULL, config_json TEXT NOT NULL, note TEXT, changes_json TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (workspace_id, agent_id, version));
CREATE TABLE IF NOT EXISTS training_tests (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, agent_id TEXT NOT NULL, draft_hash TEXT NOT NULL, task TEXT, executed INTEGER NOT NULL DEFAULT 0,
  simulated INTEGER NOT NULL DEFAULT 1, current_prompt TEXT, draft_prompt TEXT, current_result TEXT, draft_result TEXT, estimated_cost_usd REAL NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
-- chat
CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    workspace_id TEXT,
    agent TEXT NOT NULL,
    at REAL NOT NULL,
    source TEXT NOT NULL,          -- llm | atalho | sem_ia | falha
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chat_log_user_at ON chat_log(user_id, at);
CREATE INDEX IF NOT EXISTS chat_log_at ON chat_log(at);
'''

# Colunas acrescentadas por ALTER em versões antigas: (tabela, coluna, definição, SQL de preenchimento só ao criar a coluna).
LEGACY_COLUMNS: list[tuple[str, str, str, str | None]] = [
    ("productions", "go_ahead", "TEXT NOT NULL DEFAULT 'all'", None),
    ("productions", "autonomy", "TEXT NOT NULL DEFAULT 'classico'", None),
    ("productions", "edit_style", "TEXT NOT NULL DEFAULT 'dinamico'", None),
    ("productions", "music_id", "TEXT NOT NULL DEFAULT 'auto'", None),
    ("productions", "training_json", "TEXT", None),
    ("productions", "music_json", "TEXT", None),
    ("productions", "workspace_id", "TEXT", None),
    ("workspaces", "credits_exempt", "INTEGER NOT NULL DEFAULT 0",
     "UPDATE workspaces SET credits_exempt=1 WHERE owner_id IN (SELECT id FROM users WHERE is_platform_admin=1)"),
    ("users", "onboarding_done_at", "TEXT", None),
    ("users", "onboarding_step", "INTEGER NOT NULL DEFAULT 0", None),
    ("users", "email_verified_at", "TEXT", "UPDATE users SET email_verified_at=created_at"),
    ("users", "google_sub", "TEXT", None),
]


def split_statements(script: str) -> list[str]:
    """Separa um script em comandos sem usar executescript (que encerraria a transação em andamento)."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip().strip(";").strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        raise MigrationError("script de schema incompleto")
    return [s for s in out if any(not ln.strip().startswith("--") for ln in s.splitlines() if ln.strip())]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")}


def _expected() -> tuple[dict[str, set[str]], set[str]]:
    ref = sqlite3.connect(":memory:")
    try:
        for stmt in split_statements(BASELINE_SCHEMA):
            ref.execute(stmt)
        for table, col, decl, _ in LEGACY_COLUMNS:
            if col not in _columns(ref, table):
                ref.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        return {t: _columns(ref, t) for t in _tables(ref)}, _indexes(ref)
    finally:
        ref.close()


def _m001_baseline(conn: sqlite3.Connection) -> None:
    for stmt in split_statements(BASELINE_SCHEMA):      # CREATE ... IF NOT EXISTS: completa o que falta sem tocar nos dados
        conn.execute(stmt)
    for table, col, decl, fill in LEGACY_COLUMNS:
        if col not in _columns(conn, table):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError as exc:
                raise MigrationError(f"não foi possível completar {table}.{col}: {exc}") from None
            if fill:
                conn.execute(fill)
    want_cols, want_idx = _expected()
    have = _tables(conn)
    problems = []
    for table, cols in sorted(want_cols.items()):
        if table not in have:
            problems.append(f"tabela ausente: {table}")
            continue
        missing = cols - _columns(conn, table)
        if missing:
            problems.append(f"{table}: colunas ausentes {sorted(missing)}")
    for idx in sorted(want_idx - _indexes(conn)):
        problems.append(f"índice ausente: {idx}")
    if problems:
        raise MigrationError("schema existente incompatível com a versão 1: " + "; ".join(problems))
    bad = conn.execute("PRAGMA quick_check").fetchone()[0]
    if bad != "ok":
        raise MigrationError(f"banco com problema de integridade (quick_check: {bad})")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _m002_invites_consent(conn: sqlite3.Connection) -> None:
    """Fase 5: convites de uso único (só o hash do código) e registro do consentimento no cadastro."""
    conn.execute("""CREATE TABLE IF NOT EXISTS invites (
        id TEXT PRIMARY KEY,
        code_hash TEXT NOT NULL UNIQUE,
        email TEXT,                 -- opcional: o convite só vale para este e-mail
        note TEXT,
        created_by TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_at TEXT,
        used_by TEXT
    )""")
    for col in ("terms_accepted_at", "terms_version"):
        if col not in _columns(conn, "users"):
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")


def _m003_prebudget(conn: sqlite3.Connection) -> None:
    """Saldo do cliente × orçamento operacional: pré-orçamento reservado (prebudget_cc), código estável do motivo de
    pausa (pause_code), ajustes por cena e o registro de cobrança por tentativa (production_charges, idempotente).
    Produções antigas ficam com prebudget_cc NULL e seguem o regime antigo (reserva/débito por chamada)."""
    for table, col, decl in (("productions", "prebudget_cc", "INTEGER"), ("productions", "pause_code", "TEXT"),
                             ("scenes", "adjustments_used", "INTEGER NOT NULL DEFAULT 0"),
                             ("scenes", "adjustments_authorized", "INTEGER NOT NULL DEFAULT 0")):
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    conn.execute("""CREATE TABLE IF NOT EXISTS production_charges (
        attempt_id TEXT PRIMARY KEY,          -- uma decisão por tentativa: repetir o acerto não cobra de novo
        production_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        scene_idx INTEGER,
        operation TEXT NOT NULL,              -- image | video | review_image | review_video | plan
        provider TEXT,
        model TEXT,
        cost_usd REAL NOT NULL,               -- custo interno (o que o Kiroo paga ao provedor)
        charged_cc INTEGER NOT NULL,          -- o que saiu do pré-orçamento do cliente
        decision TEXT NOT NULL,               -- charged | technical_failure | absorbed
        created_at TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_charges_prod ON production_charges(production_id)")


def _m004_cost_confirmation(conn: sqlite3.Connection) -> None:
    """Confirmação do custo pelo cliente ("Confirmar e criar vídeo"): sem ela uma produção com pré-orçamento não gasta.
    Produções que já passaram da validação antes desta versão contam como confirmadas (não ficam presas)."""
    for col, decl in (("cost_confirmed_at", "TEXT"), ("cost_confirmed_cc", "INTEGER")):
        if col not in _columns(conn, "productions"):
            conn.execute(f"ALTER TABLE productions ADD COLUMN {col} {decl}")
    conn.execute("UPDATE productions SET cost_confirmed_at=updated_at, cost_confirmed_cc=prebudget_cc WHERE "
                 "prebudget_cc IS NOT NULL AND cost_confirmed_at IS NULL AND status NOT IN "
                 "('received','awaiting_references','validated')")


MIGRATIONS: list[Migration] = [
    Migration(1, "schema completo", _m001_baseline),
    Migration(2, "convites de uso único e consentimento", _m002_invites_consent),
    Migration(3, "pré-orçamento, código de pausa, ajustes por cena e cobrança por tentativa", _m003_prebudget),
    Migration(4, "confirmação do custo pelo cliente antes de gastar", _m004_cost_confirmation),
]
LATEST = MIGRATIONS[-1].version
assert [m.version for m in MIGRATIONS] == list(range(1, LATEST + 1)), "migrações devem ser 1..N em ordem"


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> list[int]:
    """Leva o banco à versão mais recente. Devolve as versões aplicadas (vazio se já estava em dia)."""
    migs = MIGRATIONS if migrations is None else migrations
    latest = migs[-1].version if migs else 0
    version = current_version(conn)
    if version == latest:
        return []
    if version > latest:
        raise MigrationError(f"o banco está na versão {version}, mais nova que a deste código ({latest}): atualize o código")
    if conn.in_transaction:
        raise MigrationError("migrar exige uma conexão sem transação aberta")
    conn.execute("BEGIN IMMEDIATE")
    applied: list[int] = []
    try:
        version = current_version(conn)          # outro processo pode ter migrado enquanto esperávamos o lock
        for m in migs:
            if m.version > version:
                m.apply(conn)
                conn.execute(f"PRAGMA user_version = {int(m.version)}")
                applied.append(m.version)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return applied
