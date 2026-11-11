"""Saldo do cliente × orçamento operacional: pré-orçamento reservado antes de começar, falha técnica não cobra,
ajuste incluído não cobra, ajuste extra só com autorização, freio interno nunca pede dinheiro, acertos idempotentes
e produções antigas continuam abrindo."""

from __future__ import annotations

import json

import pytest

from studio import budget
from studio.accounts import Accounts
from studio.credits import InsufficientCredits, Ledger
from studio.providers.base import OpResult, OpState
from studio.states import ProductionStatus as PS, SceneStatus as SS
from studio.web import view

from .test_credits import real_orch, ws_db
from .test_upload_demo_spend import FakeRealImages

GRANT = 50_000   # 500 créditos


def new_prod(orch, product, wid, *, budget_usd=50.0, prebudget=True):
    return orch.create_production(product, format_id="maos_3cenas_15s", art_direction="cozinha_sp_alto_padrao",
                                  presenter="bia", budget_usd=budget_usd, workspace_id=wid, prebudget=prebudget)


def funded(settings, tmp_path, cc=GRANT, image_gen=None):
    db, wid = ws_db(settings)
    led = Ledger(db)
    led.add(wid, cc, note="teste")
    return db, wid, led, real_orch(settings, db, tmp_path, image_gen=image_gen)


def first_image_ready(orch, pid):
    orch.run(pid)
    assert orch.db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL


# ------------------------------------------------------------------ estimativa vem da tabela
def test_estimate_comes_from_cost_table_and_env(settings, monkeypatch, tmp_path):
    base = budget.estimate_production(settings)
    assert base["scenes"] == 3 and base["cc"] > 0 and base["included_adjustments_per_scene"] == 1
    monkeypatch.setenv("STUDIO_ESTIMATE_VIDEO_TRIES_PER_SCENE", "3")
    assert budget.estimate_production(settings)["usd"] > base["usd"]
    monkeypatch.setenv("STUDIO_ESTIMATE_VIDEO_TRIES_PER_SCENE", "abc")   # inválido volta ao padrão
    assert budget.estimate_production(settings)["usd"] == base["usd"]
    table = json.loads(budget.DEFAULT_COSTS_FILE.read_text(encoding="utf-8"))
    table["operations"]["video"]["usd"] = 0.5   # tabela própria: o custo do vídeo sai dela, não do código
    f = tmp_path / "costs.json"
    f.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv("STUDIO_OPERATION_COSTS_FILE", str(f))
    assert budget.op_cost(settings, "video") == 0.5


# ------------------------------------------------------------------ saldo insuficiente bloqueia antes
def test_insufficient_balance_blocks_before_start(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path, cc=1_000)   # 10 créditos, o vídeo custa ~157
    before = db.conn.execute("SELECT COUNT(*) FROM productions").fetchone()[0]
    with pytest.raises(InsufficientCredits) as exc:
        new_prod(orch, product, wid)
    assert exc.value.needed_cc == budget.estimate_production(orch.s)["cc"] and exc.value.balance_cc == 1_000
    assert db.conn.execute("SELECT COUNT(*) FROM productions").fetchone()[0] == before   # nada foi criado
    assert led.balance(wid) == 1_000 and led.held(wid) == 0 and orch.image_gen.submit_count == 0


def test_server_refuses_creation_without_balance_with_clear_message(settings, tmp_path, monkeypatch):
    from studio.config import load_settings
    from studio.web.server import App

    from .conftest import login_app
    from .test_upload_demo_spend import png_data_url

    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "100")

    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    app = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(app, {}, email="dono@example.com")                 # o primeiro vira admin (isento)
    host: dict = {}
    login_app(app, host, email="cliente@example.com")
    s, db, acc = app._db()
    try:
        wid = acc.workspaces_of(acc.user_by_email("cliente@example.com")["id"])[0]["id"]
        acc.set_workspace(wid, allow_real=1, mode="real", monthly_cap_usd=50, credits_exempt=0)
        Ledger(db).add(wid, 500, note="pouco saldo")
    finally:
        db.close()
    body = {"name": "Copo", "files": [{"name": "f.png", "data": png_data_url(), "role": "front"}], "start": False}
    r = app.handle("POST", "/api/productions", {**host, "X-Studio-Token": app.token}, json.dumps(body).encode())
    data = json.loads(r.body)
    assert r.status == 402 and data["insufficient_credits"] and "Nada foi cobrado" in data["error"]
    assert "créditos" in data["error"] and not list((settings.data_dir / "uploads").rglob("*.png"))


