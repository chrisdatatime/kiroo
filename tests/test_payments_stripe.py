"""Planos e créditos avulsos pela Stripe (tudo com uma Stripe falsa: nenhuma rede real).

Cobre: validação da quantidade do avulso (49, 50, 1.000, 1.001, decimal, negativo, texto), checkout de plano e de
avulso (o navegador nunca manda preço), webhook com assinatura válida, inválida, vencida e evento duplicado, créditos
do ciclo pela fatura (uma vez por fatura), renovação (o ciclo anterior vence), upgrade (diferença na hora) e downgrade
(próximo ciclo), Pix pago depois, reembolso e contestação (só o que não foi usado, conta marcada), Portal do cliente,
kill switch, configuração e o cliente HTTP (formato da Stripe, versão fixa).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from studio import catalog, payments, stripe_client
from studio.config import load_settings
from studio.credits import Ledger
from studio.db import Database
from studio.stripe_client import StripeError
from studio.web.server import WEBHOOK_PATH, App

from .conftest import login_app

SECRET = "whsec_" + "test_ficticio_0123456789abcdef"  # fictício, montado em duas partes para não casar com a regra generic-api-key do gitleaks
KEY = "sk_test_FICTICIA_nao_use_0000000000"
PRICES = {"STRIPE_PRICE_BASICO_M": "price_test_basico", "STRIPE_PRICE_PRO_M": "price_test_pro",
          "STRIPE_PRICE_ESTUDIO_M": "price_test_estudio", "STRIPE_PRICE_AVULSO": "price_test_avulso"}
HOST = {"Host": "127.0.0.1:8765"}
CREDITS = {"price_test_basico": 120, "price_test_pro": 320, "price_test_estudio": 800}


def ts(days: float) -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


class FakeStripe:
    """Stripe falsa: guarda sessões, assinaturas e faturas em memória; o teste muda o estado "do lado da Stripe"."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.sessions: dict[str, dict] = {}
        self.subs: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.fail = False
        self.portal_flow_fails = False

    def create_customer(self, *, email, name, metadata, idempotency_key):
        self.calls.append(("customer", metadata["workspace_id"], idempotency_key))
        return {"id": "cus_test_" + metadata["workspace_id"][-6:]}

    def create_checkout_session(self, params, *, idempotency_key):
        if self.fail:
            raise StripeError("Stripe indisponível", 503)
        sid = f"cs_test_{len(self.sessions) + 1:04d}"
        self.calls.append(("session", params, idempotency_key))
        self.sessions[sid] = {"id": sid, "status": "open", "mode": params["mode"], "customer": params["customer"],
                              "metadata": params["metadata"], "client_reference_id": params["client_reference_id"],
                              "payment_status": "unpaid", "url": f"https://checkout.stripe.com/c/pay/{sid}"}
        return dict(self.sessions[sid])

    def get_checkout_session(self, sid):
        return dict(self.sessions[sid])

    def create_portal_session(self, *, customer, return_url, flow_data=None):
        self.calls.append(("portal", customer, flow_data))
        if flow_data and self.portal_flow_fails:
            raise StripeError("configuração do portal não permite essa troca", 400)
        return {"url": "https://billing.stripe.com/p/session/test_1"}

    def get_subscription(self, sid):
        return json.loads(json.dumps(self.subs[sid]))

    def get_invoice(self, iid):
        self.calls.append(("get_invoice", iid))
        return json.loads(json.dumps(self.invoices[iid]))

    def get_product(self, pid):
        return {"id": pid, "metadata": {}}

    def get_event(self, eid):
        return self.events[eid]


@pytest.fixture
def fake(monkeypatch):
    f = FakeStripe()
    monkeypatch.setattr(payments, "make_client", lambda: f)
    return f


@pytest.fixture
def pay_env(monkeypatch):
    monkeypatch.setenv("PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", KEY)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    for k, v in PRICES.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def app(settings, tmp_path, pay_env, fake):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    a = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(a, {}, email="admin@example.com")          # o primeiro vira administrador (conta isenta)
    login_app(a, HOST, email="cliente@example.com")       # o cliente que compra
    return a


def post(app, path, body):
    return app.handle("POST", path, {**HOST, "X-Studio-Token": app.token, "User-Agent": "Mozilla/5.0 teste"},
                      json.dumps(body).encode(), peer="203.0.113.7")


