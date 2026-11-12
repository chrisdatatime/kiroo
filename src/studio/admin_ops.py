"""Operações do administrador da plataforma: UMA camada de regras para a CLI (`studio admin`) e para a aba
Administrador (`/api/admin/*`). Nenhuma das duas repete regra de negócio; as duas chamam `AdminOps`.

Regras que valem para os dois caminhos:
- Toda ação (inclusive a recusada) grava uma linha em `admin_audit` (somente inclusão: gatilhos recusam UPDATE/DELETE)
  com quem, quando, o quê, antes/depois, motivo e IP. Nunca entra senha, token, link de senha nem código de convite.
- Teto da conta nunca acima do teto da plataforma (`paid_gate.validate_account_cap`).
- Mexer na PRÓPRIA conta de forma a subir teto/saldo/modo é permitido, mas exige motivo e fica marcado
  (`self_action=1`) para aparecer em destaque.

Só pela interface web (ator `web`):
- Máximo por lançamento (`STUDIO_ADMIN_MAX_GRANT`, padrão 200 créditos) e por dia por administrador
  (`STUDIO_ADMIN_DAILY_GRANT_CAP`, padrão 1000). Acima disso, só pela CLI.
- Concessão/ajuste exige chave de idempotência (duplo clique não credita duas vezes) e ajuste negativo exige digitar o
  e-mail da conta alvo.
- Apagar conta, criar/remover administrador: só CLI (o serviço recusa `delete_user` do ator web; não há método web
  para promover alguém).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import paid_gate
from .accounts import INVITE_MAX_DAYS, RESET_MINUTES, Accounts
from .credits import Ledger, fmt
from .db import Database, now

log = logging.getLogger("studio")

DEFAULT_MAX_GRANT = 200
DEFAULT_DAILY_GRANT_CAP = 1000
UID_RE = re.compile(r"^usr_[0-9a-f]{10}$")
INVITE_ID_RE = re.compile(r"^inv_[0-9a-f]{10}$")
IDEM_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
REASON_MAX = 300


def _int_env(name: str, default: int) -> int:
    try:
        return max(int(float(os.environ.get(name) or default)), 0)
    except ValueError:
        return default


def max_grant() -> int:
    """Créditos máximos por lançamento feito pela interface web."""
    return _int_env("STUDIO_ADMIN_MAX_GRANT", DEFAULT_MAX_GRANT)


def daily_grant_cap() -> int:
    """Créditos máximos concedidos por dia (UTC) por administrador pela interface web."""
    return _int_env("STUDIO_ADMIN_DAILY_GRANT_CAP", DEFAULT_DAILY_GRANT_CAP)


class AdminError(ValueError):
    status = 400


class NotFound(AdminError):
    status = 404


class Forbidden(AdminError):
    status = 403


class Conflict(AdminError):
    status = 409


@dataclass(frozen=True)
class Actor:
    kind: str                     # "web" | "cli"
    user_id: str | None = None
    email: str | None = None
    ip: str | None = None

    @property
    def web(self) -> bool:
        return self.kind == "web"

    @property
    def label(self) -> str:       # vai em credit_entries.created_by
        return "cli" if self.kind == "cli" else f"admin:{self.user_id}"


CLI = Actor("cli")


def _clean_reason(reason) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(reason or "")).strip()[:REASON_MAX]


def _utc_day_start() -> str:
    d = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.isoformat(timespec="seconds")


def _ws_view(ws) -> dict:
    return {"mode": ws["mode"], "allow_real": bool(ws["allow_real"]), "monthly_cap_usd": ws["monthly_cap_usd"]}


class AdminOps:
    def __init__(self, db: Database, actor: Actor = CLI, *, data_dir: Path | None = None):
        self.db = db
        self.actor = actor
        self.acc = Accounts(db)
        self.ledger = Ledger(db)
        self.data_dir = data_dir

    # ------------------------------------------------------------------ auditoria
    def _audit(self, action: str, user=None, ws=None, *, before=None, after=None, amount_cc: int | None = None,
               reason: str = "", self_action: bool = False, key: str | None = None, result: str = "ok",
               error: str | None = None, target_email: str | None = None) -> None:
        a = self.actor
        self.db.conn.execute(
            "INSERT INTO admin_audit(at, actor_kind, actor_user_id, actor_email, ip, action, target_user_id, target_email,"
            " target_workspace_id, before_json, after_json, amount_cc, reason, self_action, idempotency_key, result, error)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now(), a.kind, a.user_id, a.email, a.ip, action, user["id"] if user else None,
             (user["email"] if user else target_email), ws["id"] if ws else None,
             json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
             json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
             amount_cc, _clean_reason(reason) or None, int(bool(self_action)), key, result, (error or "")[:300] or None))
        if result == "ok":
            log.info("ação de administrador", extra={"event": f"admin_{action.replace('-', '_')}"})
            if self_action:
                log.warning("administrador alterou a própria conta", extra={"event": "admin_self_action"})

    def record(self, action: str, *, target_email: str | None = None, after=None, reason: str = "") -> None:
        """Registro de ação que não passa pelos métodos abaixo (ex.: `create-user` da CLI)."""
        user = self.acc.user_by_email(target_email) if target_email else None
        ws = self._owned_ws(user["id"]) if user else None
        self._audit(action, user, ws, after=after, reason=reason, target_email=target_email)

    def _run(self, action: str, user, ws, fn, *, reason: str = "", amount_cc: int | None = None, key: str | None = None):
        """Executa `fn`; se a regra recusar, grava a recusa na auditoria e repassa o erro."""
        try:
            return fn()
        except ValueError as exc:            # AdminError, AuthError e validações (teto, modo...) são ValueError
            self._audit(action, user, ws, amount_cc=amount_cc, reason=reason, key=key, result="refused",
                        error=str(exc), self_action=bool(user and user["id"] == self.actor.user_id))
            raise

    # ------------------------------------------------------------------ alvos
    def _owned_ws(self, uid: str):
        ws = self.db.conn.execute("SELECT * FROM workspaces WHERE owner_id=? ORDER BY created_at LIMIT 1", (uid,)).fetchone()
        if ws is None:
            rows = self.acc.workspaces_of(uid)
            ws = self.acc.workspace(rows[0]["id"]) if rows else None
        return ws

    def target(self, uid: str):
        """(usuário, estúdio dele). Id malformado ou inexistente → NotFound (a web responde 404)."""
        if not isinstance(uid, str) or not UID_RE.match(uid):
            raise NotFound("conta não encontrada")
        user = self.acc.user(uid)
        ws = self._owned_ws(uid) if user else None
        if not user or not ws:
            raise NotFound("conta não encontrada")
        return user, ws

    def uid_by_email(self, email: str) -> str:
        u = self.acc.user_by_email(email)
        if not u:
            raise NotFound("usuário não encontrado")
        return u["id"]

    def _self(self, user) -> bool:
        return self.actor.user_id is not None and user["id"] == self.actor.user_id

    def _need_reason_if_self(self, user, elevating: bool, reason: str) -> None:
        if self.actor.web and elevating and self._self(user) and not _clean_reason(reason):
            raise AdminError("ao alterar a sua própria conta, informe o motivo (fica em destaque na auditoria)")

    # ------------------------------------------------------------------ leitura
    def accounts(self) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT u.id, u.email, u.name, u.is_platform_admin, u.email_verified_at, u.google_sub, u.pw_hash, u.created_at,"
            " w.id wid, w.name wname, w.mode, w.allow_real, w.monthly_cap_usd, w.credits_exempt"
            " FROM users u JOIN workspaces w ON w.id = (SELECT id FROM workspaces x WHERE x.owner_id=u.id ORDER BY x.created_at LIMIT 1)"
            " ORDER BY u.created_at").fetchall()
        out = []
        for r in rows:
            bal, held = self.ledger.balance(r["wid"]), self.ledger.held(r["wid"])
            out.append({"id": r["id"], "email": r["email"], "name": r["name"], "admin": bool(r["is_platform_admin"]),
                        "email_verified": bool(r["email_verified_at"]), "google": bool(r["google_sub"]),
                        "has_password": r["pw_hash"] != "!", "created_at": r["created_at"],
                        "workspace": {"id": r["wid"], "name": r["wname"]}, "mode": r["mode"],
                        "allow_real": bool(r["allow_real"]), "monthly_cap_usd": r["monthly_cap_usd"],
                        "effective_cap_usd": paid_gate.effective_cap(r["monthly_cap_usd"]),
                        "exempt": bool(r["credits_exempt"]), "balance_cc": bal, "balance": fmt(bal),
                        "held_cc": held, "held": fmt(held)})
        return out

    def statement(self, uid: str, limit: int = 100) -> dict:
        user, ws = self.target(uid)
        return {"account": {"id": user["id"], "email": user["email"]}, **self.ledger.summary(ws["id"]),
                "statement": self.ledger.statement(ws["id"], limit=max(1, min(int(limit), 500)))}

    def invites(self) -> list[dict]:
        t = now()
        return [{"id": r["id"], "email": r["email"], "note": r["note"], "created_at": r["created_at"],
                 "expires_at": r["expires_at"], "used_at": r["used_at"],
                 "state": "usado" if r["used_at"] else ("expirado" if r["expires_at"] < t else "válido")}
                for r in self.acc.invites()]

    def audit_log(self, limit: int = 200, before_id: int | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        q, args = "SELECT * FROM admin_audit", []
        if before_id:
            q, args = q + " WHERE id < ?", [int(before_id)]
        rows = self.db.conn.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("before_json", "after_json"):
                d[k[:-5]] = json.loads(d.pop(k)) if d[k] else None
            d["self_action"] = bool(d["self_action"])
            d["amount"] = fmt(d["amount_cc"]) if d["amount_cc"] is not None else None
            out.append(d)
        return out

    def grants_today(self) -> int:
        """Centésimos concedidos hoje (UTC) por este administrador pela web (só lançamentos positivos)."""
        return self.db.conn.execute(
            "SELECT COALESCE(SUM(amount_cc),0) FROM admin_audit WHERE actor_kind='web' AND actor_user_id=? AND result='ok'"
            " AND action IN ('grant','adjust') AND amount_cc > 0 AND at >= ?", (self.actor.user_id, _utc_day_start())).fetchone()[0]

    def limits(self) -> dict:
        used = self.grants_today() if self.actor.web else 0
        cap = daily_grant_cap()
        return {"max_grant": max_grant(), "daily_cap": cap, "used_today_cc": used, "used_today": fmt(used),
                "left_today_cc": max(cap * 100 - used, 0), "left_today": fmt(max(cap * 100 - used, 0)),
                "platform_cap_usd": paid_gate.platform_cap()}

    def metrics(self, days: int = 30) -> dict:
        from .metrics import internal_metrics
        return internal_metrics(self.db, days)

    # ------------------------------------------------------------------ modo real, modo e teto
    def allow_real(self, uid: str, reason: str = "") -> dict:
        user, ws = self.target(uid)

        def go():
            self._need_reason_if_self(user, not ws["allow_real"], reason)
            self.acc.set_workspace(ws["id"], allow_real=1)
            after = _ws_view(self.acc.workspace(ws["id"]))
            self._audit("allow-real", user, ws, before=_ws_view(ws), after=after, reason=reason,
                        self_action=self._self(user))
            return after
        return self._run("allow-real", user, ws, go, reason=reason)

    def deny_real(self, uid: str, reason: str = "") -> dict:
        user, ws = self.target(uid)

        def go():
            self.acc.set_workspace(ws["id"], allow_real=0, mode="simulated")
            after = _ws_view(self.acc.workspace(ws["id"]))
            self._audit("deny-real", user, ws, before=_ws_view(ws), after=after, reason=reason, self_action=self._self(user))
            return after
        return self._run("deny-real", user, ws, go, reason=reason)

    def set_mode(self, uid: str, mode: str, reason: str = "") -> dict:
        user, ws = self.target(uid)
        mode = (mode or "").strip().lower()

        def go():
            if mode not in ("simulated", "real"):
                raise AdminError("informe o modo: simulated ou real")
            if mode == "real" and not ws["allow_real"]:
                raise AdminError("este estúdio não tem o modo real liberado; libere antes (allow-real)")
            self._need_reason_if_self(user, mode == "real" and ws["mode"] != "real", reason)
            with self.ledger.transaction():
                self.acc.set_workspace(ws["id"], mode=mode)
                self.ledger.add(ws["id"], 0, kind="adjust", by=self.actor.label, note=f"admin set-mode: {ws['mode']} -> {mode}")
                after = _ws_view(self.acc.workspace(ws["id"]))
                self._audit("set-mode", user, ws, before=_ws_view(ws), after=after, reason=reason, self_action=self._self(user))
            warn = None
            if mode == "real" and paid_gate.effective_cap(ws["monthly_cap_usd"]) <= 0:
                warn = "o teto efetivo é US$0.00, então nada será gasto; defina o teto do estúdio"
            return {**after, "previous_mode": ws["mode"], "warning": warn}
        return self._run("set-mode", user, ws, go, reason=reason)

    def set_cap(self, uid: str, usd, reason: str = "") -> dict:
        user, ws = self.target(uid)

        def go():
            if usd is None:
                raise AdminError("informe o teto em US$, de 0 até o teto da plataforma")
            value = paid_gate.validate_account_cap(usd)      # nunca acima do teto da plataforma (ValueError)
            self._need_reason_if_self(user, value > float(ws["monthly_cap_usd"] or 0), reason)
            plat = paid_gate.platform_cap()
            with self.ledger.transaction():
                self.acc.set_workspace(ws["id"], monthly_cap_usd=value)
                self.ledger.add(ws["id"], 0, kind="adjust", by=self.actor.label,
                                note=f"admin set-cap: US${ws['monthly_cap_usd']:.2f} -> US${value:.2f} (plataforma US${plat:.2f})")
                after = _ws_view(self.acc.workspace(ws["id"]))
                self._audit("set-cap", user, ws, before=_ws_view(ws), after=after, reason=reason, self_action=self._self(user))
            return {**after, "previous_cap_usd": ws["monthly_cap_usd"], "effective_cap_usd": paid_gate.effective_cap(value),
                    "platform_cap_usd": plat}
        return self._run("set-cap", user, ws, go, reason=reason)

    # ------------------------------------------------------------------ créditos
    def grant(self, uid: str, credits, reason: str, *, idempotency_key: str | None = None) -> dict:
        return self._credit("grant", uid, credits, reason, idempotency_key, None)

    def adjust(self, uid: str, credits, reason: str, *, idempotency_key: str | None = None,
               confirm_email: str | None = None) -> dict:
        return self._credit("adjust", uid, credits, reason, idempotency_key, confirm_email)

    def _credit(self, kind: str, uid: str, credits, reason: str, key: str | None, confirm_email: str | None) -> dict:
        user, ws = self.target(uid)
        reason = _clean_reason(reason)
        cc = None
        if isinstance(credits, (int, float)) and not isinstance(credits, bool) and math.isfinite(credits):
            cc = int(round(credits * 100))

        def go():
            if cc is None:
                raise AdminError("informe a quantidade de créditos (número)")
            if kind == "grant" and cc <= 0:
                raise AdminError("a concessão precisa ser positiva (para tirar créditos use o ajuste)")
            if kind == "adjust" and cc == 0:
                raise AdminError("o ajuste precisa ser diferente de zero")
            if not reason:
                raise AdminError("informe o motivo do lançamento")
            if self.actor.web:
                if not isinstance(key, str) or not IDEM_RE.match(key):
                    raise AdminError("chave de idempotência ausente ou inválida")
                if cc < 0 and (confirm_email or "").strip().lower() != user["email"].lower():
                    raise AdminError("para tirar créditos, digite o e-mail da conta alvo para confirmar")
                if abs(cc) > max_grant() * 100:
                    raise Forbidden(f"acima de {max_grant()} créditos por lançamento: faça pela CLI")
            ext_ref = f"admin:{self.actor.user_id or 'cli'}:{key}" if key else None
            with self.ledger.transaction():      # limite do dia + lançamento + auditoria: tudo ou nada, sob o lock
                if ext_ref:
                    prev = self.db.conn.execute("SELECT id, workspace_id, amount_cc, kind FROM credit_entries WHERE ext_ref=?",
                                                (ext_ref,)).fetchone()
                    if prev:
                        if (prev["workspace_id"], prev["amount_cc"], prev["kind"]) != (ws["id"], cc, kind):
                            raise Conflict("esta chave de idempotência já foi usada em outro lançamento")
                        bal = self.ledger.balance(ws["id"])
                        self._audit(kind, user, ws, amount_cc=cc, reason=reason, key=key, result="duplicate",
                                    self_action=self._self(user))
                        return {"duplicate": True, "entry_id": prev["id"], "balance_cc": bal, "balance": fmt(bal)}
                if self.actor.web and cc > 0:
                    used, cap = self.grants_today(), daily_grant_cap() * 100
                    if used + cc > cap:
                        raise Forbidden(f"limite diário de {daily_grant_cap()} créditos por administrador atingido "
                                        f"(hoje: {fmt(used)}); acima disso, só pela CLI")
                if cc > 0:
                    self._need_reason_if_self(user, True, reason)
                before = self.ledger.balance(ws["id"])
                eid = self.ledger.add(ws["id"], cc, kind=kind, note=reason, ext_ref=ext_ref, by=self.actor.label)
                after = self.ledger.balance(ws["id"])
                self._audit(kind, user, ws, before={"balance_cc": before}, after={"balance_cc": after}, amount_cc=cc,
                            reason=reason, key=key, self_action=self._self(user))
            return {"duplicate": False, "entry_id": eid, "balance_before_cc": before, "balance_cc": after,
                    "balance": fmt(after), "amount": fmt(cc)}
        return self._run(kind, user, ws, go, reason=reason, amount_cc=cc, key=key)

    # ------------------------------------------------------------------ convites
    def create_invite(self, *, days: int = 7, email: str | None = None, note: str = "") -> dict:
        """O código aparece só no retorno (uma vez). Na auditoria e no banco: só o id e o hash."""
        bound = (email or "").strip().lower() or None

        def go():
            try:
                d = int(days)
            except (TypeError, ValueError):
                raise AdminError(f"validade do convite: de 1 a {INVITE_MAX_DAYS} dias") from None
            code, exp = self.acc.create_invite(days=d, email=bound, note=_clean_reason(note)[:200], by=self.actor.label)
            iid = self.db.conn.execute("SELECT id FROM invites WHERE code_hash=?", (self.acc._invite_key(code),)).fetchone()["id"]
            self._audit("create-invite", None, None, target_email=bound, reason=note,
                        after={"invite_id": iid, "expires_at": exp, "days": d, "bound_to_email": bool(bound)})
            return {"id": iid, "code": code, "expires_at": exp, "email": bound}
        return self._run("create-invite", None, None, go, reason=note)

    def revoke_invite(self, invite_id: str, reason: str = "") -> dict:
        def go():
            if not isinstance(invite_id, str) or not INVITE_ID_RE.match(invite_id):
                raise NotFound("convite não encontrado")
            row = self.db.conn.execute("SELECT id, email, expires_at, used_at FROM invites WHERE id=?", (invite_id,)).fetchone()
            if not row or row["used_at"] or row["expires_at"] < now() or not self.acc.revoke_invite(invite_id):
                raise NotFound("convite não encontrado, já usado, expirado ou revogado")
            self._audit("revoke-invite", None, None, target_email=row["email"], reason=reason,
                        before={"invite_id": invite_id, "expires_at": row["expires_at"]},
                        after={"invite_id": invite_id, "revoked": True})
            return {"id": invite_id, "revoked": True}
        return self._run("revoke-invite", None, None, go, reason=reason)

    # ------------------------------------------------------------------ e-mail, senha, dados
    def verify_email(self, uid: str, reason: str = "") -> dict:
        user, ws = self.target(uid)

        def go():
            self.db.conn.execute("UPDATE users SET email_verified_at=COALESCE(email_verified_at, ?) WHERE id=?", (now(), uid))
            self.db.conn.execute("DELETE FROM email_codes WHERE user_id=?", (uid,))
            self._audit("verify-email", user, ws, before={"email_verified": bool(user["email_verified_at"])},
                        after={"email_verified": True}, reason=reason, self_action=self._self(user))
            return {"email_verified": True}
        return self._run("verify-email", user, ws, go, reason=reason)

    def reset_link(self, uid: str, base_url: str, reason: str = "") -> dict:
        """Link de nova senha (30 min, uso único). Aparece só no retorno; a auditoria registra apenas que foi gerado."""
        user, ws = self.target(uid)

        def go():
            token = self.acc.start_reset(user["email"])
            self._audit("reset-link", user, ws, after={"link_generated": True, "valid_minutes": RESET_MINUTES},
                        reason=reason, self_action=self._self(user))
            return {"link": f"{base_url.rstrip('/')}/?reset={token}", "valid_minutes": RESET_MINUTES}
        return self._run("reset-link", user, ws, go, reason=reason)

    def export_user(self, uid: str, reason: str = "") -> dict:
        from .privacy import export_account
        user, ws = self.target(uid)

        def go():
            data = export_account(self.db, self.data_dir, uid)
            self._audit("export-user", user, ws, after={"exported": True}, reason=reason, self_action=self._self(user))
            return data
        return self._run("export-user", user, ws, go, reason=reason)

    def delete_user(self, uid: str, reason: str = "") -> dict:
        """Apagar conta: SÓ pela CLI. O ator web é recusado (e a recusa fica na auditoria)."""
        from .privacy import delete_account
        user, ws = self.target(uid)

        def go():
            if self.actor.web:
                raise Forbidden("apagar conta só pela CLI (studio admin delete-user)")
            snapshot = {"email_verified": bool(user["email_verified_at"]), "admin": bool(user["is_platform_admin"]),
                        "balance_cc": self.ledger.balance(ws["id"])}
            done = delete_account(self.db, self.data_dir, uid, allow_admin=True)
            self._audit("delete-user", user, ws, before=snapshot, after={"deleted": True, **done}, reason=reason)
            return done
        return self._run("delete-user", user, ws, go, reason=reason)
