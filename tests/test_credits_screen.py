"""Tela Créditos e extrato (saldo, reservado, consumo por produção/cena/operação), saldo insuficiente para ajuste extra
(conta à vista, vídeo preservado, "Adicionar créditos" manual com ponto de integração do Mercado Pago) e a regra de
que um vídeo já pago nunca deixa de ser entregue por falta de saldo."""

from __future__ import annotations

import json

import pytest

from studio import payments
from studio.credits import Ledger, fmt
from studio.states import ProductionStatus as PS, SceneStatus as SS
from studio.web.server import App, _no_balance_for_adjustment

from .conftest import requires_ffmpeg
from .test_prebudget import GRANT, first_image_ready, funded, new_prod
from .test_upload_demo_spend import HOST, app, post  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in ("STUDIO_SUPPORT_CONTACT", "STUDIO_PAYMENTS_PROVIDER"):
        monkeypatch.delenv(v, raising=False)


def get(app, path):
    return app.handle("GET", path, {**HOST}, b"")


# ------------------------------------------------------------------ consumo por produção / cena / operação
def test_usage_by_production_scene_and_operation(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    first_image_ready(orch, pid)
    [u] = led.usage(wid)
    assert u["production_id"] == pid and u["total_cc"] > 0 and u["total"] == fmt(u["total_cc"])
    assert sum(s["cc"] for s in u["scenes"]) == u["total_cc"] == sum(s["cc"] for s in u["stages"])   # mesma conta, três recortes
    scene1 = [s for s in u["scenes"] if s["scene"] == 1][0]
    assert {o["operation"] for o in scene1["operations"]} >= {"Imagens"}
    assert all(o["credits"] and o["calls"] >= 1 for o in scene1["operations"])
    assert sum(o["cc"] for o in scene1["operations"]) == scene1["cc"]
    nones = [s for s in u["scenes"] if s["scene"] is None]
    assert [s["scene"] for s in u["scenes"]] == sorted((s["scene"] for s in u["scenes"] if s["scene"] is not None)) + [None] * len(nones)


def test_summary_shows_balance_and_reserved(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    est = db.production(pid)["prebudget_cc"]
    sm = led.summary(wid)
    assert sm["balance_cc"] == GRANT - est and sm["held_cc"] == est      # reservado para o vídeo
    first_image_ready(orch, pid)
    used = led.pool_state(pid)["used_cc"]
    sm = led.summary(wid)
    assert sm["held_cc"] == est - used and sm["balance_cc"] == GRANT - est


def test_credits_endpoint_returns_balance_statement_usage_and_topup(app):
    r = get(app, "/api/credits")
    d = json.loads(r.body)
    assert r.status == 200 and {"balance", "held", "statement", "usage", "topup", "exempt"} <= set(d)
    assert d["topup"]["online"] is False and d["topup"]["provider"] == "manual"


# ------------------------------------------------------------------ saldo insuficiente para ajuste extra
def spent_included_adjustment(orch, pid):
    first_image_ready(orch, pid)
    orch.reject(pid, 1, "image", "mais luz")          # o ajuste incluído da cena 1
    orch.run(pid)
    assert orch.db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL


def drain(led, wid, keep_cc):
    led.add(wid, -(led.balance(wid) - keep_cc), kind="adjust", note="saldo baixo para o teste")


def test_adjustment_without_balance_shows_the_math_and_changes_nothing(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    spent_included_adjustment(orch, pid)
    drain(led, wid, 500)                                                  # 5 créditos livres
    cost = orch.adjustment_info(pid, 1)["extra_cost_cc"]["image"]
    before = (dict(db.scene(pid, 1)), led.balance(wid), led.held(wid), len(led.charges(pid)))
    s = App(8765, settings_loader=lambda: settings, sim_pacing=False)
    for authorize in (False, True):                                       # pedir e até autorizar: mesma resposta
        r = s._action(pid, "reject", {"scene": 1, "stage": "image", "note": "outra cor", "authorize_extra": authorize}, settings)
        d = json.loads(r.body)
        assert r.status == 402 and d["error"] == "Saldo insuficiente para um novo ajuste" and d["insufficient_credits"]
        assert d["balance_cc"] == 500 and d["cost_cc"] == cost and d["missing_cc"] == cost - 500
        assert d["balance"] == "5" and d["cost"] == fmt(cost) and d["missing"] == fmt(cost - 500)
        assert d["keep_label"] == "Manter meu vídeo como está" and d["add_label"] == "Adicionar créditos"
        assert d["topup"]["missing_cc"] == cost - 500 and d["topup"]["online"] is False
    assert (dict(db.scene(pid, 1)), led.balance(wid), led.held(wid), len(led.charges(pid))) == before   # nada mudou
    # "Manter meu vídeo como está": o trabalho está todo lá e a cena ainda pode ser aprovada
    orch.approve(pid, 1, "image")
    assert db.scene(pid, 1)["status"] == SS.IMAGE_APPROVED and db.scene(pid, 1)["approved_image_attempt"]


def test_adjustment_with_enough_balance_still_asks_for_authorization(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    spent_included_adjustment(orch, pid)
    s = App(8765, settings_loader=lambda: settings, sim_pacing=False)
    r = s._action(pid, "reject", {"scene": 1, "stage": "image", "note": "outra cor"}, settings)
    d = json.loads(r.body)
    assert r.status == 402 and d["needs_authorization"] and not d.get("insufficient_credits")


def test_payload_helper_is_exact_and_never_negative():
    d = json.loads(_no_balance_for_adjustment(1800, 5000).body)         # saldo maior que o custo: nada falta
    assert d["missing_cc"] == 0
    d = json.loads(_no_balance_for_adjustment(1800, -300).body)         # saldo negativo (conta isenta) não confunde
    assert d["missing_cc"] == 2100


# ------------------------------------------------------------------ adicionar créditos: manual hoje, Mercado Pago depois
def test_topup_is_manual_with_contact_from_env(monkeypatch):
    t = payments.topup_options()
    assert t["provider"] == "manual" and not t["online"] and t["contact"] is None and t["steps"]
    monkeypatch.setenv("STUDIO_SUPPORT_CONTACT", "ajuda@kiroo.app")
    assert payments.topup_options()["contact"]["href"].startswith("mailto:ajuda@kiroo.app?subject=")
    monkeypatch.setenv("STUDIO_SUPPORT_CONTACT", "https://wa.me/5511999999999")
    assert payments.topup_options()["contact"]["href"] == "https://wa.me/5511999999999"
    monkeypatch.setenv("STUDIO_SUPPORT_CONTACT", "javascript:alert(1)")        # nunca vira link executável
    c = payments.topup_options()["contact"]
    assert c["href"] is None and c["label"] == "javascript:alert(1)"
    assert "18" in " ".join(payments.topup_options(1800)["steps"])             # diz quanto falta


def test_mercadopago_is_a_ready_integration_point_but_not_active(monkeypatch):
    monkeypatch.setenv("STUDIO_PAYMENTS_PROVIDER", "mercadopago")
    assert payments.provider_name() == "mercadopago" and payments.topup_options()["online"] is False
    with pytest.raises(payments.CheckoutUnavailable):
        payments.MercadoPagoProvider().start_checkout("ws_x", 1000)
    monkeypatch.setenv("STUDIO_PAYMENTS_PROVIDER", "qualquer")
    assert payments.provider_name() == "manual"


def test_webhook_credit_is_idempotent_by_ext_ref(settings):
    """O ponto de integração do Mercado Pago: o mesmo pagamento repetido credita uma vez só."""
    from .test_credits import ws_db
    db, wid = ws_db(settings)
    led = Ledger(db)
    a = led.add(wid, 3000, kind="purchase", ext_ref="mp:pay_42")
    b = led.add(wid, 3000, kind="purchase", ext_ref="mp:pay_42")
    assert a == b and led.balance(wid) == 3000


def test_topup_route(app):
    d = json.loads(get(app, "/api/credits/topup?missing_cc=250").body)
    assert d["missing_cc"] == 250 and d["provider"] == "manual"
    assert json.loads(get(app, "/api/credits/topup?missing_cc=abc").body)["missing_cc"] == 0


# ------------------------------------------------------------------ nunca bloquear a entrega de um vídeo já pago
def finish(orch, pid, rounds=12):
    for _ in range(rounds):
        status = orch.run(pid)
        if status != PS.PRODUCING:
            return status
        for s in orch.db.scenes(pid):
            if s["status"] == SS.AWAITING_IMAGE_APPROVAL:
                orch.approve(pid, s["idx"], "image")
            elif s["status"] == SS.AWAITING_VIDEO_APPROVAL:
                orch.approve(pid, s["idx"], "video")
    return orch.db.production(pid)["status"]


@requires_ffmpeg
def test_paid_video_is_delivered_even_with_zero_balance(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    first_image_ready(orch, pid)
    drain(led, wid, 0)                                                    # saldo livre zerado no meio da produção
    assert finish(orch, pid) == PS.AWAITING_FINAL_REVIEW                  # o que foi reservado leva até o fim
    assert (settings.data_dir / "productions" / pid / "delivery" / "final.mp4").is_file()
    orch.final_decision(pid, True)
    assert db.production(pid)["status"] == PS.COMPLETED
    assert led.held(wid) == 0 and led.balance(wid) >= 0                  # sobra do pré-orçamento volta; nunca fica negativo


@requires_ffmpeg
def test_old_regime_video_is_delivered_after_balance_pause(settings, product, tmp_path):
    """Produção antiga pausada por saldo: aprovar o que já existe e retomar entrega sem exigir créditos."""
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, prebudget=False)
    first_image_ready(orch, pid)
    drain(led, wid, 1)
    orch.approve(pid, 1, "image")
    orch.run(pid)
    assert db.production(pid)["status"] == PS.PAUSED and db.production(pid)["pause_code"] == "credits_insufficient"
    # sem créditos, o cliente ainda aprova o que já está pronto; só as etapas novas dependem de saldo
    assert db.scene(pid, 1)["approved_image_attempt"]                     # a imagem aprovada continua guardada
    led.add(wid, GRANT, note="liberado pela equipe")
    orch.resume(pid)
    assert finish(orch, pid) == PS.AWAITING_FINAL_REVIEW