def get(app, path):
    return app.handle("GET", path, {**HOST}, b"")


_N = [0]


def send(app, etype, obj, *, eid=None, secret=SECRET, t=None, sig=None, livemode=False):
    _N[0] += 1
    body = json.dumps({"id": eid or f"evt_test_{_N[0]:05d}", "object": "event", "type": etype, "livemode": livemode,
                       "data": {"object": obj}}).encode()
    h = {"Host": HOST["Host"], "Stripe-Signature": sig if sig is not None else stripe_client.sign(body, secret, t)}
    r = app.handle("POST", WEBHOOK_PATH, h, body)
    return r.status, json.loads(r.body)


def db_of(app):
    return Database(app.settings().db_path)


def wid_of(app):
    return json.loads(get(app, "/api/me").body)["workspace"]["id"]


def ledger(app, fn):
    db = db_of(app)
    try:
        return fn(Ledger(db), db)
    finally:
        db.close()


def balance(app):
    return ledger(app, lambda led, db: led.balance(wid_of(app)))


def left(app):
    def f(led, db):
        out = {}
        for lot in led.lots(wid_of(app), valid_only=True):
            out[lot["origin"]] = out.get(lot["origin"], 0) + lot["remaining_cc"] // 100
        return out
    return ledger(app, f)


def checkout(app, **body):
    r = post(app, "/api/payments/checkout", body)
    assert r.status == 200, r.body
    return json.loads(r.body)


def pay_topup(app, fake, credits=100, *, status="paid"):
    out = checkout(app, kind="topup", credits=credits)
    sid = next(s for s, v in fake.sessions.items() if v["metadata"]["order"] == out["payment"]["id"])
    obj = {**fake.sessions[sid], "status": "complete", "payment_status": status, "amount_total": credits * 44,
           "currency": "brl", "payment_intent": f"pi_{sid}"}
    fake.sessions[sid] = obj
    return out, sid, send(app, "checkout.session.completed", obj)


def subscribe(app, fake, plan="pro", *, period_end=None):
    """Checkout de plano + sessão concluída + primeira fatura paga (como a Stripe faria)."""
    out = checkout(app, kind="plan", plan=plan)
    sid = next(s for s, v in fake.sessions.items() if v["metadata"]["order"] == out["payment"]["id"])
    price = PRICES[f"STRIPE_PRICE_{plan.upper()}_M"]
    end = period_end or ts(30)
    fake.subs["sub_test_1"] = {"id": "sub_test_1", "object": "subscription", "status": "active", "customer": fake.sessions[sid]["customer"],
                               "cancel_at_period_end": False, "current_period_end": end, "metadata": {"workspace_id": wid_of(app)},
                               "items": {"data": [{"id": "si_test_1", "price": {"id": price}, "current_period_end": end}]},
                               "latest_invoice": "in_test_1"}
    obj = {**fake.sessions[sid], "status": "complete", "payment_status": "paid", "subscription": "sub_test_1"}
    fake.sessions[sid] = obj
    assert send(app, "checkout.session.completed", obj)[0] == 200
    invoice(fake, "in_test_1", price=price, end=end, reason="subscription_create", customer=obj["customer"])
    return out, send(app, "invoice.paid", {"id": "in_test_1", "object": "invoice"})


def invoice(fake, iid, *, price, end, reason="subscription_cycle", customer="cus_x", sub="sub_test_1", amount=9990):
    fake.invoices[iid] = {"id": iid, "object": "invoice", "status": "paid", "billing_reason": reason, "customer": customer,
                          "subscription": sub, "amount_paid": amount, "payment_intent": f"pi_{iid}", "charge": f"ch_{iid}",
                          "lines": {"data": [{"id": f"il_{iid}", "subscription_item": "si_test_1",
                                              "period": {"start": end - 30 * 86400, "end": end},
                                              "price": {"id": price, "metadata": {},
                                                        "product": {"id": "prod_x", "metadata": {"credits": str(CREDITS[price])}}}}]}}


def sub_update(fake, price, *, end=None, status="active"):
    s = fake.subs["sub_test_1"]
    s["items"]["data"][0]["price"] = {"id": price}
    s["status"] = status
    if end:
        s["current_period_end"] = end
        s["items"]["data"][0]["current_period_end"] = end
    return json.loads(json.dumps(s))


