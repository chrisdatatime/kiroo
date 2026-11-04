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
VERIFY_MINUTES = 30
VERIFY_MAX_TRIES = 5
VERIFY_RESEND_S = 45
NO_PASSWORD = "!"  # conta criada pelo Google: login por senha só depois de definir uma (esqueci a senha)
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
        user_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(users)")}
        if "onboarding_done_at" not in user_cols:  # kit de onboarding (Fase 5): concluído/pulado vale em qualquer dispositivo
            db.conn.execute("ALTER TABLE users ADD COLUMN onboarding_done_at TEXT")
        if "onboarding_step" not in user_cols:
            db.conn.execute("ALTER TABLE users ADD COLUMN onboarding_step INTEGER NOT NULL DEFAULT 0")
        if "email_verified_at" not in user_cols:  # verificação de e-mail: quem já tinha conta continua entrando sem nada a fazer
            db.conn.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
            db.conn.execute("UPDATE users SET email_verified_at=created_at")
        if "google_sub" not in user_cols:  # login com Google (id estável da conta Google)
            db.conn.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")

    # ----------------------------------------------------------- usuários
    def create_user(self, email: str, password: str | None, name: str = "", *, admin: bool = False,
                    workspace_name: str | None = None, verified: bool = False,
                    google_sub: str | None = None) -> tuple[str, str]:
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise AuthError("e-mail inválido")
        if google_sub is None or password:
            validate_password(password or "")
        if self.db.conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise AuthError("já existe uma conta com este e-mail")
        uid, wid = new_id("usr"), new_id("ws")
        name = (name or email.split("@")[0]).strip()[:80]
        self.db.conn.execute("INSERT INTO users(id, email, name, pw_hash, is_platform_admin, created_at, email_verified_at, google_sub)"
                             " VALUES (?,?,?,?,?,?,?,?)",
                             (uid, email, name, hash_password(password) if password else NO_PASSWORD, int(admin), now(),
                              now() if verified else None, google_sub))
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

    def onboarding(self, uid: str) -> dict:
        row = self.db.conn.execute("SELECT onboarding_done_at, onboarding_step FROM users WHERE id=?", (uid,)).fetchone()
        return {"done_at": row["onboarding_done_at"], "step": int(row["onboarding_step"] or 0)} if row else {"done_at": None, "step": 0}

    def set_onboarding(self, uid: str, *, step: int | None = None, done: bool | None = None) -> dict:
        """Passo atual do tour (para retomar) e conclusão. done=True marca concluído/pulado; done=False reabre."""
        if step is not None:
            step = int(step)
            if not 0 <= step <= 50:
                raise AuthError("passo inválido")
            self.db.conn.execute("UPDATE users SET onboarding_step=? WHERE id=?", (step, uid))
        if done is True:
            self.db.conn.execute("UPDATE users SET onboarding_done_at=COALESCE(onboarding_done_at, ?) WHERE id=?", (now(), uid))
        elif done is False:
            self.db.conn.execute("UPDATE users SET onboarding_done_at=NULL WHERE id=?", (uid,))
        return self.onboarding(uid)

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
            "SELECT s.*, u.email, u.name, u.is_platform_admin, u.onboarding_done_at, u.onboarding_step, u.email_verified_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=?",
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

    # ----------------------------------------------------------- verificação de e-mail
    def start_verification(self, uid: str) -> str:
        """Gera um código de 6 dígitos (vale 30 min, substitui o anterior). Reenvio no máximo a cada 45 s."""
        u = self.user(uid)
        if not u:
            raise AuthError("conta não encontrada")
        if u["email_verified_at"]:
            raise AuthError("este e-mail já está confirmado")
        row = self.db.conn.execute("SELECT sent_at FROM email_codes WHERE user_id=?", (uid,)).fetchone()
        if row:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["sent_at"])).total_seconds()
            if age < VERIFY_RESEND_S:
                raise AuthError(f"aguarde {int(VERIFY_RESEND_S - age) + 1} s para pedir outro código")
        code = f"{secrets.randbelow(10 ** 6):06d}"
        exp = (datetime.now(timezone.utc) + timedelta(minutes=VERIFY_MINUTES)).isoformat(timespec="seconds")
        self.db.conn.execute("INSERT OR REPLACE INTO email_codes(user_id, code_hash, expires_at, sent_at, tries) VALUES (?,?,?,?,0)",
                             (uid, _sha(f"{uid}:{code}"), exp, now()))
        return code

    def verify_email(self, uid: str, code: str) -> None:
        row = self.db.conn.execute("SELECT * FROM email_codes WHERE user_id=?", (uid,)).fetchone()
        code = re.sub(r"\D", "", code or "")
        if not row or row["expires_at"] < now() or row["tries"] >= VERIFY_MAX_TRIES:
            raise AuthError("código expirado: peça um novo")
        if not hmac.compare_digest(row["code_hash"], _sha(f"{uid}:{code}")):
            self.db.conn.execute("UPDATE email_codes SET tries=tries+1 WHERE user_id=?", (uid,))
            left = VERIFY_MAX_TRIES - row["tries"] - 1
            raise AuthError(f"código incorreto ({left} de {VERIFY_MAX_TRIES} tentativas restantes)" if left else "código incorreto; peça um novo")
        self.db.conn.execute("UPDATE users SET email_verified_at=? WHERE id=?", (now(), uid))
        self.db.conn.execute("DELETE FROM email_codes WHERE user_id=?", (uid,))

    # ----------------------------------------------------------- Google
    def google_user(self, sub: str, email: str, name: str, email_verified: bool, *, allow_create: bool) -> tuple[str, bool]:
        """Conta ligada ao Google: pelo id da conta Google; senão, liga à conta com o mesmo e-mail (só se o Google
        confirmou o e-mail); senão cria (quando o cadastro está aberto). Devolve (user_id, criada_agora)."""
        row = self.db.conn.execute("SELECT id FROM users WHERE google_sub=?", (sub,)).fetchone()
        if row:
            return row["id"], False
        if not email_verified:
            raise AuthError("o Google não confirmou este e-mail; entre com e-mail e senha")
        u = self.user_by_email(email)
        if u:
            self.db.conn.execute("UPDATE users SET google_sub=?, email_verified_at=COALESCE(email_verified_at, ?) WHERE id=?",
                                 (sub, now(), u["id"]))
            return u["id"], False
        if not allow_create:
            raise AuthError("Não há conta com este e-mail. O acesso é por convite: peça sua conta ao administrador.")
        uid, _ = self.create_user(email, None, name, verified=True, google_sub=sub)
        return uid, True

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
        # o link chegou pelo e-mail: vale também como confirmação dele
        self.db.conn.execute("UPDATE users SET pw_hash=?, email_verified_at=COALESCE(email_verified_at, ?) WHERE id=?",
                             (hash_password(new_password), now(), row["user_id"]))
        self.db.conn.execute("UPDATE password_resets SET used_at=? WHERE token_hash=?", (now(), row["token_hash"]))
        self.db.conn.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))  # derruba sessões antigas

    # ----------------------------------------------------------- produções
    def owns(self, wid: str, pid: str) -> bool:
        return bool(self.db.conn.execute("SELECT 1 FROM productions WHERE id=? AND workspace_id=?", (pid, wid)).fetchone())

    def assign_orphans(self, wid: str) -> int:
        """Migração: produções criadas antes das contas passam para o workspace indicado."""
        return self.db.conn.execute("UPDATE productions SET workspace_id=? WHERE workspace_id IS NULL", (wid,)).rowcount
