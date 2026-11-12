"""Rotas da aba Administrador (`/api/admin/*`). As regras de negócio vivem em `admin_ops.AdminOps` (a mesma camada da
CLI); aqui ficam só as proteções HTTP, checadas NO SERVIDOR em cada rota:

- Quem não é administrador da plataforma (ou nem entrou) recebe 404 em qualquer `/api/admin/*` (a checagem fica em
  `App.handle`, antes de tudo, e é repetida aqui por garantia).
- Toda rota que muda estado (POST): token CSRF da sessão (`X-Studio-Token`) + `Origin` do próprio host
  (+ `Sec-Fetch-Site: same-origin` quando o navegador manda). Sem isso → 403.
- Ações sensíveis (todo POST menos o próprio `reauth`) exigem login ou reautenticação recente
  (`STUDIO_ADMIN_REAUTH_MINUTES`, padrão 10): senha (com Turnstile, se ligado) ou, conta só Google, entrar de novo
  pelo Google (a sessão nova conta como login recente).
- Respostas com `Cache-Control: no-store, private` e `Pragma: no-cache`. CSP e demais cabeçalhos: os do app, sem afrouxar.
- Limite de requisições próprio (`STUDIO_RATE_ADMIN`, por usuário), além do geral de /api.
Criar/remover administrador e apagar conta NÃO existem aqui (só CLI).
"""

from __future__ import annotations

import dataclasses
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from ..accounts import LOGIN_WINDOW_MIN, verify_password
from ..admin_ops import Actor, AdminError, AdminOps
from ..db import Database
from ..logs import redact

NO_STORE = {"Cache-Control": "no-store, private, max-age=0", "Pragma": "no-cache", "Expires": "0",
            "X-Robots-Tag": "noindex, nofollow"}
DEFAULT_REAUTH_MIN = 10
ACCOUNT_ACTIONS = {"allow-real", "deny-real", "set-mode", "set-cap", "grant", "adjust", "verify-email", "reset-link", "export"}
ACCOUNT_RE = re.compile(r"/api/admin/accounts/(usr_[0-9a-f]{10})/([a-z-]+)")
INVITE_RE = re.compile(r"/api/admin/invites/(inv_[0-9a-f]{10})/revoke")


def reauth_minutes() -> int:
    try:
        return max(int(os.environ.get("STUDIO_ADMIN_REAUTH_MINUTES") or DEFAULT_REAUTH_MIN), 1)
    except ValueError:
        return DEFAULT_REAUTH_MIN


def is_admin_path(path: str) -> bool:
    return path == "/api/admin" or path.startswith("/api/admin/")


def _reply(status: int, data, headers: dict | None = None):
    from .server import _json
    return _json(status, data, {**(headers or {}), **NO_STORE})


def not_found():
    return _reply(404, {"error": "não encontrado"})


def _recent_until(sess) -> datetime | None:
    """Até quando vale a autenticação recente desta sessão (login ou reautenticação)."""
    marks = [sess["created_at"]]
    if "reauth_at" in sess.keys() and sess["reauth_at"]:
        marks.append(sess["reauth_at"])
    last = max(datetime.fromisoformat(m) for m in marks)
    return last + timedelta(minutes=reauth_minutes())


def recent_auth(sess) -> bool:
    return _recent_until(sess) > datetime.now(timezone.utc)


def same_origin(headers: dict) -> bool:
    """POST do próprio site: Origin presente e igual ao host da requisição (já conferido na lista de hosts)."""
    origin = headers.get("Origin") or ""
    host = (headers.get("Host") or "").lower()
    o = urlparse(origin)
    if o.scheme not in ("http", "https") or not host or (o.netloc or "").lower() != host:
        return False
    site = headers.get("Sec-Fetch-Site")
    return site is None or site == "same-origin"


def handle(app, method: str, path: str, url, headers: dict, payload, ctx, token: str):
    sess = ctx["sess"]
    if not ctx["admin"]:                      # repetido de App.handle: autorização sempre no servidor
        return not_found()
    actor = Actor("web", user_id=sess["user_id"], email=sess["email"], ip=app._client_ip(headers))
    s = app.settings()
    db = Database(s.db_path)
    try:
        ops = AdminOps(db, actor, data_dir=s.data_dir)
        if method == "GET":
            return _get(app, path, url, ops, sess)
        if method != "POST":
            return not_found()
        if headers.get("X-Studio-Token") != sess["csrf"] or not same_origin(headers):
            return _reply(403, {"error": "requisição recusada (origem ou verificação da sessão inválida)", "code": "csrf"})
        if not isinstance(payload, dict):
            return _reply(400, {"error": "corpo inválido"})
        if path == "/api/admin/reauth":
            return _reauth(app, headers, payload, ops, sess, token)
        if not recent_auth(sess):
            return _reply(403, {"error": f"confirme sua identidade para continuar (vale {reauth_minutes()} min)",
                                "code": "reauth_required"})
        return _post(app, path, headers, payload, ops)
    except AdminError as exc:
        return _reply(exc.status, {"error": redact(exc), "code": type(exc).__name__.lower()})
    except ValueError as exc:
        return _reply(400, {"error": redact(exc)})
    finally:
        db.close()