# ================================================================= quantidade do avulso (servidor)
@pytest.mark.parametrize("credits,ok", [(49, False), (50, True), (1000, True), (1001, False), (50.5, False), (100.0, False),
                                        (-10, False), (0, False), ("100", False), (True, False), (None, False)])
def test_topup_quantity_rules(credits, ok):
    if ok:
        q = catalog.topup_quote(credits)
        assert q["credits"] == credits and q["quantity"] == credits and q["amount_cents"] == credits * 44
    else:
        with pytest.raises(catalog.CatalogError):
            catalog.topup_quote(credits)


def test_topup_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("TOPUP_MIN_CREDITS", "100")
    monkeypatch.setenv("TOPUP_MAX_CREDITS", "300")
    assert catalog.topup_limits() == (100, 300)
    with pytest.raises(catalog.CatalogError):
        catalog.topup_quote(99)
    with pytest.raises(catalog.CatalogError):
        catalog.topup_quote(301)
    assert catalog.public_view()["topup"]["shortcuts"] == [100, 200]          # atalho fora dos limites some


@pytest.mark.parametrize("credits", [49, 1001, 50.5, -10, "100", True])
def test_api_refuses_invalid_topup_quantities_and_creates_nothing(app, fake, credits):
    r = post(app, "/api/payments/checkout", {"kind": "topup", "credits": credits})
    assert r.status == 400 and json.loads(r.body)["code"] == "invalid_quantity"
    assert not [c for c in fake.calls if c[0] == "session"]


def test_browser_never_sends_the_price(app, fake):
    out = checkout(app, kind="topup", credits=200, amount_cents=1, price="price_hacker", unit_price_cents=1)
    params = [c for c in fake.calls if c[0] == "session"][-1][1]
    assert params["mode"] == "payment" and params["line_items"] == [{"price": "price_test_avulso", "quantity": 200}]
    assert out["payment"]["amount_cents"] == 8800 and out["redirect_url"].startswith("https://checkout.stripe.com/")
    assert params["metadata"]["workspace_id"] == wid_of(app) and params["success_url"].endswith(f"/pricing?compra={out['payment']['id']}")


# ================================================================= webhook: assinatura e idempotência
def test_webhook_with_invalid_signature_is_refused_and_stores_nothing(app, fake):
    obj = {"id": "in_x", "object": "invoice"}
    assert send(app, "invoice.paid", obj, secret="whsec_outro_segredo_000000")[0] == 400
    assert send(app, "invoice.paid", obj, sig="")[0] == 400
    assert send(app, "invoice.paid", obj, sig="t=1,v1=abc")[0] == 400
    assert send(app, "invoice.paid", obj, t=int(time.time()) - 3600)[0] == 400       # assinatura velha (replay)
    assert ledger(app, lambda led, db: db.conn.execute("SELECT COUNT(*) FROM stripe_events").fetchone()[0]) == 0


def test_webhook_valid_signature_and_duplicate_event_credits_once(app, fake):
    _, sid, (code, body) = pay_topup(app, fake, 100)
    assert code == 200 and body["outcome"] == "credited"
    assert balance(app) == 10000 and left(app) == {"topup": 100}
    obj = fake.sessions[sid]
    evt = "evt_dup_00001"
    assert send(app, "checkout.session.completed", obj, eid=evt)[1]["outcome"] in ("credited",)
    assert send(app, "checkout.session.completed", obj, eid=evt)[1].get("duplicate") is True   # mesmo id: ignorado
    assert balance(app) == 10000                                                              # outro id, mesma sessão: idem
    st = json.loads(get(app, "/api/payments/" + obj["metadata"]["order"]).body)
    assert st["status"] == "paid" and st["credits"] == 100 and st["balance"] == "100"


def test_webhook_off_when_payments_disabled(app, monkeypatch):
    monkeypatch.setenv("PAYMENTS_ENABLED", "false")
    assert send(app, "invoice.paid", {"id": "in_x"})[0] == 404
    assert post(app, "/api/payments/checkout", {"kind": "topup", "credits": 100}).status == 404
    cat = json.loads(get(app, "/api/payments/catalog").body)
    assert cat["online"] is False and [p["code"] for p in cat["plans"]] == ["basico", "pro", "estudio"]


