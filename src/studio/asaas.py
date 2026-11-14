"""Cliente REST fino do Asaas (API v3) e configuração. Só o necessário para vender créditos.

Confirmado na documentação oficial (docs.asaas.com, lida em 14/11/2026):
  * Base: sandbox `https://api-sandbox.asaas.com/v3`; produção `https://api.asaas.com/v3`.
  * Autenticação: cabeçalho `access_token` com a chave. Chave de produção começa com `$aact_prod_`; de sandbox, com
    `$aact_hmlg_`. Contas novas exigem `User-Agent`.
  * Webhook: o token cadastrado no painel chega no cabeçalho `asaas-access-token` (32 a 255 caracteres, sem espaço,
    não pode ser uma chave de API).
  * A API aceita clientes duplicados: procuramos pelo `externalReference` (= id do workspace) antes de criar.

Nenhum dado de cartão passa por aqui: o cartão é pago na fatura hospedada do Asaas (`invoiceUrl`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .logs import redact


def _scrub_doc(text: str) -> str:
    """CPF/CNPJ nunca vai para mensagem de erro nem log: qualquer sequência de 11 a 14 dígitos (com ou sem pontuação) vira ***."""
    import re
    return re.sub(r"\d[\d.\-/]{9,17}\d", "***", text)


BASE_URLS = {"sandbox": "https://api-sandbox.asaas.com/v3", "production": "https://api.asaas.com/v3"}
KEY_PREFIX = {"sandbox": "$aact_hmlg_", "production": "$aact_prod_"}
USER_AGENT = "kiroo-studio"
WEBHOOK_HEADER = "Asaas-Access-Token"   # chaves de cabeçalho chegam em Title-Case no servidor


class AsaasError(Exception):
    """Falha ao falar com o Asaas. `status` = HTTP (0 = rede/tempo). A mensagem nunca leva a chave."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(redact(message)[:400])
        self.status = status


@dataclass(frozen=True)
class AsaasConfig:
    enabled: bool
    env: str
    api_key: str
    webhook_token: str

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.env]


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "sim", "yes", "on"}


def config(env=None) -> AsaasConfig:
    e = os.environ if env is None else env
    return AsaasConfig(enabled=_bool(e.get("PAYMENTS_ENABLED")),
                       env=(e.get("ASAAS_ENV") or "sandbox").strip().lower(),
                       api_key=(e.get("ASAAS_API_KEY") or "").strip(),
                       webhook_token=(e.get("ASAAS_WEBHOOK_TOKEN") or "").strip())


def config_error(env=None) -> str | None:
    """Motivo para NÃO subir o servidor (None = ok). Com PAYMENTS_ENABLED desligado nada é exigido.
    Recusa: ambiente desconhecido, chave/token ausentes, chave de sandbox em ASAAS_ENV=production e vice-versa,
    token fora do formato do Asaas, e combinações perigosas com STUDIO_ENV (sandbox em produção credita de graça;
    Asaas de produção fora de STUDIO_ENV=production cobra de verdade num ambiente de teste)."""
    e = os.environ if env is None else env
    c = config(e)
    if not c.enabled:
        return None
    if c.env not in BASE_URLS:
        return f"ASAAS_ENV inválido ({c.env!r}): use sandbox ou production"
    if not c.api_key:
        return "PAYMENTS_ENABLED=true exige ASAAS_API_KEY"
    if not c.webhook_token:
        return "PAYMENTS_ENABLED=true exige ASAAS_WEBHOOK_TOKEN"
    other = "production" if c.env == "sandbox" else "sandbox"
    if c.api_key.startswith(KEY_PREFIX[other]):
        return f"ASAAS_API_KEY parece ser de {other}, mas ASAAS_ENV={c.env}: recusado"
    if not c.api_key.startswith(KEY_PREFIX[c.env]):
        return f"ASAAS_API_KEY não tem o formato de chave de {c.env} ({KEY_PREFIX[c.env]}...): recusado"
    if not (32 <= len(c.webhook_token) <= 255) or any(ch.isspace() for ch in c.webhook_token):
        return "ASAAS_WEBHOOK_TOKEN precisa ter de 32 a 255 caracteres, sem espaços"
    if c.webhook_token.startswith("$aact_"):
        return "ASAAS_WEBHOOK_TOKEN não pode ser uma chave de API"
    studio_env = (e.get("STUDIO_ENV") or "dev").strip().lower()
    if c.env == "production" and studio_env != "production":
        return f"ASAAS_ENV=production só com STUDIO_ENV=production (agora: {studio_env})"
    if c.env == "sandbox" and studio_env == "production":
        return "ASAAS_ENV=sandbox com STUDIO_ENV=production: compras de teste creditariam de verdade; recusado"
    return None


