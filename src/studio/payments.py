"""Compra de planos e créditos: camada do provedor de pagamento (hoje a Stripe) e o "Adicionar créditos" manual.

`PAYMENTS_ENABLED` é o kill switch (padrão desligado): desligado, a tela de Planos só mostra os valores, a compra pelo
site some e o administrador libera créditos (`studio admin grant-credits`). Ligado, o provedor (`provider()`) faz:

  * `checkout_plan` / `checkout_topup`: o servidor escolhe o preço (id da Stripe em variável de ambiente) e valida a
    quantidade do avulso; o navegador só manda o código do plano ou a quantidade. Devolve a página de pagamento.
  * `portal`: Portal do cliente (trocar plano, cancelar, trocar cartão, recibos).
  * `receive_webhook`: confere a assinatura, grava o evento uma vez só e concede/estorna créditos no livro por origem.
  * `sync_order`: na volta do checkout, confere na API (rede de segurança se o webhook atrasar).

O provedor concreto mora em `payments_stripe.py`. Este módulo guarda o que não depende dele: leitura das compras, CPF/
CNPJ da nota fiscal (Minha conta), métricas e o texto do "Adicionar créditos".
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import quote

from . import catalog, stripe_client
from .credits import Ledger, fmt, fmt_balance
from .db import Database, now

log = logging.getLogger("studio.payments")

MANUAL = "manual"
STRIPE = "stripe"
BRT = timezone(timedelta(hours=-3), "BRT")   # Brasília sem horário de verão desde 2019 (sem depender de tzdata)
OPEN = ("creating", "pending", "processing")
POLL_SYNC_S = 10           # o polling da tela consulta a Stripe no máximo a cada 10 s por compra
KINDS = {"plan": "Assinatura", "topup": "Avulso", "invoice": "Ciclo do plano"}


class PaymentRefused(ValueError):
    """Pedido recusado com mensagem para o cliente (quantidade fora do limite, plano indisponível...)."""

    def __init__(self, message: str, code: str = "refused"):
        super().__init__(message)
        self.code = code


class PaymentsDisabled(Exception):
    pass


ProviderError = stripe_client.StripeError


class PaymentProvider(Protocol):
    """O que o servidor precisa de um provedor de pagamento."""

    name: str

    def checkout_plan(self, db: Database, *, wid: str, user_id: str | None, email: str, name: str, plan_code: str,
                      interval: str, base_url: str) -> dict: ...

    def checkout_topup(self, db: Database, *, wid: str, user_id: str | None, email: str, name: str, credits,
                       base_url: str) -> dict: ...

    def portal(self, db: Database, *, wid: str, base_url: str, plan_code: str | None = None) -> dict: ...

    def receive_webhook(self, db: Database, body: bytes, headers: dict) -> tuple[int, dict]: ...

    def sync_order(self, db: Database, row) -> None: ...


# =================================================================== configuração
def config_error(env=None) -> str | None:
    return stripe_client.config_error(env)


def enabled() -> bool:
    return stripe_client.config().enabled and config_error() is None


def provider_name() -> str:
    return STRIPE if enabled() else MANUAL


def make_client():
    """Ponto único de criação do cliente da Stripe (os testes trocam por um falso)."""
    return stripe_client.StripeClient(stripe_client.config())


def provider() -> PaymentProvider:
    from .payments_stripe import StripeProvider
    return StripeProvider(make_client())


# =================================================================== CPF / CNPJ (Minha conta, nota fiscal)
def _cpf_ok(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _cnpj_ok(d: str) -> bool:
    """CNPJ numérico ou alfanumérico (a partir de 07/2026): 12 posições 0-9/A-Z + 2 dígitos verificadores numéricos.
    Valor de cada caractere = código ASCII − 48 (para dígitos é o próprio dígito)."""
    if len(d) != 14 or not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", d) or d == d[0] * 14:
        return False
    vals = [ord(c) - 48 for c in d]
    for n in (12, 13):
        weights = [*range(n - 7, 1, -1), *range(9, 1, -1)]
        r = sum(v * w for v, w in zip(vals[:n], weights)) % 11
        if (0 if r < 2 else 11 - r) != vals[n]:
            return False
    return True


def normalize_document(raw) -> str:
    """Só dígitos (e letras do CNPJ alfanumérico). Recusa CPF/CNPJ com dígito verificador errado."""
    d = re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()
    if (len(d) == 11 and d.isdigit() and _cpf_ok(d)) or (len(d) == 14 and _cnpj_ok(d)):
        return d
    raise PaymentRefused("CPF ou CNPJ inválido: confira os números.", "invalid_document")


# =================================================================== leitura
def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def get(db: Database, payment_id: str):
    return db.conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()


def view(row) -> dict:
    """O que a tela vê de uma compra (sem cliente, IP ou agente)."""
    return {"id": row["id"], "kind": row["kind"] or "topup", "package_code": row["package_code"], "credits": row["credits"],
            "amount_cents": row["amount_cents"], "amount": catalog.brl(row["amount_cents"]), "status": row["status"],
            "created_at": row["created_at"], "paid_at": row["paid_at"]}


def poll(db: Database, prov: PaymentProvider | None, row) -> dict:
    """Status para a tela na volta do checkout. Pendente: confere no provedor no máximo a cada POLL_SYNC_S (rede de
    segurança se o webhook atrasar); a decisão é sempre a da API, nunca do navegador."""
    if row["status"] in OPEN and prov is not None:
        last = row["synced_at"] or row["created_at"]
        if _ts(last) < datetime.now(timezone.utc) - timedelta(seconds=POLL_SYNC_S):
            try:
                prov.sync_order(db, row)
            except ProviderError as exc:
                log.warning("consulta à Stripe falhou no polling", extra={"event": "payment_poll_error", "detail": str(exc)})
            db.conn.execute("UPDATE payments SET synced_at=? WHERE id=?", (now(), row["id"]))
            row = get(db, row["id"])
    out = view(row)
    if row["status"] == "paid":
        out["balance"] = fmt_balance(Ledger(db).balance(row["account_id"]))
    return out


def negative_balance_block(db: Database, wid: str) -> str | None:
    """Mensagem de bloqueio quando o saldo ficou negativo (lançamentos antigos; o estorno da Stripe só tira o que não
    foi usado e não deixa o saldo negativo)."""
    led = Ledger(db)
    if led.exempt(wid):
        return None
    bal = led.balance(wid)
    if bal >= 0:
        return None
    return (f"Seu saldo está negativo ({fmt_balance(bal)} créditos). Novas produções ficam bloqueadas até regularizar: "
            "compre créditos para cobrir o saldo (o que você já produziu continua disponível).")


def topup_view() -> dict:
    """Limites do avulso para o "comprar em um clique" (o servidor valida de novo)."""
    try:
        lo, hi = catalog.topup_limits()
        unit = int(catalog.load()["topup"]["unit_price_cents"])
    except catalog.CatalogError:
        return {}
    return {"min_credits": lo, "max_credits": hi, "unit_price_cents": unit}


# =================================================================== admin
def list_payments(db: Database, email: str | None = None, limit: int = 50) -> list[dict]:
    q = ("SELECT p.*, u.email FROM payments p LEFT JOIN users u ON u.id=p.user_id "
         + ("WHERE u.email=? " if email else "") + "ORDER BY p.created_at DESC LIMIT ?")
    args = ((email.strip().lower(), limit) if email else (limit,))
    return [dict(r) for r in db.conn.execute(q, args).fetchall()]


def month_metrics(db: Database, at: datetime | None = None) -> dict:
    """Receita BRUTA do mês (horário de Brasília) por tipo (ciclos de plano e avulso) e créditos vendidos × consumidos.
    A linha da sessão de assinatura (`plan`) não entra: quem conta é a fatura paga (`invoice`)."""
    at = (at or datetime.now(timezone.utc)).astimezone(BRT)
    start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat(timespec="seconds")
    try:
        paid = db.conn.execute("SELECT COALESCE(kind,'topup') kind, COUNT(*) n, COALESCE(SUM(amount_cents),0) cents,"
                               " COALESCE(SUM(credits),0) cr FROM payments WHERE paid_at>=? AND COALESCE(kind,'topup')<>'plan'"
                               " GROUP BY COALESCE(kind,'topup')", (start,)).fetchall()
    except Exception:  # noqa: BLE001 — banco sem a tabela (antes da migração 10)
        paid = []
    consumed = db.conn.execute("SELECT COALESCE(-SUM(amount_cc),0) FROM credit_entries WHERE kind='debit' AND created_at>=?",
                               (start,)).fetchone()[0]
    by = {r["kind"]: {"purchases": r["n"], "revenue_cents": r["cents"]} for r in paid}
    for k in ("invoice", "topup"):
        by.setdefault(k, {"purchases": 0, "revenue_cents": 0})
    return {"month": at.strftime("%Y-%m"), "since": start, "gross_revenue_cents": sum(r["cents"] for r in paid),
            "by_kind": by, "credits_sold": sum(r["cr"] for r in paid), "credits_consumed": round(consumed / 100, 2)}


# =================================================================== "Adicionar créditos"
def _contact(subject: str) -> dict | None:
    """STUDIO_SUPPORT_CONTACT: e-mail, endereço https:// (formulário, WhatsApp) ou texto livre. Vazio → sem contato."""
    import os
    raw = (os.environ.get("STUDIO_SUPPORT_CONTACT") or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("https://"):
        return {"label": "Falar com a equipe do Kiroo", "href": raw}
    if "@" in raw and " " not in raw:
        return {"label": raw, "href": f"mailto:{raw}?subject={quote(subject)}"}
    return {"label": raw, "href": None}


def topup_options(missing_cc: int | None = None) -> dict:
    """O que a interface mostra em "Adicionar créditos". `online` = compra pelo site (Stripe) ligada."""
    missing = max(int(missing_cc or 0), 0)
    if enabled():
        return {"provider": STRIPE, "online": True, "title": "Comprar créditos",
                "message": "Assine um plano ou compre créditos avulsos por Pix ou cartão; o saldo atualiza assim que o "
                           "pagamento é confirmado.",
                "steps": [], "contact": _contact("Comprar créditos no Kiroo"), "missing_cc": missing, "topup": topup_view()}
    subject = "Adicionar créditos no Kiroo"
    steps = ["Fale com a equipe do Kiroo e diga quantos créditos você precisa.",
             "A equipe libera os créditos na sua conta; o saldo atualiza aqui em seguida.",
             "Nada do que você já fez se perde enquanto isso."]
    if missing:
        steps[0] = f"Fale com a equipe do Kiroo e peça pelo menos {fmt(missing)} créditos (o que falta para este ajuste)."
    return {"provider": MANUAL, "online": False, "title": "Adicionar créditos",
            "message": "O pagamento pelo site ainda não está disponível. Por enquanto, os créditos são liberados pela equipe do Kiroo.",
            "steps": steps, "contact": _contact(subject), "missing_cc": missing}