def test_event_from_the_other_mode_is_ignored(app, fake):
    _, sid, _ = pay_topup(app, fake, 100, status="unpaid")
    obj = {**fake.sessions[sid], "payment_status": "paid"}
    code, body = send(app, "checkout.session.completed", obj, livemode=True)
    assert code == 200 and body["ignored"] == "livemode" and balance(app) == 0


def test_processing_error_answers_500_so_stripe_retries(app, fake):
    code, _ = send(app, "invoice.paid", {"id": "in_nao_existe", "object": "invoice"}, eid="evt_retry_1")
    assert code == 500
    invoice(fake, "in_nao_existe", price="price_test_pro", end=ts(30), reason="subscription_create",
            customer="cus_test_" + wid_of(app)[-6:])
    db = db_of(app)
    try:
        db.conn.execute("UPDATE workspaces SET stripe_customer_id=? WHERE id=?", ("cus_test_" + wid_of(app)[-6:], wid_of(app)))
    finally:
        db.close()
    assert send(app, "invoice.paid", {"id": "in_nao_existe"}, eid="evt_retry_1")[1]["outcome"] == "granted"   # reenvio


# ================================================================= avulso
def test_topup_credits_exactly_the_quantity_as_non_expiring_topup(app, fake):
    pay_topup(app, fake, 137)
    lots = ledger(app, lambda led, db: led.lots(wid_of(app)))
    assert [(lot["origin"], lot["amount_cc"], lot["expires_at"]) for lot in lots] == [("topup", 13700, None)]


def test_pix_paid_later_credits_on_async_success(app, fake):
    _, sid, (code, body) = pay_topup(app, fake, 100, status="unpaid")
    assert body["outcome"] == "awaiting_payment" and balance(app) == 0
    obj = {**fake.sessions[sid], "payment_status": "paid"}
    assert send(app, "checkout.session.async_payment_succeeded", obj)[1]["outcome"] == "credited"
    assert balance(app) == 10000


def test_return_from_checkout_syncs_when_the_webhook_is_late(app, fake):
    out = checkout(app, kind="topup", credits=60)
    sid = next(iter(fake.sessions))
    fake.sessions[sid].update(status="complete", payment_status="paid", amount_total=2640, payment_intent="pi_late")
    db = db_of(app)
    try:
        db.conn.execute("UPDATE payments SET synced_at='2026-01-01T00:00:00+00:00' WHERE id=?", (out["payment"]["id"],))
    finally:
        db.close()
    st = json.loads(get(app, "/api/payments/" + out["payment"]["id"]).body)
    assert st["status"] == "paid" and balance(app) == 6000


def test_session_of_another_account_never_credits(app, fake):
    _, sid, _ = pay_topup(app, fake, 100, status="unpaid")
    obj = {**fake.sessions[sid], "payment_status": "paid", "metadata": {**fake.sessions[sid]["metadata"], "workspace_id": "ws_outra"},
           "client_reference_id": "ws_outra"}
    assert send(app, "checkout.session.completed", obj)[1]["outcome"] == "mismatch" and balance(app) == 0


def test_provider_down_on_checkout_charges_nothing(app, fake):
    fake.fail = True
    r = post(app, "/api/payments/checkout", {"kind": "topup", "credits": 100})
    assert r.status == 502 and json.loads(r.body)["code"] == "provider_error"


def test_exempt_account_does_not_buy(app, fake):
    admin = {}
    login_app(app, admin, email="admin@example.com")
    r = app.handle("POST", "/api/payments/checkout", {**admin, "X-Studio-Token": app.token},
                   json.dumps({"kind": "topup", "credits": 100}).encode())
    assert r.status == 400


# ================================================================= plano
def test_plan_checkout_then_invoice_grants_cycle_credits_that_expire(app, fake):
    out, (code, body) = subscribe(app, fake, "pro")
    params = [c for c in fake.calls if c[0] == "session"][-1][1]
    assert params["mode"] == "subscription" and params["line_items"] == [{"price": "price_test_pro", "quantity": 1}]
    assert code == 200 and body["outcome"] == "granted"
    assert left(app) == {"subscription": 320}
    lot = ledger(app, lambda led, db: led.lots(wid_of(app)))[0]
    assert lot["origin"] == "subscription" and lot["expires_at"] is not None
    me = json.loads(get(app, "/api/me").body)
    assert me["plan"]["plan"] == "pro" and me["plan"]["subscription"]["status"] == "active"
    assert json.loads(get(app, "/api/payments/" + out["payment"]["id"]).body)["status"] == "paid"


