"""Contas, workspaces e sessões (Fase B).

- Senha: scrypt (stdlib) com sal aleatório; comparação em tempo constante.
- Sessão: token aleatório no cookie HttpOnly; no banco só o SHA-256 do token. CSRF por sessão (cabeçalho).
- Workspace: unidade de isolamento (produções, mídia, gastos, teto do mês, modo DEMO/real).
- Contas novas ficam em DEMO: só workspaces com `allow_real` (liberado pelo admin) geram de verdade.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from .db import Database, new_id, now

SESSION_DAYS = 30
RESET_MINUTES = 30
LOGIN_WINDOW_MIN = 15
LOGIN_MAX_FAILS = 8
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,24}$", re.I)

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    used_at TEXT
);
"""


class AuthError(ValueError):
    pass


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(dk) // 2)
        return hmac.compare_digest(got.hex(), dk)
    except (ValueError, TypeError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 10:
        raise AuthError("a senha precisa ter pelo menos 10 caracteres")
    if len(password) > 200:
        raise AuthError("senha longa demais")


class Accounts:
    def __init__(self, db: Database):
        self.db = db
        db.conn.executescript(SCHEMA)
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(productions)")}
        if "workspace_id" not in cols:
            db.conn.execute("ALTER TABLE productions ADD COLUMN workspace_id TEXT")
        ws_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(workspaces)")}
        if "credits_exempt" not in ws_cols:  # dono da plataforma: consumo registrado, saldo não exigido (Fase C)
            db.conn.execute("ALTER TABLE workspaces ADD COLUMN credits_exempt INTEGER NOT NULL DEFAULT 0")
            db.conn.execute("UPDATE workspaces SET credits_exempt=1 WHERE owner_id IN"
                            " (SELECT id FROM users WHERE is_platform_admin=1)")

    # ----------------------------------------------------------- usuários
    def create_user(self, email: str, password: str, name: str = "", *, admin: bool = False,
                    workspace_name: str | None = None) -> tuple[str, str]:
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise AuthError("e-mail inválido")
        validate_password(password)
        if self.db.conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise AuthError("já existe uma conta com este e-mail")
        uid, wid = new_id("usr"), new_id("ws")
        name = (name or email.split("@")[0]).strip()[:80]
        self.db.conn.execute("INSERT INTO users(id, email, name, pw_hash, is_platform_admin, created_at) VALUES (?,?,?,?,?,?)",
                             (uid, email, name, hash_password(password), int(admin), now()))
        self.db.conn.execute("INSERT INTO workspaces(id, name, owner_id, created_at) VALUES (?,?,?,?)",
                             (wid, (workspace_name or f"Estúdio de {name}")[:80], uid, now()))
        self.db.conn.execute("INSERT INTO memberships(user_id, workspace_id, role) VALUES (?,?,'owner')", (uid, wid))
        return uid, wid

    def user(self, uid: str):
        return self.db.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def user_by_email(self, email: str):
        return self.db.conn.execute("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()

    def workspace(self, wid: str):
        return self.db.conn.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()

    def workspaces_of(self, uid: str):
        return self.db.conn.execute("SELECT w.*, m.role FROM workspaces w JOIN memberships m ON m.workspace_id=w.id"
                                    " WHERE m.user_id=? ORDER BY w.created_at", (uid,)).fetchall()

    def set_workspace(self, wid: str, **fields) -> None:
        allowed = {"name", "mode", "allow_real", "monthly_cap_usd", "credits_exempt"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if "mode" in fields and fields["mode"] not in {"simulated", "real"}:
            raise AuthError("modo inválido")
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            self.db.conn.execute(f"UPDATE workspaces SET {cols} WHERE id=?", (*fields.values(), wid))

    # ----------------------------------------------------------- login
    def _throttled(self, key: str) -> bool:
        since = (datetime.now(timezone.utc) - timedelta(minutes=LOGIN_WINDOW_MIN)).isoformat(timespec="seconds")
        self.db.conn.execute("DELETE FROM login_attempts WHERE ts < ?", (since,))
        n = self.db.conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key=?", (key,)).fetchone()[0]
        return n >= LOGIN_MAX_FAILS

    def login(self, email: str, password: str, ip: str = "") -> tuple[str, dict]:
        email = (email or "").strip().lower()
        keys = [f"e:{email}", f"i:{ip}"] if ip else [f"e:{email}"]
        if any(self._throttled(k) for k in keys):
            raise AuthError(f"muitas tentativas; espere {LOGIN_WINDOW_MIN} minutos")
        u = self.user_by_email(email)
        if not u or not verify_password(password, u["pw_hash"]):
            for k in keys:
                self.db.conn.execute("INSERT INTO login_attempts(key, ts) VALUES (?,?)", (k, now()))
            raise AuthError("e-mail ou senha incorretos")  # mesma mensagem para não revelar quem tem conta
        for k in keys:
            self.db.conn.execute("DELETE FROM login_attempts WHERE key=?", (k,))
        ws = self.workspaces_of(u["id"])
        return self.create_session(u["id"], ws[0]["id"])

    def create_session(self, uid: str, wid: str) -> tuple[str, dict]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
        self.db.conn.execute("INSERT INTO sessions(token_hash, user_id, workspace_id, csrf, created_at, expires_at) VALUES (?,?,?,?,?,?)",
                             (_sha(token), uid, wid, csrf, now(), exp))
        return token, {"csrf": csrf, "user_id": uid, "workspace_id": wid}

    def session(self, token: str | None):
        if not token:
            return None
        row = self.db.conn.execute(
            "SELECT s.*, u.email, u.name, u.is_platform_admin FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=?",
            (_sha(token),)).fetchone()
        if not row or row["expires_at"] < now():
            return None
        return row

    def logout(self, token: str | None) -> None:
        if token:
            self.db.conn.execute("DELETE FROM sessions WHERE token_hash=?", (_sha(token),))

    def switch_workspace(self, token: str, wid: str) -> None:
        s = self.session(token)
        if not s or not self.db.conn.execute("SELECT 1 FROM memberships WHERE user_id=? AND workspace_id=?",
                                             (s["user_id"], wid)).fetchone():
            raise AuthError("workspace não encontrado")
        self.db.conn.execute("UPDATE sessions SET workspace_id=? WHERE token_hash=?", (wid, _sha(token)))

    # ----------------------------------------------------------- senha
    def start_reset(self, email: str) -> str | None:
        u = self.user_by_email(email)
        if not u:
            return None  # não revela se o e-mail existe
        token = secrets.token_urlsafe(32)
        exp = (datetime.now(timezone.utc) + timedelta(minutes=RESET_MINUTES)).isoformat(timespec="seconds")
        self.db.conn.execute("INSERT INTO password_resets(token_hash, user_id, expires_at) VALUES (?,?,?)", (_sha(token), u["id"], exp))
        return token

    def finish_reset(self, token: str, new_password: str) -> None:
        validate_password(new_password)
        row = self.db.conn.execute("SELECT * FROM password_resets WHERE token_hash=?", (_sha(token or ""),)).fetchone()
        if not row or row["used_at"] or row["expires_at"] < now():
            raise AuthError("link de redefinição inválido ou expirado")
        self.db.conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new_password), row["user_id"]))
        self.db.conn.execute("UPDATE password_resets SET used_at=? WHERE token_hash=?", (now(), row["token_hash"]))
        self.db.conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))  # derruba sessões antigas

    # ----------------------------------------------------------- produções
    def owns(self, wid: str, pid: str) -> bool:
        return bool(self.db.conn.execute("SELECT 1 FROM productions WHERE id=? AND workspace_id=?", (pid, wid)).fetchone())

    def assign_orphans(self, wid: str) -> int:
        """Migração: produções criadas antes das contas passam para o workspace indicado."""
        return self.db.conn.execute("UPDATE productions SET workspace_id=? WHERE workspace_id IS NULL", (wid,)).rowcount
