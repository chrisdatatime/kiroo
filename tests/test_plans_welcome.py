"""Tela "Comprar créditos" v2: plano por compra paga (e estorno), fila prioritária do motor fal.ai, WhatsApp, acesso
antecipado a estilos, saldo exibido inteiro e bônus de boas-vindas (uma vez, e-mail confirmado, dispositivo, IP, teto)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from studio import catalog, fal_contract, payments, plans, welcome
from studio.accounts import Accounts
from studio.credits import Ledger, fmt_balance
from studio.db import Database, new_id, now

from .conftest import requires_ffmpeg
from .test_accounts import BASE, CLIENT, User, app  # noqa: F401 — fixture `app` reaproveitada

DEV_A, DEV_B, DEV_C = "devAAAAAAAAAAAAAAAAA", "devBBBBBBBBBBBBBBBBB", "devCCCCCCCCCCCCCCCCC"


@pytest.fixture
def db(settings):
    d = Database(settings.db_path)
    yield d
    d.close()


def user(db, email, verified=True):
    uid, wid = Accounts(db).create_user(email, "senha-forte-123", verified=verified)
    return uid, wid


def pay(db, wid, code, status="paid", method="pix"):
    """Compra já criada no Asaas (como payments.checkout deixaria), no estado pedido."""
    q = catalog.quote(code) if code != "avulso" else catalog.quote(None, 100)
    pid = new_id("kpay")
    db.conn.execute("INSERT INTO payments(id, account_id, asaas_payment_id, asaas_customer_id, method, package_code, credits, "
                    "amount_cents, status, created_at, paid_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, wid, "pay_" + pid, "cus_1", method, q["package_code"], q["credits"], q["amount_cents"], status,
                     now(), now() if status == "paid" else None))
    return pid


def remote(db, pid, status):
    row = payments.get(db, pid)
    return payments.apply_remote(db, row, {"id": row["asaas_payment_id"], "customer": "cus_1",
                                           "value": row["amount_cents"] / 100, "billingType": "PIX", "status": status,
                                           "externalReference": pid}, source="teste")


# ================================================================= saldo inteiro (só a exibição)
def test_balance_is_shown_as_an_integer_rounded_down_and_the_ledger_keeps_decimals(db):
    assert fmt_balance(1999) == "19" and fmt_balance(2000) == "20" and fmt_balance(0) == "0"
    assert fmt_balance(-40) == "−1" and fmt_balance(200_000) == "2.000"
    _, wid = user(db, "saldo@x.com")
    Ledger(db).add(wid, 1999, note="teste")
    s = Ledger(db).summary(wid)
    assert s["balance"] == "19" and s["balance_cc"] == 1999 and s["balance_exact"] == "19,99"


# ================================================================= plano
def test_plan_is_the_biggest_paid_package_and_avulso_or_bonus_never_count(db):
    _, wid = user(db, "plano@x.com")
    assert plans.plan_of(db, wid) == "free" and not plans.has_paid_purchase(db, wid)
    pay(db, wid, "avulso")
    assert plans.plan_of(db, wid) == "free" and plans.has_paid_purchase(db, wid)   # avulso esconde o Free, não dá plano
    pay(db, wid, "inicial")
    pay(db, wid, "pro", status="pending")                                             # não pago: não conta
    assert plans.plan_of(db, wid) == "inicial"
    pay(db, wid, "escala")
    pay(db, wid, "pro")
    assert plans.plan_of(db, wid) == "escala"


def test_refund_or_chargeback_of_the_plan_package_recalculates_the_plan(db):
    _, wid = user(db, "estorno@x.com")
    pro = pay(db, wid, "pro", status="pending")
    esc = pay(db, wid, "escala", status="pending")
    assert remote(db, pro, "RECEIVED")["status"] == "paid"
    assert remote(db, esc, "RECEIVED")["status"] == "paid"
    assert plans.plan_of(db, wid) == "escala"
    assert remote(db, esc, "REFUNDED")["status"] == "refunded"
    assert plans.plan_of(db, wid) == "pro"
    assert remote(db, pro, "CHARGEBACK_REQUESTED")["status"] == "chargeback"
    assert plans.plan_of(db, wid) == "free" and not plans.has_paid_purchase(db, wid)


def test_whatsapp_only_for_pro_and_escala_and_only_with_the_env(db, monkeypatch):
    _, wid = user(db, "zap@x.com")
    monkeypatch.setenv("STUDIO_SUPPORT_WHATSAPP", "+55 (11) 98888-7777")
    assert plans.view(db, wid)["support"]["whatsapp"] is None                         # free: e-mail
    pay(db, wid, "inicial")
    assert plans.view(db, wid)["support"]["whatsapp"] is None
    pay(db, wid, "pro")
    v = plans.view(db, wid)
    assert v["plan"] == "pro" and v["priority_queue"] and v["support"]["whatsapp"] == "https://wa.me/5511988887777"
    monkeypatch.delenv("STUDIO_SUPPORT_WHATSAPP")
    assert plans.view(db, wid)["support"]["whatsapp"] is None                         # sem a variável, sem botão


def test_early_access_scene_only_shows_for_escala(monkeypatch):
    from studio.prompts import production as pp
    monkeypatch.setitem(pp.SCENES["dark_premium"], "early_access_plan", "escala")
    assert "dark_premium" not in pp.scenes_for_plan("free") and "dark_premium" not in pp.scenes_for_plan("pro")
    assert "dark_premium" in pp.scenes_for_plan("escala")
    assert {"home_light", "studio", "natural"} <= set(pp.scenes_for_plan("free"))      # os demais seguem liberados
    assert pp.scene_early_access("dark_premium") == "escala" and pp.scene_early_access("studio") is None


def test_no_scene_is_early_access_today():
    from studio.prompts import production as pp
    assert all(pp.scene_early_access(s) is None for s in pp.SCENES)
    assert pp.scenes_for_plan("free") == tuple(pp.SCENES)


# ================================================================= fila prioritária
def test_slot_queue_priority_first_then_arrival_and_never_over_the_cap():
    t = [0.0]
    q = plans.SlotQueue(clock=lambda: t[0])
    # teto cheio: ninguém entra, todos ficam registrados
    assert not q.admit("free1", level=0, arrival="2026-01-01T10:00:00", inflight=1, cap=1)
    assert not q.admit("pro1", level=1, arrival="2026-01-01T10:05:00", inflight=1, cap=1)
    assert not q.admit("pro0", level=1, arrival="2026-01-01T10:01:00", inflight=1, cap=1)
    assert q.order() == ["pro0", "pro1", "free1"]
    # vaga aberta: o free chegou primeiro, mas espera; o pro mais antigo entra
    assert not q.admit("free1", level=0, arrival="2026-01-01T10:00:00", inflight=0, cap=1)
    assert not q.admit("pro1", level=1, arrival="2026-01-01T10:05:00", inflight=0, cap=1)
    assert q.admit("pro0", level=1, arrival="2026-01-01T10:01:00", inflight=0, cap=1)
    assert q.order() == ["pro1", "free1"]
    # duas vagas: os dois primeiros da fila
    assert q.admit("free1", level=0, arrival="2026-01-01T10:00:00", inflight=0, cap=2)
    # quem parou de perguntar (pausou, caiu) sai da fila depois do ttl e não trava ninguém
    q.admit("ghost", level=1, arrival="2026-01-01T09:00:00", inflight=1, cap=1, ttl=30)
    t[0] = 100.0
    assert q.order() == []                                        # pro1 e ghost pararam de perguntar há 100 s


@requires_ffmpeg
def test_fal_queue_sends_pro_before_an_earlier_free_production(settings, tmp_path, photo_product):
    from studio.providers.simulated_fal import FalSimScript
    from .test_fal_flow import funded, new
    o, free_wid = funded(settings, tmp_path, fal_script=FalSimScript(polls_before_done=1), fal_max_inflight=1)
    acc = Accounts(o.db)
    _, pro_wid = acc.create_user("pro@example.com", "senha-forte-123")
    acc.set_workspace(pro_wid, allow_real=1, mode="real", monthly_cap_usd=100, credits_exempt=0)
    Ledger(o.db).add(pro_wid, 50_000, note="teste")
    pay(o.db, pro_wid, "pro")

    busy = new(o, photo_product, crid="busy-0001", wid=free_wid)
    o.run(busy, wait=False)
    assert o.fal_gen.submit_count == 1                                     # vaga ocupada
    early_free = new(o, photo_product, crid="free-0001", wid=free_wid)
    o.db.conn.execute("UPDATE productions SET created_at=? WHERE id=?",
                      ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds"), early_free))
    late_pro = new(o, photo_product, crid="pro-00001", wid=pro_wid)
    o.run(early_free, wait=False), o.run(late_pro, wait=False)
    assert o.fal_gen.submit_count == 1                                     # teto respeitado: os dois esperam
    o.run(busy, wait=True)                                                 # a execução termina e libera a vaga
    o.run(early_free, wait=False)
    assert o.db.attempts(early_free) == []                                 # chegou antes, mas o Pro passa na frente
    o.run(late_pro, wait=False)
    assert o.fal_gen.submit_count == 2 and len(o.db.attempts(late_pro)) == 1
    o.run(early_free, wait=False)
    assert o.db.attempts(early_free) == []                                 # teto 1: espera o Pro terminar
    o.run(late_pro, wait=True)
    o.run(early_free, wait=False)
    assert o.fal_gen.submit_count == 3                                     # depois sai, sem passar do teto


@pytest.fixture
def photo_product(tmp_path):
    from studio.models import ProductInput
    from studio.providers.simulated import placeholder_png
    p = tmp_path / "foto.png"
    p.write_bytes(placeholder_png("foto", 540, 960))
    return ProductInput.model_validate({"name": "", "references": [{"path": str(p), "role": "front"}]})


# ================================================================= bônus de boas-vindas
def test_email_normalization():
    n = welcome.normalize_email
    assert n("Fulano.Silva+loja@GMail.com") == "fulanosilva@gmail.com"
    assert n("f.u.l.a.n.o@googlemail.com") == "fulano@gmail.com"
    assert n(" Ana.B+x@Loja.com.br ") == "ana.b@loja.com.br"     # fora do gmail, pontos contam


def test_bonus_needs_a_confirmed_email_and_is_granted_once(db):
    uid, wid = user(db, "novo@x.com", verified=False)
    r = welcome.try_grant(db, user_id=uid, workspace_id=wid, device_id=DEV_A, ip="1.1.1.1")
    assert not r["granted"] and r["reason"] == "email_unverified"
    assert Ledger(db).balance(wid) == 0
    db.conn.execute("UPDATE users SET email_verified_at=? WHERE id=?", (now(), uid))
    r = welcome.try_grant(db, user_id=uid, workspace_id=wid, device_id=DEV_A, ip="1.1.1.1")
    assert r["granted"] and r["credits"] == 20
    assert r["message"] == "Seu primeiro vídeo é por nossa conta. 20 créditos já estão na sua conta."
    again = welcome.try_grant(db, user_id=uid, workspace_id=wid, device_id=DEV_B, ip="2.2.2.2")
    assert not again["granted"] and again["reason"] == "already"
    assert Ledger(db).balance(wid) == 2000
    kinds = [r["kind"] for r in db.conn.execute("SELECT kind FROM credit_entries WHERE workspace_id=?", (wid,))]
    assert kinds == ["welcome_bonus"]
    # não é compra: não dá plano, não esconde o Free, não entra na receita
    assert plans.plan_of(db, wid) == "free" and not plans.has_paid_purchase(db, wid)
    assert payments.month_metrics(db)["credits_sold"] == 0
    assert Ledger(db).statement(wid)[0]["label"] == "Bônus de boas-vindas"


def test_one_bonus_per_normalized_email(db):
    a, wa = user(db, "fulano.silva@gmail.com")
    b, wb = user(db, "fulanosilva+2@gmail.com")
    assert welcome.try_grant(db, user_id=a, workspace_id=wa, device_id=DEV_A, ip="1.1.1.1")["granted"]
    r = welcome.try_grant(db, user_id=b, workspace_id=wb, device_id=DEV_B, ip="2.2.2.2")
    assert not r["granted"] and r["reason"] == "email" and Ledger(db).balance(wb) == 0


def test_one_bonus_per_device_and_none_without_device(db):
    a, wa = user(db, "a@x.com")
    b, wb = user(db, "b@x.com")
    c, wc = user(db, "c@x.com")
    assert welcome.try_grant(db, user_id=a, workspace_id=wa, device_id=DEV_A, ip="1.1.1.1")["granted"]
    assert welcome.try_grant(db, user_id=b, workspace_id=wb, device_id=DEV_A, ip="2.2.2.2")["reason"] == "device"
    assert welcome.try_grant(db, user_id=c, workspace_id=wc, device_id=None, ip="3.3.3.3")["reason"] == "no_device"
    assert welcome.try_grant(db, user_id=c, workspace_id=wc, device_id="curto", ip="3.3.3.3")["reason"] == "already"


def test_at_most_two_bonuses_per_ip_in_24h(db):
    ids = [user(db, f"ip{i}@x.com") for i in range(4)]
    devs = [DEV_A, DEV_B, DEV_C, "devDDDDDDDDDDDDDDDDD"]
    t0 = datetime.now(timezone.utc)
    got = [welcome.try_grant(db, user_id=u, workspace_id=w, device_id=d, ip="9.9.9.9", at=t0)
           for (u, w), d in zip(ids[:3], devs[:3])]
    assert [g["granted"] for g in got] == [True, True, False] and got[2]["reason"] == "ip"
    later = welcome.try_grant(db, user_id=ids[3][0], workspace_id=ids[3][1], device_id=devs[3], ip="9.9.9.9",
                              at=t0 + timedelta(hours=25))
    assert later["granted"]                                       # a janela é de 24 h


def test_daily_cap_blocks_and_warns(db, monkeypatch, caplog):
    monkeypatch.setenv("STUDIO_WELCOME_DAILY_CAP", "1")
    a, wa = user(db, "cap1@x.com")
    b, wb = user(db, "cap2@x.com")
    assert welcome.try_grant(db, user_id=a, workspace_id=wa, device_id=DEV_A, ip="1.1.1.1")["granted"]
    with caplog.at_level(logging.WARNING, logger="studio.welcome"):
        r = welcome.try_grant(db, user_id=b, workspace_id=wb, device_id=DEV_B, ip="2.2.2.2")
    assert r["reason"] == "daily_cap" and any(getattr(x, "event", "") == "welcome_denied" for x in caplog.records)
    m = welcome.metrics(db)
    assert m["granted_today"] == 1 and m["cap_reached_today"] and m["denied_today"] == {"daily_cap": 1}


def test_welcome_credits_env_and_metrics_count_conversions(db, monkeypatch):
    monkeypatch.setenv("STUDIO_WELCOME_CREDITS", "40")
    a, wa = user(db, "conv@x.com")
    assert welcome.try_grant(db, user_id=a, workspace_id=wa, device_id=DEV_A, ip="1.1.1.1")["credits"] == 40
    assert Ledger(db).balance(wa) == 4000
    assert welcome.metrics(db)["converted_month"] == 0
    pay(db, wa, "pro")
    m = welcome.metrics(db)
    assert m["granted_month"] == 1 and m["converted_month"] == 1 and m["converted_total"] == 1


def test_verify_over_http_grants_the_bonus_with_the_device_cookie(app):  # noqa: F811
    box = []
    app.send_mail = lambda to, subject, text, html=None: box.append(subject) or True
    a = User(app, "http@x.com")
    code = box[-1].rsplit(" ", 1)[-1]
    h = {**CLIENT, "Cookie": f"{a.cookie}; {welcome.DEVICE_COOKIE}={DEV_A}"}
    r = app.handle("POST", "/api/auth/verify", h, json.dumps({"code": code}).encode())
    body = json.loads(r.body)
    assert r.status == 200 and body["welcome"]["granted"] and body["welcome"]["credits"] == 20
    me = a.get("/api/me")[1]
    assert me["welcome"]["credits"] == 20 and me["workspace"]["credits"]["balance"] == "20"
    assert me["plan"]["plan"] == "free" and me["plan"]["has_purchase"] is False


def test_unverified_signup_has_no_bonus(app):  # noqa: F811
    app.send_mail = lambda *a, **k: True
    a = User(app, "semconfirmar@x.com")
    me = a.get("/api/me")[1]
    assert me["welcome"] is None and me["workspace"]["credits"]["balance_cc"] == 0