def test_same_invoice_in_two_events_grants_once(app, fake):
    subscribe(app, fake, "pro")
    assert send(app, "invoice.paid", {"id": "in_test_1"})[1]["outcome"] == "granted"   # outro evento, mesma fatura
    assert left(app) == {"subscription": 320} and balance(app) == 32000
    n = ledger(app, lambda led, db: db.conn.execute("SELECT COUNT(*) FROM payments WHERE stripe_invoice_id='in_test_1'").fetchone()[0])
    assert n == 1


def test_second_subscription_checkout_is_refused(app, fake):
    subscribe(app, fake, "basico")
    r = post(app, "/api/payments/checkout", {"kind": "plan", "plan": "pro"})
    assert r.status == 400 and json.loads(r.body)["code"] == "has_subscription"


def test_annual_and_unknown_plans_are_refused(app, fake):
    assert json.loads(post(app, "/api/payments/checkout", {"kind": "plan", "plan": "pro", "interval": "year"}).body)["code"] == "invalid_interval"
    assert json.loads(post(app, "/api/payments/checkout", {"kind": "plan", "plan": "ouro"}).body)["code"] == "invalid_plan"


def test_renewal_expires_the_previous_cycle_and_grants_the_new_one(app, fake):
    end1 = ts(1)
    subscribe(app, fake, "pro", period_end=end1)
    ledger(app, lambda led, db: led.reserve_pool(wid_of(app), "prod_r", 2000, ref="base"))     # usou 20 do plano
    end2 = ts(31)
    invoice(fake, "in_test_2", price="price_test_pro", end=end2, reason="subscription_cycle")
    assert send(app, "invoice.paid", {"id": "in_test_2"})[1]["outcome"] == "granted"
    assert left(app) == {"subscription": 320}                       # sobrou 300 do ciclo 1: não acumula
    kinds = ledger(app, lambda led, db: [r["kind"] for r in led.statement(wid_of(app))])
    assert "expire" in kinds