def _httpx():
    import httpx
    return httpx


class AsaasClient:
    """Transporte HTTP. `transport` permite testar com httpx.MockTransport (nenhuma rede real em teste)."""

    def __init__(self, cfg: AsaasConfig, *, transport=None, timeout_s: float = 15.0):
        self.cfg = cfg
        self._transport, self._timeout, self._c = transport, timeout_s, None

    @property
    def http(self):
        if self._c is None:
            self._c = _httpx().Client(base_url=self.cfg.base_url, transport=self._transport, timeout=self._timeout,
                                      follow_redirects=False,
                                      headers={"access_token": self.cfg.api_key, "User-Agent": USER_AGENT,
                                               "Content-Type": "application/json", "Accept": "application/json"})
        return self._c

    def _req(self, method: str, path: str, **kw) -> dict:
        httpx = _httpx()
        try:
            r = self.http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise AsaasError(f"Asaas indisponível ({type(exc).__name__})") from exc
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            errs = data.get("errors") if isinstance(data, dict) else None
            desc = "; ".join(str(x.get("description") or x.get("code")) for x in errs or [] if isinstance(x, dict))
            desc = _scrub_doc(desc)
            raise AsaasError(f"Asaas recusou ({r.status_code}): {desc or 'sem detalhe'}", r.status_code)
        return data if isinstance(data, dict) else {}

    # --------------------------------------------------------------- clientes
    def find_customer(self, external_reference: str) -> dict | None:
        d = self._req("GET", "/customers", params={"externalReference": external_reference, "limit": 1})
        rows = [c for c in d.get("data") or [] if not c.get("deleted")]
        return rows[0] if rows else None

    def create_customer(self, *, name: str, cpf_cnpj: str, email: str | None, external_reference: str) -> dict:
        body = {"name": name, "cpfCnpj": cpf_cnpj, "externalReference": external_reference,
                "notificationDisabled": True}
        if email:
            body["email"] = email
        return self._req("POST", "/customers", json=body)

    # --------------------------------------------------------------- cobranças
    def create_payment(self, *, customer: str, billing_type: str, value_cents: int, due_date: str, description: str,
                       external_reference: str, success_url: str | None = None) -> dict:
        body = {"customer": customer, "billingType": billing_type, "value": round(value_cents / 100, 2),
                "dueDate": due_date, "description": description[:500], "externalReference": external_reference}
        if success_url:
            body["callback"] = {"successUrl": success_url[:255], "autoRedirect": True}
        return self._req("POST", "/payments", json=body)

    def find_payment(self, external_reference: str) -> dict | None:
        """Cobrança pelo nosso id (externalReference): recupera a que foi criada sem a resposta chegar até nós."""
        d = self._req("GET", "/payments", params={"externalReference": external_reference, "limit": 1})
        rows = d.get("data") or []
        return rows[0] if rows else None

    def get_payment(self, asaas_id: str) -> dict:
        return self._req("GET", f"/payments/{asaas_id}")

    def pix_qr(self, asaas_id: str) -> dict:
        return self._req("GET", f"/payments/{asaas_id}/pixQrCode")
