import dataclasses
import json

import pytest

from studio.accounts import Accounts
from studio.credits import InsufficientCredits, Ledger, to_cc
from studio.db import Database
from studio.ffmpeg import FFmpeg
from studio.orchestrator import Orchestrator
from studio.providers.base import PermanentError
from studio.providers.simulated import SimulatedPlanner, SimulatedReviewer, SimulatedVideoGenerator, SimulationScript
from studio.states import ProductionStatus as PS

from .test_accounts import User, app  # noqa: F401 — fixture reaproveitada
from .test_upload_demo_spend import FakeRealImages


def ws_db(settings, exempt=False):
    db = Database(settings.db_path)
    acc = Accounts(db)
    _, wid = acc.create_user("cliente@example.com", "senha-forte-123")
    acc.set_workspace(wid, allow_real=1, mode="real", monthly_cap_usd=100, credits_exempt=int(exempt))
    return db, wid


def real_orch(settings, db, tmp_path, image_gen=None):
    s = dataclasses.replace(settings, mode="real", allow_paid_calls=True, monthly_cap_usd=100)
    ff = FFmpeg(s.ffmpeg_bin, s.ffprobe_bin, s.font_file, "ultrafast")
    script = SimulationScript()
    return Orchestrator(s, db, image_gen=image_gen or FakeRealImages(s.data_dir, s.image_model, script),
                        video_gen=SimulatedVideoGenerator(s.data_dir, s.video_model, ff, script),
                        planner=SimulatedPlanner(), reviewer=SimulatedReviewer(script), ffmpeg=ff,
                        sleep=lambda _: None, base_dir=tmp_path)


def new_prod(orch, product, wid):
    return orch.create_production(product, format_id="maos_3cenas_15s", art_direction="cozinha_sp_alto_padrao",
                                  presenter="bia", budget_usd=50, workspace_id=wid)


def test_hold_release_and_idempotent_grant(settings):
    db, wid = ws_db(settings)
    led = Ledger(db)
    assert led.add(wid, 500, ext_ref="mp:pay_1") == led.add(wid, 500, ext_ref="mp:pay_1")  # webhook repetido
    assert led.balance(wid) == 500
    with pytest.raises(InsufficientCredits):
        led.hold(wid, "prod_x", 1.0, "image")  # US$1 ≈ 1620 centésimos > 500
    assert led.balance(wid) == 500 and led.held(wid) == 0  # nada reservado na recusa
    hid = led.hold(wid, "prod_x", 0.05, "image")
    assert led.held(wid) == to_cc(0.05) and led.balance(wid) == 500 - to_cc(0.05)
    led.release(hid)
    led.release(hid)  # idempotente
    assert led.balance(wid) == 500 and led.held(wid) == 0
    with pytest.raises(ValueError):
        led.add(wid, -10)  # crédito negativo só como ajuste


def test_real_production_debits_and_pauses_without_balance(settings, product, tmp_path):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 10_000, note="teste")
    orch = real_orch(settings, db, tmp_path)
    pid = new_prod(orch, product, wid)
    orch.run(pid)
    att = [a for a in db.attempts(pid) if a["kind"] == "image"][0]
    debit = to_cc(att["estimated_cost_usd"])  # sem custo confirmado → cobra o estimado
    assert debit > 0 and led.held(wid) == 0
    assert led.balance(wid) == 10_000 - debit
    use = led.usage(wid)
    assert use[0]["production_id"] == pid and use[0]["total_cc"] == debit and use[0]["stages"][0]["stage"] == "Imagens"

    led.add(wid, -(led.balance(wid) - 1), kind="adjust", note="zera para o teste")
    orch.approve(pid, 1, "image")
    orch.run(pid)
    prod = db.production(pid)
    assert prod["status"] == PS.PAUSED and "saldo de créditos insuficiente" in prod["status_reason"]
    assert "estimado US$" in prod["status_reason"]  # a interface lê o próximo custo daqui
    assert orch.image_gen.submit_count == 1 and led.held(wid) == 0

    led.add(wid, 10_000)
    orch.resume(pid)
    orch.run(pid)
    assert orch.image_gen.submit_count == 3  # cenas 2 e 3
    assert led.held(wid) == 0
    debits = [e for e in led.statement(wid) if e["kind"] == "debit" and e["stage"] == "Imagens"]
    assert len(debits) == 3


class RefusingImages(FakeRealImages):
    def submit(self, req):
        raise PermanentError("conteúdo recusado pelo provedor")