def test_upgrade_grants_the_difference_now_and_downgrade_waits_for_the_next_cycle(app, fake):
    end = ts(30)
    subscribe(app, fake, "pro", period_end=end)
    code, body = send(app, "customer.subscription.updated", sub_update(fake, "price_test_estudio"))
    assert body["outcome"] == "upgrade" and left(app) == {"subscription": 800}         # 320 + 480
    assert send(app, "customer.subscription.updated", sub_update(fake, "price_test_estudio"))[1]["outcome"] == "updated"
    assert left(app) == {"subscription": 800}                                            # repetido: nada
    assert send(app, "customer.subscription.updated", sub_update(fake, "price_test_basico"))[1]["outcome"] == "updated"
    assert left(app) == {"subscription": 800}                                            # downgrade: nada agora
    assert send(app, "customer.subscription.updated", sub_update(fake, "price_test_pro"))[1]["outcome"] == "updated"
    assert left(app) == {"subscription": 800}                                            # voltar a subir no ciclo: nada
    invoice(fake, "in_test_2", price="price_test_basico", end=end + 30 * 86400)
    db = db_of(app)
    try:   # o ciclo 1 terminou
        db.conn.execute("UPDATE credit_lots SET expires_at=? WHERE origin='subscription'",
                        ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds"),))
    finally:
        db.close()
    send(app, "invoice.paid", {"id": "in_test_2"})
    assert left(app) == {"subscription": 120}                                            # próximo ciclo já no Básico


def test_payment_failed_and_cancellation(app, fake):
    subscribe(app, fake, "pro")
    assert send(app, "invoice.payment_failed", {"id": "in_f", "subscription": "sub_test_1"})[1]["outcome"] == "payment_failed"
    assert json.loads(get(app, "/api/me").body)["plan"]["subscription"]["status"] == "past_due"
    deleted = {**fake.subs["sub_test_1"], "status": "canceled"}
    assert send(app, "customer.subscription.deleted", deleted)[1]["outcome"] == "canceled"
    me = json.loads(get(app, "/api/me").body)
    assert me["plan"]["plan"] == "free" and left(app) == {"subscription": 320}           # o ciclo pago continua até vencer


def test_portal_and_change_plan_flow(app, fake):
    r = post(app, "/api/payments/portal", {})
    assert r.status == 400 and json.loads(r.body)["code"] == "no_customer"
    subscribe(app, fake, "pro")
    out = json.loads(post(app, "/api/payments/portal", {}).body)
    assert out["redirect_url"].startswith("https://billing.stripe.com/")
    post(app, "/api/payments/portal", {"plan": "estudio"})
    flow = [c for c in fake.calls if c[0] == "portal"][-1][2]
    assert flow["type"] == "subscription_update_confirm"
    assert flow["subscription_update_confirm"]["items"] == [{"id": "si_test_1", "price": "price_test_estudio", "quantity": 1}]
    fake.portal_flow_fails = True                                       # portal sem a troca liberada: abre o comum
    assert json.loads(post(app, "/api/payments/portal", {"plan": "basico"}).body)["redirect_url"]


# ================================================================= reembolso e contestação
def test_refund_removes_only_unused_credits_and_marks_the_account(app, fake):
    _, sid, _ = pay_topup(app, fake, 100)
    ledger(app, lambda led, db: led.reserve_pool(wid_of(app), "prod_u", 2000, ref="base"))   # 20 já em uso
    ch = {"id": "ch_1", "object": "charge", "payment_intent": f"pi_{sid}", "amount": 4400, "amount_refunded": 2200}
    assert send(app, "charge.refunded", ch)[1]["outcome"] == "refunded"
    assert balance(app) == 3000                                        # metade (50) estornada dos 80 não usados
    assert send(app, "charge.refunded", ch)[1]["outcome"] == "refunded" and balance(app) == 3000   # repetido: nada
    send(app, "charge.refunded", {**ch, "amount_refunded": 4400})
    assert balance(app) == 0                                           # nunca negativo
    flag = ledger(app, lambda led, db: db.conn.execute("SELECT billing_flag FROM workspaces WHERE id=?", (wid_of(app),)).fetchone()[0])
    assert flag == "refund"


def test_dispute_removes_unused_plan_credits_and_flags(app, fake):
    subscribe(app, fake, "pro")
    d = {"id": "dp_1", "object": "dispute", "charge": "ch_in_test_1", "payment_intent": "pi_in_test_1", "amount": 9990}
    assert send(app, "charge.dispute.created", d)[1]["outcome"] == "disputed"
    assert balance(app) == 0
    flag = ledger(app, lambda led, db: db.conn.execute("SELECT billing_flag FROM workspaces WHERE id=?", (wid_of(app),)).fetchone()[0])
    assert flag == "dispute"


def test_refund_of_an_unknown_charge_is_ignored(app, fake):
    assert send(app, "charge.refunded", {"id": "ch_x", "payment_intent": "pi_x", "amount": 100, "amount_refunded": 100})[1]["outcome"] == "unknown_payment"


# ================================================================= tela, métricas e CLI
def test_catalog_endpoint_has_plans_topup_and_subscription(app, fake):
    cat = json.loads(get(app, "/api/payments/catalog").body)
    assert cat["online"] is True and cat["annual_enabled"] is False and cat["video_price_credits"] == 20
    assert {p["code"]: p["credits"] for p in cat["plans"]} == {"basico": 120, "pro": 320, "estudio": 800}
    assert cat["topup"] == {"unit_price_cents": 44, "min_credits": 50, "max_credits": 1000, "shortcuts": [100, 200, 500]}
    assert not any("Download" in f["text"] for p in cat["plans"] for f in p["features"])   # [confirmar]/inexistente: fora
    assert "price_test" not in json.dumps(cat)                                             # id da Stripe não vai à tela
    me = json.loads(get(app, "/api/me").body)
    assert me["payments"]["online"] is True and me["payments"]["topup"]["min_credits"] == 50


def test_month_metrics_count_invoices_and_topups(app, fake):
    subscribe(app, fake, "pro")
    pay_topup(app, fake, 100)
    m = ledger(app, lambda led, db: payments.month_metrics(db))
    assert m["by_kind"]["invoice"]["purchases"] == 1 and m["by_kind"]["topup"]["purchases"] == 1
    assert m["gross_revenue_cents"] == 9990 + 4400 and m["credits_sold"] == 420


# ================================================================= configuração e cliente
BASE_ENV = {"PAYMENTS_ENABLED": "true", "STRIPE_SECRET_KEY": KEY, "STRIPE_WEBHOOK_SECRET": SECRET, **PRICES}


@pytest.mark.parametrize("env,err", [
    ({"PAYMENTS_ENABLED": "false"}, None),
    (BASE_ENV, None),
    ({**BASE_ENV, "STRIPE_SECRET_KEY": ""}, "exige STRIPE_SECRET_KEY"),
    ({**BASE_ENV, "STRIPE_SECRET_KEY": "pk_test_x"}, "formato"),
    ({**BASE_ENV, "STRIPE_WEBHOOK_SECRET": "abc"}, "whsec_"),
    ({**BASE_ENV, "STRIPE_PRICE_PRO_M": ""}, "STRIPE_PRICE_PRO_M"),
    ({**BASE_ENV, "STRIPE_PRICE_AVULSO": "prod_123"}, "price_"),
    ({**BASE_ENV, "STUDIO_ENV": "production"}, "teste"),
    ({**BASE_ENV, "STRIPE_SECRET_KEY": "sk_live_x"}, "STUDIO_ENV=production"),
    ({**BASE_ENV, "STRIPE_PUBLISHABLE_KEY": "pk_live_x"}, "mesmo modo"),
    ({**BASE_ENV, "TOPUP_MIN_CREDITS": "2000"}, "TOPUP"),
])
def test_config_error(env, err):
    got = stripe_client.config_error(env)
    assert (got is None) if err is None else (err in got)


def test_secret_key_never_reaches_logs_or_errors(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", KEY)
    assert KEY not in str(StripeError(f"falhou com {KEY}"))


def test_signature_helpers():
    body = b'{"id":"evt_1"}'
    h = stripe_client.sign(body, SECRET, t=1_800_000_000)
    assert stripe_client.verify_signature(body, h, SECRET, now=1_800_000_100)
    assert not stripe_client.verify_signature(body + b" ", h, SECRET, now=1_800_000_100)
    assert not stripe_client.verify_signature(body, h, SECRET, now=1_800_000_400)        # fora da tolerância
    two = h + ",v1=" + "0" * 64                                                           # rotação: aceita qualquer v1
    assert stripe_client.verify_signature(body, two, SECRET, now=1_800_000_000)


def test_form_encoding_matches_stripe():
    got = stripe_client.encode({"mode": "payment", "line_items": [{"price": "price_1", "quantity": 3}],
                                "metadata": {"a": "b"}, "x": None, "flag": True})
    assert got == [("mode", "payment"), ("line_items[0][price]", "price_1"), ("line_items[0][quantity]", "3"),
                   ("metadata[a]", "b"), ("flag", "true")]


def test_real_client_uses_api_url_basic_auth_and_pinned_version():
    import httpx
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"})
    cfg = stripe_client.config({"STRIPE_SECRET_KEY": KEY})
    c = stripe_client.StripeClient(cfg, transport=httpx.MockTransport(handler))
    c.create_checkout_session({"mode": "payment", "line_items": [{"price": "price_1", "quantity": 2}]}, idempotency_key="k1")
    r = seen[0]
    assert str(r.url) == "https://api.stripe.com/v1/checkout/sessions"
    assert r.headers["Stripe-Version"] == stripe_client.DEFAULT_API_VERSION and r.headers["Idempotency-Key"] == "k1"
    assert r.headers["Authorization"].startswith("Basic ") and b"line_items%5B0%5D%5Bquantity%5D=2" in r.content


def test_real_client_error_is_typed_and_has_no_key():
    import httpx
    c = stripe_client.StripeClient(stripe_client.config({"STRIPE_SECRET_KEY": KEY}),
                                   transport=httpx.MockTransport(lambda req: httpx.Response(402, json={"error": {"message": "Your card was declined", "code": "card_declined"}})))
    with pytest.raises(StripeError) as e:
        c.get_invoice("in_1")
    assert e.value.status == 402 and e.value.code == "card_declined" and KEY not in str(e.value)
