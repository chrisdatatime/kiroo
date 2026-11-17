"""Cliente REST fino da Stripe, configuração e verificação de assinatura do webhook. Só o necessário para vender
planos (Checkout `subscription`), créditos avulsos (Checkout `payment`) e abrir o Portal do cliente.

Sem SDK: httpx com corpo `application/x-www-form-urlencoded` (a API da Stripe usa colchetes para objetos e listas) e o
cabeçalho `Stripe-Version` fixo (`STRIPE_API_VERSION`, padrão abaixo), para o formato das respostas não mudar quando a
conta trocar de versão. Nenhum dado de cartão passa por aqui: o pagamento é na página da Stripe.

Assinatura do webhook (cabeçalho `Stripe-Signature: t=<unix>,v1=<hex>[,v1=...]`): HMAC-SHA256 do texto
`"<t>.<corpo cru>"` com o segredo `whsec_...`, comparado em tempo constante; recusa evento com mais de 5 minutos.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from .logs import redact

API_BASE = "https://api.stripe.com"
DEFAULT_API_VERSION = "2025-02-24.acacia"
SIGNATURE_HEADER = "Stripe-Signature"     # chaves de cabeçalho chegam em Title-Case no servidor
TOLERANCE_S = 300
SECRET_PREFIX = {"test": ("sk_test_", "rk_test_"), "live": ("sk_live_", "rk_live_")}
PUBLISHABLE_PREFIX = {"test": "pk_test_", "live": "pk_live_"}


class StripeError(Exception):
    """Falha ao falar com a Stripe. `status` = HTTP (0 = rede/tempo). A mensagem nunca leva a chave."""

    def __init__(self, message: str, status: int = 0, code: str | None = None):
        super().__init__(redact(message)[:400])
        self.status = status
        self.code = code


@dataclass(frozen=True)
class StripeConfig:
    enabled: bool
    secret_key: str
    webhook_secret: str
    publishable_key: str
    api_version: str

    @property
    def mode(self) -> str:
        return "live" if self.secret_key.startswith(SECRET_PREFIX["live"]) else "test"

    @property
    def live(self) -> bool:
        return self.mode == "live"


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "sim", "yes", "on"}


def config(env=None) -> StripeConfig:
    e = os.environ if env is None else env
    return StripeConfig(enabled=_bool(e.get("PAYMENTS_ENABLED")),
                        secret_key=(e.get("STRIPE_SECRET_KEY") or "").strip(),
                        webhook_secret=(e.get("STRIPE_WEBHOOK_SECRET") or "").strip(),
                        publishable_key=(e.get("STRIPE_PUBLISHABLE_KEY") or "").strip(),
                        api_version=(e.get("STRIPE_API_VERSION") or DEFAULT_API_VERSION).strip())


def config_error(env=None) -> str | None:
    """Motivo para NÃO subir o servidor (None = ok). Com PAYMENTS_ENABLED desligado nada é exigido.
    Recusa: chave/segredo ausentes ou fora do formato, chave de teste em STUDIO_ENV=production (compra de teste
    creditaria de verdade) e chave live fora de produção (cobraria de verdade num ambiente de teste), preço da Stripe
    faltando e limites do avulso inválidos."""
    e = os.environ if env is None else env
    c = config(e)
    if not c.enabled:
        return None
    if not c.secret_key:
        return "PAYMENTS_ENABLED=true exige STRIPE_SECRET_KEY"
    if not c.secret_key.startswith(SECRET_PREFIX["test"] + SECRET_PREFIX["live"]):
        return "STRIPE_SECRET_KEY não tem o formato de chave secreta da Stripe (sk_test_/sk_live_ ou rk_test_/rk_live_)"
    if not c.webhook_secret:
        return "PAYMENTS_ENABLED=true exige STRIPE_WEBHOOK_SECRET"
    if not c.webhook_secret.startswith("whsec_"):
        return "STRIPE_WEBHOOK_SECRET precisa começar com whsec_"
    if c.publishable_key and not c.publishable_key.startswith(PUBLISHABLE_PREFIX[c.mode]):
        return f"STRIPE_PUBLISHABLE_KEY não é do mesmo modo ({c.mode}) da STRIPE_SECRET_KEY"
    studio_env = (e.get("STUDIO_ENV") or "dev").strip().lower()
    if c.live and studio_env != "production":
        return f"chave live da Stripe só com STUDIO_ENV=production (agora: {studio_env})"
    if not c.live and studio_env == "production":
        return "chave de teste da Stripe com STUDIO_ENV=production: compras de teste creditariam de verdade; recusado"
    from . import catalog
    try:
        envs = catalog.price_envs()
        lo, hi = _topup_limits(e)
    except (catalog.CatalogError, ValueError) as exc:
        return f"catálogo de planos inválido: {exc}"
    for name in envs:
        v = (e.get(name) or "").strip()
        if not v:
            return f"PAYMENTS_ENABLED=true exige {name} (id do preço na Stripe)"
        if not v.startswith("price_"):
            return f"{name} precisa ser um id de preço da Stripe (price_...)"
    if not (0 < lo <= hi):
        return "TOPUP_MIN_CREDITS e TOPUP_MAX_CREDITS precisam ser positivos, com mínimo <= máximo"
    return None


def _topup_limits(e) -> tuple[int, int]:
    from . import catalog
    t = catalog.load()["topup"]
    lo = int((e.get("TOPUP_MIN_CREDITS") or "").strip() or t["min_credits"])
    hi = int((e.get("TOPUP_MAX_CREDITS") or "").strip() or t["max_credits"])
    return lo, hi


# ------------------------------------------------------------------ assinatura do webhook
def sign(payload: bytes, secret: str, t: int | None = None) -> str:
    """Cabeçalho `Stripe-Signature` para um corpo (testes e roteiros locais)."""
    t = int(time.time()) if t is None else int(t)
    mac = hmac.new(secret.encode("utf-8"), f"{t}.".encode("utf-8") + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify_signature(payload: bytes, header: str | None, secret: str, *, tolerance: int = TOLERANCE_S,
                     now: float | None = None) -> bool:
    if not header or not secret:
        return False
    t, sigs = None, []
    for part in header.split(","):
        k, _, v = part.strip().partition("=")
        if k == "t":
            try:
                t = int(v)
            except ValueError:
                return False
        elif k == "v1" and v:
            sigs.append(v)
    if t is None or not sigs:
        return False
    if abs((time.time() if now is None else now) - t) > tolerance:
        return False
    expected = hmac.new(secret.encode("utf-8"), f"{t}.".encode("utf-8") + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


# ------------------------------------------------------------------ corpo no formato da Stripe
def encode(params: dict | None) -> list[tuple[str, str]]:
    """{"line_items": [{"price": "p", "quantity": 2}]} -> [("line_items[0][price]", "p"), ("line_items[0][quantity]", "2")]."""
    out: list[tuple[str, str]] = []

    def walk(prefix: str, v) -> None:
        if v is None:
            return
        if isinstance(v, dict):
            for k, x in v.items():
                walk(f"{prefix}[{k}]" if prefix else str(k), x)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                walk(f"{prefix}[{i}]", x)
        elif isinstance(v, bool):
            out.append((prefix, "true" if v else "false"))
        else:
            out.append((prefix, str(v)))

    walk("", params or {})
    return out


def _httpx():
    import httpx
    return httpx


class StripeClient:
    """Transporte HTTP. `transport` permite testar com httpx.MockTransport (nenhuma rede real em teste)."""

    def __init__(self, cfg: StripeConfig, *, transport=None, timeout_s: float = 20.0):
        self.cfg = cfg
        self._transport, self._timeout, self._c = transport, timeout_s, None

    @property
    def http(self):
        if self._c is None:
            self._c = _httpx().Client(base_url=API_BASE, transport=self._transport, timeout=self._timeout,
                                      follow_redirects=False, auth=(self.cfg.secret_key, ""),
                                      headers={"Stripe-Version": self.cfg.api_version, "User-Agent": "kiroo-studio"})
        return self._c

    def _req(self, method: str, path: str, params: dict | None = None, *, idempotency_key: str | None = None) -> dict:
        httpx = _httpx()
        from urllib.parse import urlencode
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        try:
            if method == "GET":
                r = self.http.get(path, params=encode(params), headers=headers)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                r = self.http.post(path, content=urlencode(encode(params)).encode("ascii"), headers=headers)
        except httpx.HTTPError as exc:
            raise StripeError(f"Stripe indisponível: {type(exc).__name__}") from None
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            err = body.get("error") if isinstance(body, dict) else None
            err = err if isinstance(err, dict) else {}
            raise StripeError(f"Stripe recusou ({r.status_code}): {err.get('message') or 'erro'}", r.status_code,
                              err.get("code"))
        return body if isinstance(body, dict) else {}

    # --- clientes, checkout, portal
    def create_customer(self, *, email: str | None, name: str | None, metadata: dict, idempotency_key: str) -> dict:
        return self._req("POST", "/v1/customers", {"email": email, "name": name, "metadata": metadata},
                         idempotency_key=idempotency_key)

    def create_checkout_session(self, params: dict, *, idempotency_key: str) -> dict:
        return self._req("POST", "/v1/checkout/sessions", params, idempotency_key=idempotency_key)

    def get_checkout_session(self, session_id: str) -> dict:
        return self._req("GET", f"/v1/checkout/sessions/{session_id}")

    def create_portal_session(self, *, customer: str, return_url: str, flow_data: dict | None = None) -> dict:
        return self._req("POST", "/v1/billing_portal/sessions",
                         {"customer": customer, "return_url": return_url, "flow_data": flow_data, "locale": "pt-BR"})

    # --- leitura (a fonte da verdade é a API, na versão fixada)
    def get_subscription(self, sub_id: str) -> dict:
        return self._req("GET", f"/v1/subscriptions/{sub_id}")

    def get_invoice(self, invoice_id: str) -> dict:
        return self._req("GET", f"/v1/invoices/{invoice_id}", {"expand": ["lines.data.price.product"]})

    def get_product(self, product_id: str) -> dict:
        return self._req("GET", f"/v1/products/{product_id}")

    def get_event(self, event_id: str) -> dict:
        return self._req("GET", f"/v1/events/{event_id}")
