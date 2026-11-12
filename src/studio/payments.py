"""Ponto de integração para ADICIONAR CRÉDITOS (hoje manual; pronto para o Mercado Pago).

Hoje não há pagamento: "Adicionar créditos" leva a um contato/instrução manual, e o administrador libera os créditos
(`studio admin grant-credits`). Para ligar o Mercado Pago depois, basta:
  1. implementar `MercadoPagoProvider.start_checkout` (criar a preferência/pagamento e devolver a URL);
  2. receber o webhook e creditar com `Ledger.add(wid, cc, kind="purchase", ext_ref=f"mp:{payment_id}")` — o `ext_ref`
     único já torna o lançamento idempotente (webhook repetido não credita duas vezes);
  3. escolher o provedor com STUDIO_PAYMENTS_PROVIDER=mercadopago.
A interface (`/api/credits/topup`, Credits.jsx, aviso de saldo insuficiente) não muda: ela só lê o que `topup_options` devolve.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

MANUAL = "manual"
MERCADOPAGO = "mercadopago"


class CheckoutUnavailable(Exception):
    """O provedor de pagamento escolhido ainda não está implementado/configurado."""


@dataclass(frozen=True)
class Checkout:
    url: str            # para onde levar o cliente
    reference: str      # id do pedido no provedor (vira ext_ref do crédito quando o pagamento for confirmado)


class MercadoPagoProvider:
    """Ponto de integração (ainda sem pagamento). Não faz chamada de rede."""

    name = MERCADOPAGO

    def start_checkout(self, workspace_id: str, credits_cc: int) -> Checkout:
        raise CheckoutUnavailable("pagamento pelo Mercado Pago ainda não está disponível")


def provider_name() -> str:
    raw = (os.environ.get("STUDIO_PAYMENTS_PROVIDER") or MANUAL).strip().lower()
    return raw if raw in (MANUAL, MERCADOPAGO) else MANUAL


def _contact(subject: str) -> dict | None:
    """STUDIO_SUPPORT_CONTACT: e-mail, endereço https:// (formulário, WhatsApp) ou texto livre. Vazio → sem contato."""
    raw = (os.environ.get("STUDIO_SUPPORT_CONTACT") or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("https://"):
        return {"label": "Falar com a equipe do Kiroo", "href": raw}
    if "@" in raw and " " not in raw:
        return {"label": raw, "href": f"mailto:{raw}?subject={quote(subject)}"}
    return {"label": raw, "href": None}


def topup_options(missing_cc: int | None = None) -> dict:
    """O que a interface mostra em "Adicionar créditos". `online` = há checkout (Mercado Pago) pronto; hoje sempre falso."""
    missing = max(int(missing_cc or 0), 0)
    subject = "Adicionar créditos no Kiroo"
    steps = ["Fale com a equipe do Kiroo e diga quantos créditos você precisa.",
             "A equipe libera os créditos na sua conta; o saldo atualiza aqui em seguida.",
             "Nada do que você já fez se perde enquanto isso."]
    if missing:
        from .credits import fmt
        steps[0] = f"Fale com a equipe do Kiroo e peça pelo menos {fmt(missing)} créditos (o que falta para este ajuste)."
    return {"provider": provider_name(), "online": False, "title": "Adicionar créditos",
            "message": "O pagamento pelo site ainda não está disponível. Por enquanto, os créditos são liberados pela equipe do Kiroo.",
            "steps": steps, "contact": _contact(subject), "missing_cc": missing}