# ------------------------------------------------------------------ reserva e uso
def test_prebudget_is_reserved_and_usage_draws_from_it(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    est = db.production(pid)["prebudget_cc"]
    assert est == budget.estimate_production(orch.s)["cc"]
    assert led.balance(wid) == GRANT - est and led.held(wid) == est
    first_image_ready(orch, pid)
    charges = led.charges(pid)
    assert charges and all(c["decision"] == "charged" for c in charges)
    used = led.pool_state(pid)["used_cc"]
    assert used == sum(c["charged_cc"] for c in charges) > 0
    assert led.balance(wid) == GRANT - est            # o uso sai do que já foi reservado, nada a mais
    assert led.held(wid) == est - used
    assert {c["operation"] for c in charges} >= {"image"} and all(c["provider"] for c in charges)


class FailingOnceImages(FakeRealImages):
    """Erro do provedor na primeira geração (tempo esgotado), sucesso depois."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.failed = False

    def poll(self, op_id):
        if not self.failed:
            self.failed = True
            return OpResult(state=OpState.FAILED, error="tempo esgotado no provedor")
        return super().poll(op_id)


def test_technical_failure_is_not_charged(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path, image_gen=FailingOnceImages(settings.data_dir, settings.image_model))
    pid = new_prod(orch, product, wid)
    est = db.production(pid)["prebudget_cc"]
    orch.run(pid)
    charges = led.charges(pid)
    failed = [c for c in charges if c["decision"] == "technical_failure"]
    assert len(failed) == 1 and failed[0]["charged_cc"] == 0 and failed[0]["cost_usd"] > 0   # custo interno registrado
    ok = [c for c in charges if c["decision"] == "charged"]
    assert led.pool_state(pid)["used_cc"] == sum(c["charged_cc"] for c in ok)
    assert led.balance(wid) == GRANT - est


def test_technical_failure_is_refunded_in_old_productions(settings, product, tmp_path):
    """Regime antigo (reserva por chamada): falha técnica devolve a reserva e não debita."""
    db, wid, led, orch = funded(settings, tmp_path, image_gen=FailingOnceImages(settings.data_dir, settings.image_model))
    pid = new_prod(orch, product, wid, prebudget=False)
    orch.run(pid)
    att = [a for a in db.attempts(pid) if a["kind"] == "image"]
    assert att[0]["status"] == "failed"
    debits = db.conn.execute("SELECT COUNT(*) FROM credit_entries WHERE attempt_id=? AND kind='debit'",
                             (att[0]["id"],)).fetchone()[0]
    assert debits == 0 and led.held(wid) == 0


# ------------------------------------------------------------------ ajustes
def test_included_adjustment_does_not_charge(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    first_image_ready(orch, pid)
    bal, reserves = led.balance(wid), db.conn.execute("SELECT COUNT(*) FROM credit_entries WHERE kind='reserve'").fetchone()[0]
    orch.reject(pid, 1, "image", "mais luz")             # 1 ajuste incluído por cena: sem autorização
    assert db.scene(pid, 1)["adjustments_used"] == 1
    orch.run(pid)
    assert db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL
    assert led.balance(wid) == bal                       # nada além do pré-orçamento
    assert db.conn.execute("SELECT COUNT(*) FROM credit_entries WHERE kind='reserve'").fetchone()[0] == reserves


def test_extra_adjustment_needs_explicit_authorization_with_visible_cost(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    first_image_ready(orch, pid)
    orch.reject(pid, 1, "image", "mais luz")
    orch.run(pid)
    bal = led.balance(wid)
    scene_before = dict(db.scene(pid, 1))
    with pytest.raises(budget.AdjustmentNeedsAuthorization) as exc:
        orch.reject(pid, 1, "image", "outra cor de fundo")
    cost = exc.value.cost_cc
    assert cost == orch.adjustment_info(pid, 1)["extra_cost_cc"]["image"] > 0
    assert dict(db.scene(pid, 1)) == scene_before and led.balance(wid) == bal   # nada mudou sem autorização
    snap = view.snapshot(orch.s, db, pid)["production"]
    adj = [s for s in snap["scenes"] if s["idx"] == 1][0]["adjustments"]
    assert adj["free_left"] == 0 and adj["extra_cost_credits"]["image"] == -(-cost // 100)   # custo visível

    orch.reject(pid, 1, "image", "outra cor de fundo", authorize_extra=True)
    assert led.balance(wid) == bal - cost and db.scene(pid, 1)["adjustments_authorized"] == 1
    assert led.pool_state(pid)["reserved_cc"] == db.production(pid)["prebudget_cc"] + cost


def test_extra_adjustment_without_balance_changes_nothing(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    first_image_ready(orch, pid)
    orch.reject(pid, 1, "image", "mais luz")
    orch.run(pid)
    led.add(wid, -led.balance(wid), kind="adjust", note="zera para o teste")
    with pytest.raises(InsufficientCredits):
        orch.reject(pid, 1, "image", "outra", authorize_extra=True)
    assert db.scene(pid, 1)["adjustments_authorized"] == 0 and db.scene(pid, 1)["adjustments_used"] == 1
    assert db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL


# ------------------------------------------------------------------ freio interno
def test_ops_budget_reached_never_charges_nor_asks_for_upgrade(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, budget_usd=0.07)   # cabe 1 imagem: o freio interno pega a segunda
    est = db.production(pid)["prebudget_cc"]
    first_image_ready(orch, pid)
    orch.approve(pid, 1, "image")
    orch.run(pid)
    prod = db.production(pid)
    assert prod["status"] == PS.PAUSED and prod["pause_code"] == budget.OPS_BUDGET_REACHED
    assert prod["status_reason"] == budget.CLIENT_MESSAGES[budget.OPS_BUDGET_REACHED]
    for word in ("limite", "upgrade", "subir", "US$"):
        assert word.lower() not in prod["status_reason"].lower()
    alerts = [e for e in db.events(pid) if e["type"] == "ops_alert"]
    assert alerts and json.loads(alerts[-1]["data_json"])["code"] == budget.OPS_BUDGET_REACHED
    assert orch.image_gen.submit_count == 1
    assert led.balance(wid) == GRANT - est                # nenhuma cobrança automática
    assert db.conn.execute("SELECT COUNT(*) FROM credit_entries WHERE kind='reserve'").fetchone()[0] == 1
    snap = view.snapshot(orch.s, db, pid)["production"]
    assert snap["pause_code"] == budget.OPS_BUDGET_REACHED and snap["credits"]["prebudget"]
    assert snap["credits"]["budget"] == -(-est // 100)    # o cliente vê o que reservou, não o freio interno
    # o administrador ajusta o freio e retoma; o cliente continua sem pagar a mais
    orch.set_budget(pid, 50)
    orch.resume(pid)
    assert db.production(pid)["pause_code"] is None
    orch.run(pid)
    assert orch.image_gen.submit_count >= 2 and led.balance(wid) == GRANT - est


def test_zero_cap_spends_nothing_even_with_prebudget(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    Accounts(db).set_workspace(wid, monthly_cap_usd=0)
    pid = new_prod(orch, product, wid)
    orch.run(pid)
    prod = db.production(pid)
    assert orch.image_gen.submit_count == 0 and prod["pause_code"] == budget.MONTHLY_CAP
    assert led.pool_state(pid)["used_cc"] == 0


# ------------------------------------------------------------------ idempotência e encerramento
def test_settlement_is_idempotent_and_cancel_returns_the_rest(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    first_image_ready(orch, pid)
    used = led.pool_state(pid)["used_cc"]
    n = len(led.charges(pid))
    for _ in range(3):
        orch._settle(pid)
        led.settle_pool(pid, wid)
    assert len(led.charges(pid)) == n and led.pool_state(pid)["used_cc"] == used
    debits = db.conn.execute("SELECT COUNT(*) FROM credit_entries WHERE production_id=? AND kind='debit'", (pid,)).fetchone()[0]
    assert debits == len([c for c in led.charges(pid) if c["charged_cc"] > 0])
    orch.cancel(pid)
    assert led.close_pool(pid) == 0                       # já encerrado: não devolve duas vezes
    assert led.held(wid) == 0 and led.balance(wid) == GRANT - used
    with pytest.raises(ValueError):
        led.reserve_pool(wid, pid, 100, ref="extra:9:9")  # pré-orçamento encerrado não reabre


def test_same_reserve_ref_is_not_duplicated(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid)
    bal = led.balance(wid)
    assert led.reserve_pool(wid, pid, 500, ref="extra:1:1") is True
    assert led.reserve_pool(wid, pid, 500, ref="extra:1:1") is False   # repetição (clique duplo, retry de rede)
    assert led.balance(wid) == bal - 500


# ------------------------------------------------------------------ produções antigas
def test_old_production_without_prebudget_still_opens_and_runs(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, prebudget=False)
    assert db.production(pid)["prebudget_cc"] is None and led.held(wid) == 0
    snap = view.snapshot(orch.s, db, pid)["production"]
    assert snap["credits"]["prebudget"] is False and snap["pause_code"] is None
    assert all(s["adjustments"] is None for s in snap["scenes"])
    first_image_ready(orch, pid)
    assert led.balance(wid) < GRANT and led.held(wid) == 0          # regime antigo: débito por chamada
    orch.reject(pid, 1, "image", "mais luz")
    orch.reject(pid, 1, "image", "mais luz de novo")                 # sem regra de ajuste incluído
    assert view.snapshot(orch.s, db, pid)["production"]["id"] == pid
