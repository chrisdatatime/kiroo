"""Provedor Stripe: Checkout (planos mensais e avulso), Portal do cliente e webhook.

Regras de crédito (livro por origem, credits.py):
  * Plano: `invoice.paid` (motivo `subscription_create` ou `subscription_cycle`) concede os créditos do ciclo como lote
    `subscription` que vence no fim do período da fatura. O que sobrar do ciclo anterior vence (não acumula).
  * Upgrade (`customer.subscription.updated` para um plano com mais créditos, mesmo ciclo): concede só a diferença na
    hora, até o fim do ciclo. Downgrade: nada muda agora; a próxima fatura já vem com o plano menor.
  * Avulso: `checkout.session.completed` (pago) credita exatamente a quantidade que o SERVIDOR pediu ao criar a sessão,
    como lote `topup` sem validade. Pix pago depois: `checkout.session.async_payment_succeeded`.
  * Reembolso (`charge.refunded`, proporcional ao valor devolvido) e contestação (`charge.dispute.created`, tudo):
    tiram dos lotes daquela compra só o que ainda não foi usado e marcam a conta (`workspaces.billing_flag`).

Idempotência: cada evento uma vez só (`stripe_events.id`); cada fatura uma vez só (`payments.stripe_invoice_id` único
e `ext_ref` = `invoice:<id>` no livro); cada sessão uma vez só (`ext_ref` = `topup:<nosso id>`). Evento que falha no
meio fica sem `processed_at` e a Stripe reenvia (resposta 500).

Formato: as faturas são relidas na API com a versão fixada (`STRIPE_API_VERSION`), então o formato do payload do
webhook não importa para elas; para os demais objetos, os campos lidos existem nas versões antigas e novas.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone

from . import catalog, plans, stripe_client
from .credits import Ledger
from .db import Database, new_id, now
from .payments import OPEN, PaymentRefused, get, view
from .stripe_client import StripeError

log = logging.getLogger("studio.payments")

HANDLED = {"checkout.session.completed", "checkout.session.async_payment_succeeded",
           "checkout.session.async_payment_failed", "checkout.session.expired", "invoice.paid",
           "invoice.payment_failed", "customer.subscription.created", "customer.subscription.updated",
           "customer.subscription.deleted", "charge.refunded", "charge.dispute.created"}
GRANT_REASONS = {"subscription_create", "subscription_cycle"}
_PRODUCT_CACHE: dict[str, tuple[float, int | None]] = {}
PRODUCT_TTL_S = 600


def _iso(ts) -> str | None:
    if ts in (None, ""):
        return None
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat(timespec="seconds")


def _id(v) -> str | None:
    """Campo que pode vir como id (texto) ou como objeto expandido."""
    if isinstance(v, dict):
        return v.get("id")
    return v or None


def _credits_meta(obj) -> int | None:
    if not isinstance(obj, dict):
        return None
    raw = (obj.get("metadata") or {}).get("credits")
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _invoice_subscription(inv: dict) -> str | None:
    sub = _id(inv.get("subscription"))
    if sub:
        return sub
    parent = inv.get("parent") or {}
    return _id((parent.get("subscription_details") or {}).get("subscription"))


def _invoice_metadata(inv: dict) -> dict:
    meta = (inv.get("subscription_details") or {}).get("metadata")
    if not meta:
        meta = ((inv.get("parent") or {}).get("subscription_details") or {}).get("metadata")
    return meta or {}


def _line_price(line: dict) -> tuple[str | None, dict | None]:
    price = line.get("price")
    if price:
        return _id(price), price if isinstance(price, dict) else None
    pd = ((line.get("pricing") or {}).get("price_details") or {})
    return _id(pd.get("price")), None


def _sub_period_end(sub: dict) -> str | None:
    if sub.get("current_period_end"):
        return _iso(sub["current_period_end"])
    items = ((sub.get("items") or {}).get("data") or [])
    return _iso(items[0].get("current_period_end")) if items and items[0].get("current_period_end") else None


def _sub_item(sub: dict) -> dict:
    items = ((sub.get("items") or {}).get("data") or [])
    return items[0] if items else {}


class StripeProvider:
    name = "stripe"

    def __init__(self, client):
        self.c = client

    # =============================================================== cliente da Stripe por conta
    def customer(self, db: Database, wid: str, *, email: str | None, name: str | None) -> str:
        ws = db.conn.execute("SELECT stripe_customer_id FROM workspaces WHERE id=?", (wid,)).fetchone()
        if ws and ws["stripe_customer_id"]:
            return ws["stripe_customer_id"]
        cus = self.c.create_customer(email=email, name=name, metadata={"workspace_id": wid},
                                     idempotency_key=f"kiroo-customer-{wid}")
        db.conn.execute("UPDATE workspaces SET stripe_customer_id=? WHERE id=?", (cus["id"], wid))
        return cus["id"]

    def _order(self, db: Database, *, wid, user_id, kind, code, credits, amount_cents) -> str:
        pid = new_id("kpay")
        db.conn.execute("INSERT INTO payments(id, account_id, user_id, method, package_code, credits, amount_cents, status,"
                        " created_at, provider, kind) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (pid, wid, user_id, "stripe", code, credits, amount_cents, "creating", now(), "stripe", kind))
        return pid

    def _open_session(self, db: Database, pid: str, params: dict) -> dict:
        try:
            s = self.c.create_checkout_session(params, idempotency_key=f"kiroo-{pid}")
        except StripeError:
            db.conn.execute("UPDATE payments SET status='failed', note='erro ao criar a sessão de pagamento' WHERE id=?", (pid,))
            raise
        db.conn.execute("UPDATE payments SET stripe_session_id=?, status='pending', synced_at=? WHERE id=?",
                        (s["id"], now(), pid))
        log.info("checkout criado", extra={"event": "payment_created", "payment_id": pid})
        return {"payment": view(get(db, pid)), "redirect_url": s.get("url")}

    @staticmethod
    def _urls(base_url: str, pid: str) -> dict:
        base = base_url.rstrip("/")
        return {"success_url": f"{base}/pricing?compra={pid}", "cancel_url": f"{base}/pricing?cancelado=1"}

    def checkout_plan(self, db: Database, *, wid: str, user_id: str | None, email: str, name: str, plan_code: str,
                      interval: str = "month", base_url: str) -> dict:
        if interval not in catalog.INTERVALS or (interval == "year" and not catalog.annual_enabled()):
            raise PaymentRefused("Por enquanto os planos são só mensais.", "invalid_interval")
        try:
            p = catalog.plan(str(plan_code or ""))
        except catalog.CatalogError as exc:
            raise PaymentRefused("Plano inexistente.", "invalid_plan") from exc
        price = catalog.price_id(p["code"], interval)
        if not price:
            raise PaymentRefused("Este plano não está disponível agora.", "plan_unavailable")
        if plans.subscription(db, wid) is not None:
            raise PaymentRefused("Você já tem um plano. Para trocar, use “Mudar de plano”.", "has_subscription")
        cus = self.customer(db, wid, email=email, name=name)
        pid = self._order(db, wid=wid, user_id=user_id, kind="plan", code=p["code"], credits=p["credits"],
                          amount_cents=p["price_cents"])
        meta = {"workspace_id": wid, "order": pid, "kind": "plan", "plan": p["code"]}
        return self._open_session(db, pid, {
            "mode": "subscription", "customer": cus, "client_reference_id": wid, "locale": "pt-BR",
            "line_items": [{"price": price, "quantity": 1}], **self._urls(base_url, pid), "metadata": meta,
            "subscription_data": {"metadata": {"workspace_id": wid, "plan": p["code"]}}})

    def checkout_topup(self, db: Database, *, wid: str, user_id: str | None, email: str, name: str, credits,
                       base_url: str) -> dict:
        try:
            q = catalog.topup_quote(credits)
        except catalog.CatalogError as exc:
            raise PaymentRefused(str(exc), "invalid_quantity") from exc
        price = catalog.topup_price_id()
        if not price:
            raise PaymentRefused("A compra avulsa não está disponível agora.", "topup_unavailable")
        cus = self.customer(db, wid, email=email, name=name)
        pid = self._order(db, wid=wid, user_id=user_id, kind="topup", code="avulso", credits=q["credits"],
                          amount_cents=q["amount_cents"])
        meta = {"workspace_id": wid, "order": pid, "kind": "topup", "credits": str(q["credits"])}
        return self._open_session(db, pid, {
            "mode": "payment", "customer": cus, "client_reference_id": wid, "locale": "pt-BR",
            "line_items": [{"price": price, "quantity": q["quantity"]}], **self._urls(base_url, pid), "metadata": meta,
            "payment_intent_data": {"metadata": meta}})

    def portal(self, db: Database, *, wid: str, base_url: str, plan_code: str | None = None) -> dict:
        ws = db.conn.execute("SELECT stripe_customer_id FROM workspaces WHERE id=?", (wid,)).fetchone()
        cus = ws["stripe_customer_id"] if ws else None
        if not cus:
            raise PaymentRefused("Você ainda não tem compras na Stripe.", "no_customer")
        ret = base_url.rstrip("/") + "/pricing"
        flow = None
        sub = plans.subscription(db, wid)
        if plan_code and sub is not None and sub["item_id"] and plan_code != sub["plan"]:
            try:
                price = catalog.price_id(str(plan_code), sub["interval"] or "month")
            except catalog.CatalogError:
                price = None
            if price:   # "Mudar para X": abre o portal já na confirmação da troca
                flow = {"type": "subscription_update_confirm",
                        "subscription_update_confirm": {"subscription": sub["id"],
                                                        "items": [{"id": sub["item_id"], "price": price, "quantity": 1}]},
                        "after_completion": {"type": "redirect", "redirect": {"return_url": ret + "?plano=1"}}}
        try:
            s = self.c.create_portal_session(customer=cus, return_url=ret, flow_data=flow)
        except StripeError:
            if flow is None:
                raise
            log.warning("portal com troca direta recusado; abrindo o portal comum", extra={"event": "portal_flow_fallback"})
            s = self.c.create_portal_session(customer=cus, return_url=ret)
        return {"redirect_url": s.get("url")}

    # =============================================================== webhook
    def receive_webhook(self, db: Database, body: bytes, headers: dict) -> tuple[int, dict]:
        cfg = stripe_client.config()
        if not stripe_client.verify_signature(body, headers.get(stripe_client.SIGNATURE_HEADER), cfg.webhook_secret):
            log.warning("webhook da Stripe com assinatura inválida", extra={"event": "payment_webhook_unauthorized"})
            return 400, {"error": "assinatura inválida"}
        try:
            evt = json.loads(body or b"{}")
        except ValueError:
            return 400, {"error": "json inválido"}
        obj = ((evt.get("data") or {}).get("object")) if isinstance(evt, dict) else None
        if not isinstance(evt.get("id"), str) or not isinstance(evt.get("type"), str) or not isinstance(obj, dict):
            return 400, {"error": "evento sem id, tipo ou objeto"}
        if bool(evt.get("livemode")) != cfg.live:
            log.warning("evento da Stripe de outro modo (teste x produção): ignorado", extra={"event": "payment_event_mode"})
            return 200, {"ok": True, "ignored": "livemode"}
        eid, etype = evt["id"][:200], evt["type"][:80]
        db.conn.execute("INSERT OR IGNORE INTO stripe_events(id, type, object_id, livemode, received_at) VALUES (?,?,?,?,?)",
                        (eid, etype, str(obj.get("id") or "")[:120], int(bool(evt.get("livemode"))), now()))
        row = db.conn.execute("SELECT processed_at FROM stripe_events WHERE id=?", (eid,)).fetchone()
        if row["processed_at"]:
            log.info("evento repetido da Stripe: ignorado", extra={"event": "payment_event_duplicate", "type": etype})
            return 200, {"ok": True, "duplicate": True}
        try:
            outcome = self.process(db, etype, obj)
        except Exception as exc:  # noqa: BLE001 — fica sem processed_at: a Stripe reenvia (e o reconcile tenta)
            db.conn.execute("UPDATE stripe_events SET outcome='error' WHERE id=?", (eid,))
            log.warning("falha ao processar evento da Stripe", extra={"event": "payment_event_error", "type": etype,
                                                                      "detail": type(exc).__name__})
            return 500, {"error": "falha ao processar; tente de novo"}
        db.conn.execute("UPDATE stripe_events SET processed_at=?, outcome=? WHERE id=?", (now(), outcome, eid))
        return 200, {"ok": True, "outcome": outcome}

    def process(self, db: Database, etype: str, obj: dict) -> str:
        if etype not in HANDLED:
            log.info("evento da Stripe sem efeito: ignorado", extra={"event": "payment_event_ignored", "type": etype})
            return "ignored"
        if etype.startswith("checkout.session."):
            return self.on_session(db, obj, etype)
        if etype == "invoice.paid":
            return self.on_invoice_paid(db, obj["id"])
        if etype == "invoice.payment_failed":
            return self.on_invoice_failed(db, obj)
        if etype.startswith("customer.subscription."):
            return self.on_subscription(db, obj, deleted=etype.endswith(".deleted"))
        if etype == "charge.refunded":
            return self.on_refund(db, obj)
        return self.on_dispute(db, obj)

    def reprocess(self, db: Database, event_id: str) -> str:
        """Reconcile: relê o evento na API e processa de novo (eventos que ficaram sem processed_at)."""
        evt = self.c.get_event(event_id)
        obj = (evt.get("data") or {}).get("object") or {}
        outcome = self.process(db, evt.get("type") or "", obj)
        db.conn.execute("UPDATE stripe_events SET processed_at=?, outcome=? WHERE id=?", (now(), outcome, event_id))
        return outcome

    # --------------------------------------------------------------- conta do evento
    def _workspace_for(self, db: Database, *, sub_id=None, customer=None, metadata=None) -> str | None:
        if sub_id:
            r = db.conn.execute("SELECT workspace_id FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
            if r:
                return r[0]
        cus_ws = None
        if customer:
            r = db.conn.execute("SELECT id FROM workspaces WHERE stripe_customer_id=?", (customer,)).fetchone()
            cus_ws = r[0] if r else None
        wid = (metadata or {}).get("workspace_id")
        if wid and db.conn.execute("SELECT 1 FROM workspaces WHERE id=?", (wid,)).fetchone():
            if cus_ws and cus_ws != wid:
                log.warning("cliente da Stripe de outra conta: ignorado", extra={"event": "payment_customer_mismatch"})
                return None
            return wid
        return cus_ws

    def _credits_for(self, price_id: str | None, price_obj: dict | None, fallback: int) -> int:
        """Créditos do ciclo: metadado `credits` do preço ou do produto na Stripe; sem ele, o catálogo local."""
        n = _credits_meta(price_obj)
        product = (price_obj or {}).get("product")
        if n is None and isinstance(product, dict):
            n = _credits_meta(product)
        elif n is None and isinstance(product, str):
            n = self._product_credits(product)
        if n is None:
            return int(fallback)
        if n != int(fallback):
            log.info("créditos do metadado da Stripe diferentes do catálogo local: vale a Stripe",
                     extra={"event": "payment_credits_metadata", "credits": n})
        return n

    def _product_credits(self, product_id: str) -> int | None:
        hit = _PRODUCT_CACHE.get(product_id)
        if hit and time.monotonic() - hit[0] < PRODUCT_TTL_S:
            return hit[1]
        n = _credits_meta(self.c.get_product(product_id))
        _PRODUCT_CACHE[product_id] = (time.monotonic(), n)
        return n

    # --------------------------------------------------------------- checkout
    def on_session(self, db: Database, s: dict, etype: str) -> str:
        meta = s.get("metadata") or {}
        row = db.conn.execute("SELECT * FROM payments WHERE stripe_session_id=?", (s.get("id"),)).fetchone()
        if row is None and meta.get("order"):
            row = get(db, str(meta["order"]))
            if row is not None and row["stripe_session_id"] not in (None, s.get("id")):
                row = None
        if row is None:
            log.warning("sessão da Stripe que não é nossa: ignorada", extra={"event": "payment_session_unknown"})
            return "unknown_order"
        if row["account_id"] != (meta.get("workspace_id") or s.get("client_reference_id")):
            log.warning("sessão da Stripe de outra conta: nada creditado", extra={"event": "payment_mismatch", "payment_id": row["id"]})
            return "mismatch"
        if s.get("customer"):
            db.conn.execute("UPDATE workspaces SET stripe_customer_id=COALESCE(stripe_customer_id, ?) WHERE id=?",
                            (_id(s["customer"]), row["account_id"]))
        if etype == "checkout.session.expired":
            db.conn.execute("UPDATE payments SET status='expired', synced_at=? WHERE id=? AND status IN ('creating','pending')",
                            (now(), row["id"]))
            return "expired"
        if etype == "checkout.session.async_payment_failed":
            db.conn.execute("UPDATE payments SET status='failed', synced_at=?, note='pagamento não concluído' WHERE id=?"
                            " AND status IN ('creating','pending','processing')", (now(), row["id"]))
            return "failed"
        paid = s.get("payment_status") in ("paid", "no_payment_required")
        if s.get("mode") == "subscription":
            return self._link_subscription(db, row, s, paid)
        if not paid:   # Pix ainda não pago: espera o async_payment_succeeded
            db.conn.execute("UPDATE payments SET status='processing', stripe_payment_intent=?, synced_at=? WHERE id=?"
                            " AND status IN ('creating','pending')", (_id(s.get("payment_intent")), now(), row["id"]))
            return "awaiting_payment"
        return self._credit_topup(db, row, s)

    def _credit_topup(self, db: Database, row, s: dict) -> str:
        if (s.get("currency") or "brl").lower() != "brl":
            log.warning("avulso pago em outra moeda: revisar", extra={"event": "payment_currency", "payment_id": row["id"]})
        if s.get("amount_total") is not None and int(s["amount_total"]) != int(row["amount_cents"]):
            log.warning("valor pago diferente do catálogo (preço da Stripe mudou?): credita a quantidade comprada",
                        extra={"event": "payment_amount_diff", "payment_id": row["id"]})
        led = Ledger(db)
        with led.transaction():
            led.add(row["account_id"], int(row["credits"]) * 100, kind="purchase", origin="topup", payment_id=row["id"],
                    ext_ref=f"topup:{row['id']}", note=f"{row['credits']} créditos avulsos")
            db.conn.execute("UPDATE payments SET status='paid', paid_at=COALESCE(paid_at, ?), synced_at=?, "
                            "stripe_payment_intent=COALESCE(?, stripe_payment_intent), "
                            "amount_cents=COALESCE(?, amount_cents) WHERE id=?",
                            (now(), now(), _id(s.get("payment_intent")), s.get("amount_total"), row["id"]))
        log.info("avulso creditado", extra={"event": "payment_ledger", "payment_id": row["id"]})
        return "credited"

    def _link_subscription(self, db: Database, row, s: dict, paid: bool) -> str:
        sub_id = _id(s.get("subscription"))
        if sub_id:
            sub = s["subscription"] if isinstance(s.get("subscription"), dict) else self.c.get_subscription(sub_id)
            self._upsert_subscription(db, row["account_id"], sub)
            db.conn.execute("UPDATE payments SET stripe_subscription_id=? WHERE id=?", (sub_id, row["id"]))
        if paid:
            db.conn.execute("UPDATE payments SET status='paid', paid_at=COALESCE(paid_at, ?), synced_at=? WHERE id=?",
                            (now(), now(), row["id"]))
        return "subscription_linked"

    # --------------------------------------------------------------- assinatura
    def _upsert_subscription(self, db: Database, wid: str, sub: dict, *, deleted: bool = False) -> dict:
        item = _sub_item(sub)
        price_id, _ = _line_price(item)
        found = catalog.plan_for_price(price_id)
        plan_code, interval = (found[0]["code"], found[1]) if found else (None, None)
        status = "canceled" if deleted else str(sub.get("status") or "incomplete")
        period_end = _sub_period_end(sub)
        cur = db.conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub["id"],)).fetchone()
        if cur is None:
            db.conn.execute("INSERT INTO subscriptions(id, workspace_id, customer_id, item_id, price_id, plan, interval, status,"
                            " cancel_at_period_end, current_period_end, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sub["id"], wid, _id(sub.get("customer")), item.get("id"), price_id, plan_code, interval, status,
                             int(bool(sub.get("cancel_at_period_end"))), period_end, now(), now()))
        else:
            db.conn.execute("UPDATE subscriptions SET customer_id=COALESCE(?, customer_id), item_id=COALESCE(?, item_id),"
                            " price_id=COALESCE(?, price_id), plan=COALESCE(?, plan), interval=COALESCE(?, interval),"
                            " status=?, cancel_at_period_end=?, current_period_end=COALESCE(?, current_period_end),"
                            " updated_at=? WHERE id=?",
                            (_id(sub.get("customer")), item.get("id"), price_id, plan_code, interval, status,
                             int(bool(sub.get("cancel_at_period_end"))), period_end, now(), sub["id"]))
        return {"plan": plan_code, "price_id": price_id, "price": item.get("price"), "period_end": period_end,
                "status": status, "previous": cur}

    def on_subscription(self, db: Database, sub: dict, *, deleted: bool = False) -> str:
        wid = self._workspace_for(db, sub_id=sub.get("id"), customer=_id(sub.get("customer")), metadata=sub.get("metadata"))
        if wid is None:
            log.warning("assinatura de cliente desconhecido: ignorada", extra={"event": "payment_subscription_unknown"})
            return "unknown_customer"
        led = Ledger(db)
        with led.transaction():
            u = self._upsert_subscription(db, wid, sub, deleted=deleted)
            if deleted:
                return "canceled"
            prev = db.conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub["id"],)).fetchone()
            if not u["plan"] or u["status"] not in ("active", "trialing") or prev["cycle_end"] is None \
                    or prev["cycle_end"] != u["period_end"]:
                return "updated"     # ciclo ainda sem fatura paga: quem concede é o invoice.paid
            p = catalog.plan(u["plan"])
            new_credits = self._credits_for(u["price_id"], u["price"] if isinstance(u["price"], dict) else None, p["credits"])
            if new_credits <= int(prev["cycle_credits"]):
                return "updated"     # downgrade (ou mesmo nível): vale no próximo ciclo
            diff = new_credits - int(prev["cycle_credits"])
            led.add(wid, diff * 100, kind="subscription", origin="subscription", expires_at=u["period_end"],
                    ext_ref=f"upgrade:{sub['id']}:{u['period_end']}:{new_credits}", note=f"upgrade para o plano {p['name']}")
            db.conn.execute("UPDATE subscriptions SET cycle_credits=? WHERE id=?", (new_credits, sub["id"]))
        log.info("upgrade de plano: diferença concedida", extra={"event": "payment_upgrade", "credits": diff})
        return "upgrade"

    def on_invoice_failed(self, db: Database, inv: dict) -> str:
        sub_id = _invoice_subscription(inv)
        if sub_id:
            db.conn.execute("UPDATE subscriptions SET status='past_due', updated_at=? WHERE id=? AND status IN ('active','trialing')",
                            (now(), sub_id))
        log.warning("cobrança do plano falhou", extra={"event": "payment_invoice_failed"})
        return "payment_failed"

    def on_invoice_paid(self, db: Database, invoice_id: str) -> str:
        inv = self.c.get_invoice(invoice_id)   # relida na API (versão fixada): não depende do formato do webhook
        if inv.get("status") != "paid":
            return "not_paid"
        sub_id = _invoice_subscription(inv)
        wid = self._workspace_for(db, sub_id=sub_id, customer=_id(inv.get("customer")), metadata=_invoice_metadata(inv))
        if wid is None:
            log.warning("fatura de cliente desconhecido: ignorada", extra={"event": "payment_invoice_unknown"})
            return "unknown_customer"
        line, found = None, None
        for ln in ((inv.get("lines") or {}).get("data") or []):
            pid, _ = _line_price(ln)
            found = catalog.plan_for_price(pid)
            if found:
                line = ln
                break
        if line is None:
            log.warning("fatura sem preço de plano conhecido: nada concedido", extra={"event": "payment_invoice_no_plan"})
            return "no_plan_line"
        if inv.get("billing_reason") not in GRANT_REASONS:
            return "ignored_reason"      # ex.: fatura de proração do upgrade (a diferença já veio no subscription.updated)
        p, interval = found
        price_id, price_obj = _line_price(line)
        credits = self._credits_for(price_id, price_obj, p["credits"])
        period_end = _iso((line.get("period") or {}).get("end")) or _iso(inv.get("period_end"))
        led = Ledger(db)
        with led.transaction():
            db.conn.execute(
                "INSERT OR IGNORE INTO payments(id, account_id, method, package_code, credits, amount_cents, status, created_at,"
                " paid_at, provider, kind, stripe_invoice_id, stripe_payment_intent, stripe_charge_id, stripe_subscription_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("kpay"), wid, "stripe", p["code"], credits, int(inv.get("amount_paid") or 0), "paid", now(), now(),
                 "stripe", "invoice", inv["id"], _id(inv.get("payment_intent")), _id(inv.get("charge")), sub_id))
            pay = db.conn.execute("SELECT id FROM payments WHERE stripe_invoice_id=?", (inv["id"],)).fetchone()
            # o ciclo anterior acaba aqui: o que sobrou dele vence agora (créditos do plano não acumulam)
            db.conn.execute("UPDATE credit_lots SET expires_at=? WHERE workspace_id=? AND origin='subscription'"
                            " AND closed_at IS NULL AND expires_at<? AND expires_at>?", (now(), wid, period_end, now()))
            led.add(wid, credits * 100, kind="subscription", origin="subscription", expires_at=period_end,
                    payment_id=pay["id"], ext_ref=f"invoice:{inv['id']}", note=f"ciclo até {period_end[8:10]}/{period_end[5:7]}")
            if sub_id:
                cur = db.conn.execute("SELECT 1 FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
                if cur is None:
                    self._upsert_subscription(db, wid, {"id": sub_id, "customer": inv.get("customer"), "status": "active",
                                                        "items": {"data": [{"id": line.get("subscription_item"),
                                                                            "price": {"id": price_id},
                                                                            "current_period_end": (line.get("period") or {}).get("end")}]}})
                # fatura antiga reprocessada fora de ordem não volta o ciclo para trás
                db.conn.execute("UPDATE subscriptions SET cycle_end=?, cycle_credits=?, current_period_end=?, plan=?,"
                                " price_id=?, interval=?, status=CASE WHEN status IN ('canceled') THEN status ELSE 'active' END,"
                                " updated_at=? WHERE id=? AND (cycle_end IS NULL OR cycle_end<=?)",
                                (period_end, credits, period_end, p["code"], price_id, interval, now(), sub_id, period_end))
                db.conn.execute("UPDATE payments SET status='paid', paid_at=COALESCE(paid_at, ?), synced_at=? WHERE kind='plan'"
                                " AND account_id=? AND status IN ('creating','pending','processing') AND"
                                " (stripe_subscription_id=? OR stripe_subscription_id IS NULL)", (now(), now(), wid, sub_id))
        log.info("créditos do ciclo concedidos", extra={"event": "payment_cycle_granted", "credits": credits})
        return "granted"

    # --------------------------------------------------------------- reembolso e contestação
    def _payment_for_charge(self, db: Database, *, charge_id=None, intent=None, invoice=None):
        for col, v in (("stripe_payment_intent", intent), ("stripe_charge_id", charge_id), ("stripe_invoice_id", invoice)):
            if v:
                row = db.conn.execute(f"SELECT * FROM payments WHERE {col}=? AND kind IN ('topup','invoice')", (v,)).fetchone()
                if row is not None:
                    return row
        return None

    def _flag(self, db: Database, wid: str, flag: str) -> None:
        db.conn.execute("UPDATE workspaces SET billing_flag=?, billing_flag_at=? WHERE id=?", (flag, now(), wid))

    def on_refund(self, db: Database, ch: dict) -> str:
        row = self._payment_for_charge(db, charge_id=ch.get("id"), intent=_id(ch.get("payment_intent")),
                                       invoice=_id(ch.get("invoice")))
        if row is None:
            log.warning("reembolso de cobrança que não é nossa: ignorado", extra={"event": "payment_refund_unknown"})
            return "unknown_payment"
        amount, refunded = int(ch.get("amount") or 0), int(ch.get("amount_refunded") or 0)
        if amount <= 0 or refunded <= 0:
            return "nothing_refunded"
        full = refunded >= amount
        led = Ledger(db)
        taken = 0
        with led.transaction():
            for lot in db.conn.execute("SELECT id, amount_cc FROM credit_lots WHERE payment_id=?", (row["id"],)).fetchall():
                target = lot["amount_cc"] if full else math.ceil(lot["amount_cc"] * refunded / amount)
                taken += led.revoke_lot(lot["id"], target, note="reembolso" if full else "reembolso parcial", close=full)
            db.conn.execute("UPDATE payments SET status=?, refunded_at=COALESCE(refunded_at, ?), stripe_charge_id="
                            "COALESCE(stripe_charge_id, ?) WHERE id=?",
                            ("refunded" if full else "partially_refunded", now(), ch.get("id"), row["id"]))
            self._flag(db, row["account_id"], "refund")
        log.warning("reembolso: créditos não usados removidos", extra={"event": "payment_refund", "payment_id": row["id"],
                                                                        "delta_cc": -taken})
        return "refunded"

    def on_dispute(self, db: Database, d: dict) -> str:
        row = self._payment_for_charge(db, charge_id=_id(d.get("charge")), intent=_id(d.get("payment_intent")))
        if row is None:
            log.warning("contestação de cobrança que não é nossa: ignorada", extra={"event": "payment_dispute_unknown"})
            return "unknown_payment"
        led = Ledger(db)
        taken = 0
        with led.transaction():
            for lot in db.conn.execute("SELECT id, amount_cc FROM credit_lots WHERE payment_id=?", (row["id"],)).fetchall():
                taken += led.revoke_lot(lot["id"], lot["amount_cc"], note="contestação da compra", close=True)
            db.conn.execute("UPDATE payments SET status='disputed', refunded_at=COALESCE(refunded_at, ?) WHERE id=?",
                            (now(), row["id"]))
            self._flag(db, row["account_id"], "dispute")
        log.warning("contestação: créditos não usados removidos e conta marcada",
                    extra={"event": "payment_dispute", "payment_id": row["id"], "delta_cc": -taken})
        return "disputed"

    # =============================================================== volta do checkout (rede de segurança)
    def sync_order(self, db: Database, row) -> None:
        if row["status"] not in OPEN or not row["stripe_session_id"]:
            return
        s = self.c.get_checkout_session(row["stripe_session_id"])
        if s.get("status") == "expired":
            self.on_session(db, s, "checkout.session.expired")
            return
        if s.get("status") != "complete":
            return
        self.on_session(db, s, "checkout.session.completed")
        if s.get("mode") == "subscription" and _id(s.get("subscription")):
            sub = self.c.get_subscription(_id(s["subscription"]))
            inv = _id(sub.get("latest_invoice"))
            if inv:
                self.on_invoice_paid(db, inv)
