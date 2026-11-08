"""Cloudflare Turnstile: confere no servidor o token que o widget gerou no navegador.

Liga só com as DUAS variáveis (STUDIO_TURNSTILE_SITE_KEY pública, STUDIO_TURNSTILE_SECRET_KEY segredo). Meia configuração
em staging/produção falha fechada (as rotas protegidas recusam); em dev apenas desliga e avisa. O token e o segredo nunca
são registrados nem devolvidos.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .runtime import environment_name

log = logging.getLogger("studio.turnstile")

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_S = 5
MAX_TOKEN = 2048          # limite documentado pela Cloudflare para o token
MAX_RESPONSE = 64 * 1024

OK, INVALID, UNAVAILABLE = "ok", "invalid", "unavailable"
# Códigos do siteverify que indicam token ruim (o usuário tenta de novo); o resto é problema nosso ou da Cloudflare.
_TOKEN_ERRORS = {"missing-input-response", "invalid-input-response", "timeout-or-duplicate", "bad-request"}


def keys(env=None) -> tuple[str, str]:
    e = os.environ if env is None else env
    return (e.get("STUDIO_TURNSTILE_SITE_KEY") or "").strip(), (e.get("STUDIO_TURNSTILE_SECRET_KEY") or "").strip()


def config_problem(env=None) -> str | None:
    """Só uma das duas chaves definida → texto do aviso (sem valores); senão None."""
    site, secret = keys(env)
    if bool(site) != bool(secret):
        missing = "STUDIO_TURNSTILE_SECRET_KEY" if site else "STUDIO_TURNSTILE_SITE_KEY"
        return f"Turnstile mal configurado: falta {missing}."
    return None


def _protected(e) -> bool:
    """staging/production; STUDIO_ENV inválido conta como protegido (fecha, não abre)."""
    try:
        return environment_name(e) in ("staging", "production")
    except ValueError:
        return True


def fail_closed(env=None) -> bool:
    """Meia configuração em staging/produção: as rotas protegidas recusam em vez de liberar sem captcha."""
    e = os.environ if env is None else env
    return _protected(e) and config_problem(e) is not None


def startup_warning(env=None) -> tuple[str, str] | None:
    """(nível, texto) para o log de subida, ou None quando está tudo certo."""
    e = os.environ if env is None else env
    problem = config_problem(e)
    if problem and _protected(e):
        return "critical", (f"{problem} Cadastro, login, 'esqueci a senha' e reenvio de código ficam RECUSANDO tudo "
                            "até corrigir (docs/TURNSTILE.md).")
    if problem:
        return "warning", f"{problem} Verificação desligada (dev)."
    if not keys(e)[0] and _protected(e):
        return "warning", ("Turnstile desligado: defina STUDIO_TURNSTILE_SITE_KEY e STUDIO_TURNSTILE_SECRET_KEY para proteger "
                           "cadastro e login contra robôs (docs/TURNSTILE.md).")
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # 3xx vira HTTPError: nunca seguimos redirecionamento
        return None


def _post(url: str, form: dict) -> dict:
    req = urllib.request.Request(url, data=urlencode(form).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.build_opener(_NoRedirect).open(req, timeout=TIMEOUT_S) as r:   # noqa: S310 (URL fixa; só os testes trocam)
        if r.status != 200:
            raise urllib.error.HTTPError(url, r.status, "status", r.headers, None)
        data = json.loads(r.read(MAX_RESPONSE).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("resposta inesperada")
    return data


def verify(secret: str, token, ip: str = "", *, url: str = SITEVERIFY_URL, post=_post) -> str:
    """OK | INVALID | UNAVAILABLE. Token ausente ou fora do formato nem chega à Cloudflare."""
    if not isinstance(token, str) or not token.strip() or len(token) > MAX_TOKEN:
        return INVALID
    form = {"secret": secret, "response": token.strip()}
    if ip and ip != "local":
        form["remoteip"] = ip
    try:
        data = post(url, form)
    except Exception as exc:  # noqa: BLE001 (timeout, DNS, TLS, 3xx/5xx, JSON ruim): falha fechada
        log.warning("Turnstile: siteverify indisponível (%s)", type(exc).__name__)
        return UNAVAILABLE
    if data.get("success") is True:
        return OK
    raw = data.get("error-codes")
    codes = [c for c in raw if isinstance(c, str)] if isinstance(raw, list) else []
    if codes and not set(codes) <= _TOKEN_ERRORS:
        log.error("Turnstile: a Cloudflare recusou a configuração (%s)", ", ".join(c[:40] for c in codes[:5]))
        return UNAVAILABLE
    return INVALID
