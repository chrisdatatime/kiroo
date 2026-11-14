"""Compra de créditos pelo Asaas (SANDBOX, tudo com um Asaas falso: nenhuma rede real).

Cobre: Pix pago, cartão confirmado, webhook duplicado, fora de ordem, token inválido, valor/cliente divergente,
estorno, chargeback com saldo negativo (bloqueio de produção), limites de cartão em conta nova, avulso fora do
incremento/mínimo/máximo, preço fixo do vídeo (20 créditos), reconciliação, métricas, CLI e configuração.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from studio import asaas, budget, catalog, payments
from studio.config import load_settings
from studio.credits import Ledger
from studio.db import Database, now
from studio.web.server import WEBHOOK_PATH, App

from .conftest import login_app

TOKEN = "whk-sandbox-token-ficticio-0123456789abcdef"
KEY = "$aact_hmlg_FICTICIA_nao_use_0000000000"
CPF = "529.982.247-25"
HOST = {"Host": "127.0.0.1:8765"}


class FakeAsaas:
    """Asaas falso: guarda clientes e cobranças em memória e deixa o teste mudar o status "do lado do Asaas"."""

    def __init__(self):
        self.customers: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.fail_create = False

    def find_customer(self, ext):
        self.calls.append(("find_customer", ext))
        return next((c for c in self.customers.values() if c["externalReference"] == ext), None)

    def create_customer(self, *, name, cpf_cnpj, email, external_reference):
        self.calls.append(("create_customer", cpf_cnpj))
        cid = f"cus_{len(self.customers) + 1:06d}"
        self.customers[cid] = {"id": cid, "name": name, "cpfCnpj": cpf_cnpj, "externalReference": external_reference}
        return self.customers[cid]

    def create_payment(self, *, customer, billing_type, value_cents, due_date, description, external_reference,
                       success_url=None):
        if self.fail_create:
            raise asaas.AsaasError("Asaas indisponível", 503)
        self.calls.append(("create_payment", billing_type, value_cents, success_url))
        pid = f"pay_{len(self.payments) + 1:012d}"
        self.payments[pid] = {"object": "payment", "id": pid, "customer": customer, "billingType": billing_type,
                              "value": value_cents / 100, "status": "PENDING", "dueDate": due_date,
                              "externalReference": external_reference, "deleted": False,
                              "invoiceUrl": f"https://sandbox.asaas.com/i/{pid}"}
        return dict(self.payments[pid])

    def get_payment(self, aid):
        self.calls.append(("get_payment", aid))
        return dict(self.payments[aid])

    def find_payment(self, ext):
        return next((dict(p) for p in self.payments.values() if p["externalReference"] == ext), None)

    def pix_qr(self, aid):
        return {"encodedImage": "iVBORw0KGgo=", "payload": f"00020126PIX{aid}", "expirationDate": "2026-11-15 23:59:59"}

    def set(self, aid, **kw):
        self.payments[aid].update(kw)


@pytest.fixture
def fake(monkeypatch):
    f = FakeAsaas()
    monkeypatch.setattr(payments, "make_client", lambda cfg=None: f)
    return f


@pytest.fixture
def pay_env(monkeypatch):
    monkeypatch.setenv("PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("ASAAS_ENV", "sandbox")
    monkeypatch.setenv("ASAAS_API_KEY", KEY)
    monkeypatch.setenv("ASAAS_WEBHOOK_TOKEN", TOKEN)


@pytest.fixture
def app(settings, tmp_path, pay_env, fake):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    a = App(8765, settings_loader=loader, sim_pacing=False)
    a.payments_sync = True
    login_app(a, {}, email="admin@example.com")          # o primeiro vira administrador (conta isenta)
    login_app(a, HOST, email="cliente@example.com")       # o cliente que compra
    return a


def post(app, path, body):
    return app.handle("POST", path, {**HOST, "X-Studio-Token": app.token, "User-Agent": "Mozilla/5.0 teste"},
                      json.dumps(body).encode(), peer="203.0.113.7")


def get(app, path):
    return app.handle("GET", path, {**HOST}, b"")


def hook(app, event_id, event, asaas_id, token=TOKEN, **payment):
    body = {"id": event_id, "event": event, "dateCreated": "2026-11-14 10:00:00",
            "payment": {"object": "payment", "id": asaas_id, **payment}}
    h = {"Host": HOST["Host"]}
    if token is not None:
        h["asaas-access-token"] = token
    return app.handle("POST", WEBHOOK_PATH, h, json.dumps(body).encode())


def db_of(app):
    return Database(app.settings().db_path)


def wid_of(app):
    return json.loads(get(app, "/api/me").body)["workspace"]["id"]


def balance(app):
    db = db_of(app)
    try:
        return Ledger(db).balance(wid_of(app))
    finally:
        db.close()


def buy(app, **body):
    r = post(app, "/api/payments/checkout", {"document": CPF, **body})
    assert r.status == 200, r.body
    return json.loads(r.body)


def asaas_id(app, kpay):
    db = db_of(app)
    try:
        return payments.get(db, kpay)["asaas_payment_id"]
    finally:
        db.close()


# ------------------------------------------------------------------ preço fixo do vídeo
def test_video_costs_fixed_20_credits_and_usd_estimate_stays_separate(settings):
    est = budget.estimate_workflow(settings)
    assert est["cc"] == 2000 == catalog.video_price_cc()                      # 20 créditos, não a conversão do custo
    assert est["usd"] == budget.workflow_cost()[0] == 0.6                     # reserva interna em US$ continua (US$ 0,60)


def test_catalog_public_view_savings_and_videos():
    v = catalog.public_view()
    by = {p["code"]: p for p in v["packages"]}
    assert (by["inicial"]["credits"], by["inicial"]["price_cents"], by["inicial"]["videos"]) == (200, 7990, 10)
    assert (by["pro"]["credits"], by["pro"]["price_cents"], by["pro"]["highlight"]) == (600, 19990, True)
    assert (by["escala"]["credits"], by["escala"]["price_cents"]) == (2000, 54990)
    assert [by[c]["savings_pct"] for c in ("inicial", "pro", "escala")] == [20, 33, 45]
    assert v["custom"] == {"unit_price_cents": 50, "min_credits": 40, "step_credits": 20, "max_credits": 1000,
                           "shortcuts": [40, 100, 200], "hint_from_credits": 140, "hint_package": "inicial"}


@pytest.mark.parametrize("credits,ok", [(40, True), (60, True), (1000, True), (20, False), (30, False), (50, False),
                                        (1020, False), ("40", False), (40.0, False), (True, False), (None, False)])
def test_custom_amount_min_step_max(credits, ok):
    if ok:
        assert catalog.quote(None, credits)["amount_cents"] == credits * 50
    else:
        with pytest.raises(catalog.CatalogError):
            catalog.quote(None, credits)


# ------------------------------------------------------------------ Pix
def test_pix_paid_credits_once_with_ledger_linked_to_payment(app, fake):
    out = buy(app, method="pix", package="pro")
    assert out["payment"]["status"] == "pending" and out["payment"]["credits"] == 600
    assert out["pix"]["payload"].startswith("000201") and out["pix"]["image"]
    kpay = out["payment"]["id"]
    aid = asaas_id(app, kpay)
    assert fake.payments[aid]["value"] == 199.90 and fake.payments[aid]["billingType"] == "PIX"
    assert fake.payments[aid]["externalReference"] == kpay
    # o webhook chega, mas o Asaas ainda não marcou como recebido: nada credita (nunca confia no payload)
    assert hook(app, "evt_1", "PAYMENT_RECEIVED", aid, status="RECEIVED", value=199.90).status == 200
    assert balance(app) == 0
    fake.set(aid, status="RECEIVED")
    assert hook(app, "evt_2", "PAYMENT_RECEIVED", aid).status == 200
    assert balance(app) == 60000
    st = json.loads(get(app, f"/api/payments/{kpay}").body)
    assert st["status"] == "paid" and st["balance"] == "600"
    db = db_of(app)
    try:
        rows = db.conn.execute("SELECT kind, amount_cc, payment_id FROM credit_entries WHERE payment_id=?", (kpay,)).fetchall()
        prow = payments.get(db, kpay)
        ev = db.conn.execute("SELECT raw FROM payment_events WHERE asaas_event_id='evt_2'").fetchone()[0]
    finally:
        db.close()
    assert [tuple(r) for r in rows] == [("purchase", 60000, kpay)]
    assert prow["ip"] == "203.0.113.7" and prow["user_agent"] == "Mozilla/5.0 teste" and prow["paid_at"]
    assert "52998224725" not in ev and "cliente" not in ev     # evento guardado sem dado sensível


def test_pix_confirmed_is_not_paid_yet(app, fake):
    kpay = buy(app, method="pix", package="inicial")["payment"]["id"]
    aid = asaas_id(app, kpay)
    fake.set(aid, status="CONFIRMED")          # Pix CONFIRMED pode ser bloqueio cautelar temporário
    hook(app, "evt_c", "PAYMENT_CONFIRMED", aid)
    assert balance(app) == 0


def test_first_purchase_requires_valid_document_and_customer_is_reused(app, fake):
    r = post(app, "/api/payments/checkout", {"method": "pix", "package": "pro"})
    assert r.status == 400 and json.loads(r.body)["code"] == "document_required"
    r = post(app, "/api/payments/checkout", {"method": "pix", "package": "pro", "document": "111.111.111-11"})
    assert r.status == 400 and json.loads(r.body)["code"] == "invalid_document"
    buy(app, method="pix", package="pro")
    cat = json.loads(get(app, "/api/payments/catalog").body)
    assert cat["needs_document"] is False
    r = post(app, "/api/payments/checkout", {"method": "pix", "package": "inicial"})   # segunda compra: sem documento
    assert r.status == 200
    assert [c for c in fake.calls if c[0] == "create_customer"] == [("create_customer", "52998224725")]


def test_document_saved_in_my_account_is_reused_and_never_asked_again(app, fake):
    assert json.loads(get(app, "/api/payments/catalog").body)["needs_document"] is True
    assert post(app, "/api/account/tax-doc", {"document": CPF}).status == 200      # Minha conta → CPF/CNPJ
    assert json.loads(get(app, "/api/payments/catalog").body)["needs_document"] is False
    r = post(app, "/api/payments/checkout", {"method": "pix", "package": "pro"})      # sem documento no pedido
    assert r.status == 200
    assert [c for c in fake.calls if c[0] == "create_customer"] == [("create_customer", "52998224725")]


def test_document_never_reaches_logs_or_error_text(app, fake, caplog):
    import logging
    post(app, "/api/account/tax-doc", {"document": CPF})
    with caplog.at_level(logging.DEBUG):
        post(app, "/api/payments/checkout", {"method": "pix", "package": "pro"})
        post(app, "/api/payments/checkout", {"method": "pix", "package": "pro", "document": "111.111.111-11"})
    text = " ".join(r.getMessage() + " " + str(r.__dict__) for r in caplog.records)
    assert "52998224725" not in text and CPF not in text
    assert asaas._scrub_doc("CPF 529.982.247-25 e 11222333000181 inválidos") == "CPF *** e *** inválidos"


@pytest.mark.parametrize("doc,ok", [("529.982.247-25", True), ("11.222.333/0001-81", True), ("12.ABC.345/01DE-35", True),
                                    ("123.456.789-00", False), ("00000000000", False), ("11.222.333/0001-80", False)])
def test_document_validation(doc, ok):
    if ok:
        assert payments.normalize_document(doc)
    else:
        with pytest.raises(payments.PaymentRefused):
            payments.normalize_document(doc)


def test_client_never_sends_the_price(app, fake):
    out = buy(app, method="pix", credits=40, amount_cents=1, price_cents=1, value=0.01)
    assert out["payment"]["amount_cents"] == 2000 and out["payment"]["package_code"] == "avulso"
    assert fake.payments[asaas_id(app, out["payment"]["id"])]["value"] == 20.00


@pytest.mark.parametrize("credits", [20, 30, 50, 1020])
def test_custom_out_of_rules_is_refused_by_the_api(app, credits):
    r = post(app, "/api/payments/checkout", {"method": "pix", "credits": credits, "document": CPF})
    assert r.status == 400 and json.loads(r.body)["code"] == "invalid_quote"


# ------------------------------------------------------------------ cartão
def test_card_confirmed_credits_and_uses_hosted_invoice(app, fake):
    out = buy(app, method="card", package="pro")
    assert out["redirect_url"].startswith("https://sandbox.asaas.com/i/") and "pix" not in out
    aid = asaas_id(app, out["payment"]["id"])
    assert fake.payments[aid]["billingType"] == "CREDIT_CARD"
    fake.set(aid, status="CONFIRMED")
    hook(app, "evt_cc1", "PAYMENT_CONFIRMED", aid)
    assert balance(app) == 60000
    fake.set(aid, status="RECEIVED")            # ~32 dias depois: RECEIVED do mesmo pagamento não credita de novo
    hook(app, "evt_cc2", "PAYMENT_RECEIVED", aid)
    assert balance(app) == 60000


def test_card_new_account_one_per_day_and_max_pro(app, fake):
    r = post(app, "/api/payments/checkout", {"method": "card", "package": "escala", "document": CPF})
    assert r.status == 400 and json.loads(r.body)["code"] == "card_new_max"
    buy(app, method="card", package="inicial")
    r = post(app, "/api/payments/checkout", {"method": "card", "package": "pro"})
    assert r.status == 400 and json.loads(r.body)["code"] == "card_new_daily"
    assert post(app, "/api/payments/checkout", {"method": "pix", "package": "escala"}).status == 200   # Pix segue livre


def test_card_same_open_purchase_reuses_invoice(app, fake):
    a = buy(app, method="card", package="inicial")
    b = buy(app, method="card", package="inicial")
    assert a["payment"]["id"] == b["payment"]["id"] and a["redirect_url"] == b["redirect_url"]
    assert len(fake.payments) == 1


def _make_established(app):
    db = db_of(app)
    try:
        wid = wid_of(app)
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
        db.conn.execute("UPDATE workspaces SET created_at=? WHERE id=?", (old, wid))
        db.conn.execute("INSERT INTO payments(id, account_id, method, package_code, credits, amount_cents, status, "
                        "created_at, paid_at) VALUES ('kpay_000000old0',?, 'pix','inicial',200,7990,'paid',?,?)",
                        (wid, old, old))
    finally:
        db.close()


def test_card_daily_limit_600_reais(app, fake):
    _make_established(app)
    buy(app, method="card", package="escala")                         # R$ 549,90: conta antiga, cabe no limite
    r = post(app, "/api/payments/checkout", {"method": "card", "package": "inicial"})   # +79,90 > 600
    assert r.status == 400 and json.loads(r.body)["code"] == "card_daily_limit"
    r = post(app, "/api/payments/checkout", {"method": "card", "credits": 100})         # +50,00 = 599,90: cabe
    assert r.status == 200


def test_card_limit_only_counts_last_24h(app, fake):
    out = buy(app, method="card", package="inicial")
    db = db_of(app)
    try:
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
        db.conn.execute("UPDATE payments SET created_at=? WHERE id=?", (old, out["payment"]["id"]))
    finally:
        db.close()
    assert post(app, "/api/payments/checkout", {"method": "card", "package": "pro"}).status == 200


# ------------------------------------------------------------------ webhook: segurança e idempotência
def test_webhook_token_invalid_or_missing_is_401_and_stores_nothing(app, fake):
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    aid = asaas_id(app, kpay)
    fake.set(aid, status="RECEIVED")
    assert hook(app, "evt_x", "PAYMENT_RECEIVED", aid, token="token-errado-0000000000000000000000000").status == 401
    assert hook(app, "evt_y", "PAYMENT_RECEIVED", aid, token=None).status == 401
    assert hook(app, "evt_z", "PAYMENT_RECEIVED", aid, token=TOKEN[:-1]).status == 401
    db = db_of(app)
    try:
        assert db.conn.execute("SELECT COUNT(*) FROM payment_events").fetchone()[0] == 0
    finally:
        db.close()
    assert balance(app) == 0


def test_webhook_off_when_payments_disabled(app, monkeypatch):
    monkeypatch.setenv("PAYMENTS_ENABLED", "false")
    assert hook(app, "evt_off", "PAYMENT_RECEIVED", "pay_1").status == 404
    assert get(app, "/api/payments/catalog").status == 404


def test_duplicate_webhook_credits_once(app, fake):
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    aid = asaas_id(app, kpay)
    fake.set(aid, status="RECEIVED")
    for _ in range(3):
        r = hook(app, "evt_dup", "PAYMENT_RECEIVED", aid)
        assert r.status == 200
    assert json.loads(r.body).get("duplicate") is True
    hook(app, "evt_dup_2", "PAYMENT_RECEIVED", aid)        # outro evento, mesmo pagamento: também não credita de novo
    assert balance(app) == 60000
    gets = [c for c in fake.calls if c == ("get_payment", aid)]
    assert len(gets) == 2                                   # evento repetido nem chega a consultar o Asaas


def test_out_of_order_events_follow_current_api_state(app, fake):
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    aid = asaas_id(app, kpay)
    fake.set(aid, status="REFUNDED")                        # já foi pago e estornado quando os avisos chegam
    hook(app, "evt_ref", "PAYMENT_REFUNDED", aid)           # o estorno chega primeiro
    hook(app, "evt_rec", "PAYMENT_RECEIVED", aid)           # o "recebido" velho chega depois
    assert balance(app) == 0
    db = db_of(app)
    try:
        assert payments.get(db, kpay)["status"] == "refunded"
        assert db.conn.execute("SELECT COUNT(*) FROM credit_entries WHERE payment_id=?", (kpay,)).fetchone()[0] == 0
    finally:
        db.close()


def test_divergent_value_or_customer_never_credits(app, fake):
    k1 = buy(app, method="pix", package="pro")["payment"]["id"]
    a1 = asaas_id(app, k1)
    fake.set(a1, status="RECEIVED", value=1.00)
    hook(app, "evt_v", "PAYMENT_RECEIVED", a1, value=199.90)   # payload diz o valor certo; a API diz outro
    k2 = buy(app, method="pix", package="inicial")["payment"]["id"]
    a2 = asaas_id(app, k2)
    fake.set(a2, status="RECEIVED", customer="cus_999999")
    hook(app, "evt_c2", "PAYMENT_RECEIVED", a2)
    assert balance(app) == 0
    db = db_of(app)
    try:
        assert payments.get(db, k1)["status"] == payments.get(db, k2)["status"] == "mismatch"
        assert "valor divergente" in payments.get(db, k1)["note"]
    finally:
        db.close()


def test_unknown_payment_and_irrelevant_events_are_ignored_with_200(app, fake):
    assert hook(app, "evt_u", "PAYMENT_RECEIVED", "pay_nao_e_nosso").status == 200
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    assert hook(app, "evt_v2", "PAYMENT_BANK_SLIP_VIEWED", asaas_id(app, kpay)).status == 200
    db = db_of(app)
    try:
        out = dict(db.conn.execute("SELECT asaas_event_id, outcome FROM payment_events").fetchall())
    finally:
        db.close()
    assert out == {"evt_u": "unknown_payment", "evt_v2": "ignored"}


# ------------------------------------------------------------------ estorno e chargeback
def test_refund_debits_the_credits(app, fake):
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    aid = asaas_id(app, kpay)
    fake.set(aid, status="RECEIVED")
    hook(app, "e1", "PAYMENT_RECEIVED", aid)
    fake.set(aid, status="REFUNDED")
    hook(app, "e2", "PAYMENT_REFUNDED", aid)
    hook(app, "e3", "PAYMENT_REFUNDED", aid)
    assert balance(app) == 0
    st = json.loads(get(app, "/api/credits").body)["statement"]
    assert {e["label"] for e in st} >= {"Compra", "Estorno de compra"}


def test_chargeback_with_negative_balance_blocks_new_productions(app, fake):
    kpay = buy(app, method="card", package="inicial")["payment"]["id"]
    aid = asaas_id(app, kpay)
    fake.set(aid, status="CONFIRMED")
    hook(app, "cb1", "PAYMENT_CONFIRMED", aid)
    assert balance(app) == 20000
    db = db_of(app)
    try:   # o cliente usou 150 créditos antes da contestação
        Ledger(db)._insert(workspace_id=wid_of(app), kind="debit", amount_cc=-15000, created_at=now(), ext_ref="uso-teste")
    finally:
        db.close()
    fake.set(aid, status="CHARGEBACK_REQUESTED")
    hook(app, "cb2", "PAYMENT_CHARGEBACK_REQUESTED", aid)
    assert balance(app) == -15000
    r = post(app, "/api/productions", {"name": "Copo", "files": []})
    d = json.loads(r.body)
    assert r.status == 402 and d["negative_balance"] is True and "negativo" in d["error"] and "regularizar" in d["error"]
    r = post(app, "/api/payments/checkout", {"method": "card", "package": "inicial"})
    assert r.status == 400 and json.loads(r.body)["code"] == "card_disputed"
    # regulariza por Pix: o saldo volta a positivo e a produção deixa de ser bloqueada por saldo negativo
    k2 = buy(app, method="pix", package="inicial")["payment"]["id"]
    a2 = asaas_id(app, k2)
    fake.set(a2, status="RECEIVED")
    hook(app, "cb3", "PAYMENT_RECEIVED", a2)
    assert balance(app) == 5000
    r = post(app, "/api/productions", {"name": "Copo", "files": []})
    assert not json.loads(r.body).get("negative_balance")


def test_dispute_won_restores_credits_once(app, fake):
    kpay = buy(app, method="card", package="inicial")["payment"]["id"]
    aid = asaas_id(app, kpay)
    for i, st in enumerate(["CONFIRMED", "CHARGEBACK_DISPUTE", "AWAITING_CHARGEBACK_REVERSAL", "RECEIVED", "RECEIVED"]):
        fake.set(aid, status=st)
        hook(app, f"d{i}", "PAYMENT_UPDATED", aid)
    assert balance(app) == 20000


# ------------------------------------------------------------------ reconciliação, status e falhas
def test_reconcile_recovers_lost_webhook(app, fake):
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    fake.set(asaas_id(app, kpay), status="RECEIVED")     # pago, mas o webhook nunca chegou
    db = db_of(app)
    try:
        out = payments.reconcile(db, fake)
        again = payments.reconcile(db, fake)
    finally:
        db.close()
    assert [r["delta_cc"] for r in out if r.get("payment_id") == kpay] == [60000]
    assert again == []                                   # nada mais pendente
    assert balance(app) == 60000


def test_poll_syncs_pending_payment_after_interval(app, fake):
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    fake.set(asaas_id(app, kpay), status="RECEIVED")
    assert json.loads(get(app, f"/api/payments/{kpay}").body)["status"] == "pending"   # ainda dentro dos 10 s
    db = db_of(app)
    try:
        db.conn.execute("UPDATE payments SET synced_at=? WHERE id=?", ("2026-01-01T00:00:00+00:00", kpay))
    finally:
        db.close()
    assert json.loads(get(app, f"/api/payments/{kpay}").body)["status"] == "paid"
    assert balance(app) == 60000


def test_payment_status_is_private_to_its_account(app, fake):
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    login_app(app, HOST, email="outra@example.com")
    assert get(app, f"/api/payments/{kpay}").status == 404


def test_asaas_down_on_checkout_charges_nothing(app, fake):
    fake.fail_create = True
    r = post(app, "/api/payments/checkout", {"method": "pix", "package": "pro", "document": CPF})
    assert r.status == 502 and "Nada foi cobrado" in json.loads(r.body)["error"]
    db = db_of(app)
    try:
        assert db.conn.execute("SELECT status FROM payments").fetchone()[0] == "failed"
    finally:
        db.close()


def test_catalog_endpoint_and_topup_online(app):
    d = json.loads(get(app, "/api/payments/catalog").body)
    assert d["needs_document"] is True and d["card"]["new_account"] is True and len(d["packages"]) == 3
    t = json.loads(get(app, "/api/credits").body)["topup"]
    assert t["online"] is True and t["provider"] == "asaas"


def test_exempt_account_does_not_buy(app):
    login_app(app, HOST, email="admin@example.com")
    r = post(app, "/api/payments/checkout", {"method": "pix", "package": "pro", "document": CPF})
    assert r.status == 400


# ------------------------------------------------------------------ métricas e CLI
def test_month_metrics_revenue_by_method_and_credits(app, fake):
    for method, pkg, st in (("pix", "pro", "RECEIVED"), ("card", "inicial", "CONFIRMED")):
        kpay = buy(app, method=method, package=pkg)["payment"]["id"]
        fake.set(asaas_id(app, kpay), status=st)
        hook(app, "m-" + kpay, "PAYMENT_UPDATED", asaas_id(app, kpay))
    db = db_of(app)
    try:
        Ledger(db)._insert(workspace_id=wid_of(app), kind="debit", amount_cc=-4000, created_at=now(), ext_ref="uso-m")
        m = payments.month_metrics(db)
        from studio.metrics import format_text, internal_metrics
        text = format_text(internal_metrics(db, 30))
    finally:
        db.close()
    assert m["gross_revenue_cents"] == 19990 + 7990
    assert m["by_method"] == {"pix": {"purchases": 1, "revenue_cents": 19990}, "card": {"purchases": 1, "revenue_cents": 7990}}
    assert m["credits_sold"] == 800 and m["credits_consumed"] == 40
    assert "receita bruta: R$ 279,80" in text and "créditos vendidos: 800" in text


def test_cli_payments_list_and_reconcile(app, fake, monkeypatch, capsys):
    from studio import cli
    kpay = buy(app, method="pix", package="pro")["payment"]["id"]
    fake.set(asaas_id(app, kpay), status="RECEIVED")
    monkeypatch.setenv("STUDIO_DATA_DIR", str(app.settings().data_dir))
    assert cli.main(["payments", "list", "--email", "cliente@example.com"]) == 0
    assert kpay in capsys.readouterr().out
    assert cli.main(["payments", "reconcile"]) == 0
    assert "com mudança no saldo" in capsys.readouterr().out
    assert balance(app) == 60000


# ------------------------------------------------------------------ configuração
@pytest.mark.parametrize("env,err", [
    ({}, None),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "sandbox", "ASAAS_API_KEY": KEY, "ASAAS_WEBHOOK_TOKEN": TOKEN}, None),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "production", "ASAAS_API_KEY": KEY, "ASAAS_WEBHOOK_TOKEN": TOKEN,
      "STUDIO_ENV": "production"}, "parece ser de sandbox"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "sandbox", "ASAAS_API_KEY": "$aact_prod_FICTICIA", "ASAAS_WEBHOOK_TOKEN": TOKEN},
     "parece ser de production"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "sandbox", "ASAAS_API_KEY": "chave-sem-prefixo", "ASAAS_WEBHOOK_TOKEN": TOKEN},
     "formato"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "sandbox", "ASAAS_API_KEY": KEY}, "ASAAS_WEBHOOK_TOKEN"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "sandbox", "ASAAS_WEBHOOK_TOKEN": TOKEN}, "ASAAS_API_KEY"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "sandbox", "ASAAS_API_KEY": KEY, "ASAAS_WEBHOOK_TOKEN": "curto"}, "32 a 255"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "homolog", "ASAAS_API_KEY": KEY, "ASAAS_WEBHOOK_TOKEN": TOKEN}, "inválido"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "sandbox", "ASAAS_API_KEY": KEY, "ASAAS_WEBHOOK_TOKEN": TOKEN,
      "STUDIO_ENV": "production"}, "creditariam"),
    ({"PAYMENTS_ENABLED": "true", "ASAAS_ENV": "production", "ASAAS_API_KEY": "$aact_prod_FICTICIA_0000",
      "ASAAS_WEBHOOK_TOKEN": TOKEN, "STUDIO_ENV": "staging"}, "só com STUDIO_ENV=production"),
])
def test_config_error(env, err):
    got = asaas.config_error(env)
    assert (got is None) if err is None else (err in got)


def test_asaas_secrets_are_redacted(monkeypatch, pay_env):
    from studio.config import secret_values
    vals = secret_values()
    assert KEY in vals and TOKEN in vals


def test_real_client_uses_sandbox_url_and_access_token_header():
    import httpx
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path.endswith("/pixQrCode"):
            return httpx.Response(200, json={"encodedImage": "x", "payload": "y"})
        if req.method == "POST":
            return httpx.Response(200, json={"id": "pay_1", "status": "PENDING", **json.loads(req.content)})
        return httpx.Response(400, json={"errors": [{"code": "invalid", "description": "cobrança inexistente"}]})

    c = asaas.AsaasClient(asaas.AsaasConfig(True, "sandbox", KEY, TOKEN), transport=httpx.MockTransport(handler))
    p = c.create_payment(customer="cus_1", billing_type="PIX", value_cents=19990, due_date="2026-11-15",
                         description="Kiroo", external_reference="kpay_1", success_url="https://kiroo.app/?compra=kpay_1")
    assert p["value"] == 199.9 and p["callback"] == {"successUrl": "https://kiroo.app/?compra=kpay_1", "autoRedirect": True}
    c.pix_qr("pay_1")
    with pytest.raises(asaas.AsaasError, match="cobrança inexistente") as e:
        c.get_payment("pay_x")
    assert e.value.status == 400
    assert str(seen[0].url) == "https://api-sandbox.asaas.com/v3/payments"
    assert seen[0].headers["access_token"] == KEY and seen[0].headers["User-Agent"] == "kiroo-studio"
    assert str(seen[1].url) == "https://api-sandbox.asaas.com/v3/payments/pay_1/pixQrCode"