def _get(app, path: str, url, ops: AdminOps, sess):
    q = parse_qs(url.query)

    def qint(name: str, default: int) -> int:
        try:
            return int(q.get(name, [default])[0])
        except (TypeError, ValueError):
            return default

    if path == "/api/admin/overview":
        u = ops.acc.user(sess["user_id"])
        until = _recent_until(sess)
        return _reply(200, {"me": {"id": u["id"], "email": u["email"], "has_password": u["pw_hash"] != "!",
                                   "google": bool(u["google_sub"])},
                            "reauth": {"ok": until > datetime.now(timezone.utc), "until": until.isoformat(timespec="seconds"),
                                       "minutes": reauth_minutes()},
                            "limits": ops.limits(), "signup": app.signup, "google_enabled": app.google_enabled,
                            "turnstile": app.turnstile_site if app.turnstile_on and not app.turnstile_broken else None})
    if path == "/api/admin/accounts":
        return _reply(200, {"accounts": ops.accounts(), "limits": ops.limits()})
    m = re.fullmatch(r"/api/admin/accounts/(usr_[0-9a-f]{10})/statement", path)
    if m:
        return _reply(200, ops.statement(m.group(1), limit=qint("limit", 100)))
    if path == "/api/admin/invites":
        return _reply(200, {"invites": ops.invites()})
    if path == "/api/admin/metrics":
        return _reply(200, ops.metrics(max(qint("days", 30), 0)))
    if path == "/api/admin/audit":
        before = qint("before", 0) or None
        return _reply(200, {"entries": ops.audit_log(limit=qint("limit", 100), before_id=before)})
    return not_found()


def _reauth(app, headers: dict, p: dict, ops: AdminOps, sess, token: str):
    """Confirma a senha (Turnstile antes, se ligado: não é contornado). Conta só Google: entrar de novo pelo Google."""
    u = ops.acc.user(sess["user_id"])
    if u["pw_hash"] == "!":
        return _reply(400, {"error": "Sua conta entra pelo Google: entre de novo com o Google para confirmar.",
                            "code": "google_reauth"})
    ip = app._client_ip(headers)
    if (blocked := app._captcha(p, ip)) is not None:
        return dataclasses.replace(blocked, headers={**blocked.headers, **NO_STORE})
    key = f"r:{u['id']}"
    if ops.acc.throttled(key):
        return _reply(429, {"error": f"muitas tentativas; espere {LOGIN_WINDOW_MIN} minutos"},
                      {"Retry-After": str(LOGIN_WINDOW_MIN * 60)})
    if not verify_password(str(p.get("password") or ""), u["pw_hash"]):
        ops.acc.record_fail(key)
        ops._audit("reauth", u, None, result="refused", error="senha incorreta")
        return _reply(403, {"error": "senha incorreta", "code": "reauth_failed"})
    ops.acc.mark_reauth(token)
    ops._audit("reauth", u, None, after={"minutes": reauth_minutes()})
    until = datetime.now(timezone.utc) + timedelta(minutes=reauth_minutes())
    return _reply(200, {"ok": True, "until": until.isoformat(timespec="seconds")})


def _post(app, path: str, headers: dict, p: dict, ops: AdminOps):
    reason = str(p.get("reason") or "")
    if path == "/api/admin/invites":
        days = p.get("days", 7)
        if isinstance(days, bool) or not isinstance(days, (int, float)):
            raise AdminError("validade do convite: de 1 a 30 dias")
        inv = ops.create_invite(days=int(days), email=str(p.get("email") or "") or None, note=str(p.get("note") or ""))
        return _reply(200, {"ok": True, **inv, "notice": "Copie o código agora: ele não aparece de novo."})
    m = INVITE_RE.fullmatch(path)
    if m:
        return _reply(200, {"ok": True, **ops.revoke_invite(m.group(1), reason=reason)})
    m = ACCOUNT_RE.fullmatch(path)
    if not m or m.group(2) not in ACCOUNT_ACTIONS:
        return not_found()
    uid, action = m.group(1), m.group(2)
    user, _ws = ops.target(uid)   # 404 se a conta não existe
    self_action = user["id"] == ops.actor.user_id
    if action == "allow-real":
        out = ops.allow_real(uid, reason)
    elif action == "deny-real":
        out = ops.deny_real(uid, reason)
    elif action == "set-mode":
        out = ops.set_mode(uid, str(p.get("mode") or ""), reason)
    elif action == "set-cap":
        out = ops.set_cap(uid, p.get("usd"), reason)
    elif action in ("grant", "adjust"):
        kw = {"idempotency_key": p.get("idempotency_key")}
        if action == "adjust":
            kw["confirm_email"] = str(p.get("confirm_email") or "")
        out = (ops.grant if action == "grant" else ops.adjust)(uid, p.get("credits"), reason, **kw)
    elif action == "verify-email":
        out = ops.verify_email(uid, reason)
    elif action == "reset-link":
        base = app.base_url() if app.public_host else app._origin(headers)
        out = {**ops.reset_link(uid, base, reason), "notice": "Copie o link agora: ele não aparece de novo."}
    else:   # export
        data = ops.export_user(uid, reason)
        name = f"kiroo-conta-{uid}-{time.strftime('%Y%m%d')}.json"
        return _reply(200, data, {"Content-Disposition": f'attachment; filename="{name}"'})
    return _reply(200, {"ok": True, "self_action": self_action, **out, "limits": ops.limits()})