def test_refusal_without_cost_is_refunded(settings, product, tmp_path):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 10_000)
    orch = real_orch(settings, db, tmp_path, image_gen=RefusingImages(settings.data_dir, settings.image_model))
    pid = new_prod(orch, product, wid)
    orch.run(pid)
    assert led.balance(wid) == 10_000 and led.held(wid) == 0
    kinds = [e["kind"] for e in led.statement(wid)]
    assert "refund" in kinds and "debit" not in kinds


def test_exempt_workspace_records_usage_without_balance(settings, product, tmp_path):
    db, wid = ws_db(settings, exempt=True)
    led = Ledger(db)
    orch = real_orch(settings, db, tmp_path)
    pid = new_prod(orch, product, wid)
    orch.run(pid)
    assert orch.image_gen.submit_count == 1
    assert led.balance(wid) < 0 and led.summary(wid)["exempt"]


def test_migration_marks_existing_admin_exempt(settings):
    db = Database(settings.db_path)
    acc = Accounts(db)
    _, wid_admin = acc.create_user("dono@example.com", "senha-forte-123", admin=True)
    _, wid_cli = acc.create_user("cli@example.com", "senha-forte-123")
    db.conn.execute("ALTER TABLE workspaces DROP COLUMN credits_exempt")  # banco da Fase B
    Accounts(db)
    led = Ledger(db)
    assert led.exempt(wid_admin) and not led.exempt(wid_cli)


def test_demo_does_not_touch_credits(product, make_orch):
    orch = make_orch()
    db = orch.db
    acc = Accounts(db)
    _, wid = acc.create_user("demo@example.com", "senha-forte-123")
    pid = new_prod(orch, product, wid)
    orch.run(pid)
    assert Ledger(db).statement(wid) == []


def test_credits_api(app):  # noqa: F811
    admin = User(app, "admin@example.com")
    cliente = User(app, "cliente@example.com")
    assert admin.me["workspace"]["credits"]["exempt"] is True
    assert cliente.me["workspace"]["credits"] == {**cliente.me["workspace"]["credits"], "balance_cc": 0, "exempt": False}
    db = Database(app.load_settings().db_path)
    Ledger(db).add(cliente.me["workspace"]["id"], 2500, note="boas-vindas")
    db.close()
    status, body = cliente.get("/api/credits")
    assert status == 200 and body["balance"] == "25" and body["statement"][0]["note"] == "boas-vindas"
    status, body = admin.get("/api/credits")
    assert body["statement"] == []  # cada workspace só vê o próprio extrato
    status, state = cliente.get("/api/state")
    assert state["credits"]["balance_cc"] == 2500
    assert json.dumps(state["credits"])  # serializável


class BrokeProviderImages(FakeRealImages):
    """Conta do provedor sem créditos pré-pagos (HTTP 402) até `funded` virar True."""
    funded = False

    def submit(self, req):
        if not self.funded:
            from studio.providers.base import ProviderBillingError
            raise ProviderBillingError("APIStatusError: Error code: 402 - Your prepayment credits are depleted.")
        return super().submit(req)


def test_provider_out_of_credits_pauses_without_spending_attempts(settings, product, tmp_path):
    from studio.orchestrator import PROVIDER_BILLING_REASON
    from studio.states import SceneStatus as SS
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, 10_000)
    gen = BrokeProviderImages(settings.data_dir, settings.image_model)
    orch = real_orch(settings, db, tmp_path, image_gen=gen)
    pid = new_prod(orch, product, wid)
    for _ in range(5):  # insistir não esgota as tentativas nem bloqueia a cena
        assert orch.run(pid) == PS.PAUSED
        assert db.production(pid)["status_reason"].startswith(PROVIDER_BILLING_REASON)
        assert db.scene(pid, 1)["status"] == SS.GENERATING_IMAGE
        assert db.count_generation_attempts(pid, 1, "image") == 0
        orch.resume(pid)
    assert led.balance(wid) == 10_000 and led.held(wid) == 0
    gen.funded = True  # recarregou a conta: retomar gera normalmente
    orch.run(pid)
    assert db.scene(pid, 1)["status"] != SS.BLOCKED
    assert db.count_generation_attempts(pid, 1, "image") >= 1


def test_gemini_classifies_402_as_billing():
    from studio.providers.base import ProviderBillingError
    from studio.providers.gemini import _classify

    class APIStatusError(Exception):
        status_code = 402
    assert isinstance(_classify(APIStatusError("Your prepayment credits are depleted")), ProviderBillingError)

    class Other(Exception):
        pass
    assert isinstance(_classify(Other("Error code: 402 - RESOURCE_EXHAUSTED prepayment credits")), ProviderBillingError)
