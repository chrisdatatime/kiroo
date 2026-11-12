"""'Seu próximo vídeo': resumo antes de gastar e confirmação do cliente. Sem confirmação nada é gasto; o valor
confirmado é o que o cliente viu; R$ só com STUDIO_CREDIT_PRICE_BRL; produções antigas e DEMO não são afetadas."""

from __future__ import annotations

import pytest

from studio import budget, migrations
from studio.credits import fmt
from studio.db import Database
from studio.orchestrator import BudgetExceeded, OrchestratorError
from studio.states import ProductionStatus as PS
from studio.web import view

from .test_prebudget import GRANT, funded, new_prod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("STUDIO_CREDIT_PRICE_BRL", raising=False)


def brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ sem confirmação nada é gasto
def test_nothing_is_spent_without_confirmation(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    est = db.production(pid)["prebudget_cc"]
    assert orch.needs_confirmation(pid)
    for _ in range(2):
        orch.run(pid)
    assert orch.image_gen.submit_count == 0 and db.attempts(pid) == []
    assert db.production(pid)["status"] == PS.VALIDATED          # espera o cliente; não pausa nem falha
    assert led.pool_state(pid)["used_cc"] == 0 and led.balance(wid) == GRANT - est
    orch.confirm_cost(pid)
    orch.run(pid)
    assert orch.image_gen.submit_count >= 1 and not orch.needs_confirmation(pid)


def test_unconfirmed_hold_is_refused_defensively(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    with pytest.raises(BudgetExceeded):
        orch._hold(pid, 0.05, "teste", "image")


def test_cancel_before_confirming_returns_the_reservation(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    orch.cancel(pid)
    assert led.balance(wid) == GRANT and led.held(wid) == 0


# ------------------------------------------------------------------ valor confirmado = valor visto
def test_confirm_requires_the_amount_the_client_saw(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    total = db.production(pid)["prebudget_cc"]
    with pytest.raises(OrchestratorError):
        orch.confirm_cost(pid, total + 100)                        # o valor mudou desde o resumo
    assert orch.needs_confirmation(pid)
    orch.confirm_cost(pid, total)
    orch.confirm_cost(pid, total + 999)                            # idempotente: já confirmado, nada muda
    row = db.production(pid)
    assert row["cost_confirmed_cc"] == total and row["cost_confirmed_at"]
    assert len([e for e in db.events(pid) if e["type"] == "cost_confirmed"]) == 1


# ------------------------------------------------------------------ conteúdo do resumo
def test_summary_has_product_format_scenes_adjustments_cost_balance(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    sm = budget.next_video_summary(db, orch.s, pid)
    total = db.production(pid)["prebudget_cc"]
    assert sm["product"] == product.name and sm["format"] == "9:16" and sm["scenes"] == 3
    assert sm["included_adjustments_per_scene"] == 1
    assert sm["total_cc"] == total and sm["balance_cc"] == GRANT      # saldo atual conta o que está reservado
    assert sm["balance_after"] == fmt(GRANT - total)
    assert sm["no_extra_cost"] == "Nenhum custo adicional será aplicado sem sua autorização."
    assert sm["total_brl"] is None                                   # sem tabela de preço configurada: sem R$


def test_brl_only_with_configured_credit_price(settings, product, tmp_path, monkeypatch):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    total = db.production(pid)["prebudget_cc"]
    monkeypatch.setenv("STUDIO_CREDIT_PRICE_BRL", "0.5")
    assert budget.next_video_summary(db, orch.s, pid)["total_brl"] == brl(total / 100 * 0.5)
    for bad in ("0", "-1", "abc", "nan", "inf"):
        monkeypatch.setenv("STUDIO_CREDIT_PRICE_BRL", bad)
        assert budget.next_video_summary(db, orch.s, pid)["total_brl"] is None, bad


# ------------------------------------------------------------------ o que a tela recebe
def test_snapshot_exposes_confirmation_and_old_productions_are_unaffected(settings, product, tmp_path):
    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    c = view.snapshot(orch.s, db, pid)["production"]["confirmation"]
    assert c["required"] and not c["confirmed"] and c["summary"]["scenes"] == 3
    orch.confirm_cost(pid)
    assert view.snapshot(orch.s, db, pid)["production"]["confirmation"]["confirmed"]
    old = new_prod(orch, product, wid, prebudget=False)            # produção antiga: sem confirmação, abre e roda
    assert view.snapshot(orch.s, db, old)["production"]["confirmation"] == {"required": False, "confirmed": True, "summary": None}
    assert not orch.needs_confirmation(old)
    orch.run(old)
    assert orch.image_gen.submit_count >= 1


def test_demo_mode_never_needs_confirmation(make_orch, product):
    from .conftest import create
    orch = make_orch()
    pid = create(orch, product)
    assert not orch.needs_confirmation(pid)
    orch.run(pid)
    assert orch.image_gen.submit_count == 1


# ------------------------------------------------------------------ rota
def test_confirm_route_checks_owner_amount_and_does_not_start_the_run(settings, product, tmp_path):
    from studio.web.server import App

    db, wid, led, orch = funded(settings, tmp_path)
    pid = new_prod(orch, product, wid, confirm=False)
    total = db.production(pid)["prebudget_cc"]
    app = App(8765, settings_loader=lambda: settings, sim_pacing=False)
    with pytest.raises(OrchestratorError, match="custo mudou"):    # o handler HTTP transforma em 400
        app._action(pid, "confirm", {"total_cc": total + 1}, settings)
    assert Database(settings.db_path).production(pid)["cost_confirmed_at"] is None
    r = app._action(pid, "confirm", {"total_cc": total}, settings)
    assert r.status == 200 and not app.is_running(pid)             # só autoriza; quem inicia é direction/run
    assert Database(settings.db_path).production(pid)["cost_confirmed_cc"] == total


# ------------------------------------------------------------------ migração
def test_migration_4_confirms_productions_already_past_validation(tmp_path):
    db = Database(tmp_path / "m.sqlite3")
    c = db.conn
    ts = "2026-01-01T00:00:00+00:00"
    for pid, st in (("prod_aaaaaaaaaa", "producing"), ("prod_bbbbbbbbbb", "validated"), ("prod_cccccccccc", "completed")):
        c.execute("INSERT INTO productions(id,status,mode,format_id,product_json,profiles_json,budget_usd,created_at,updated_at,"
                  "prebudget_cc) VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, st, "real", "f", "{}", "{}", 1, ts, ts, 5000))
    c.execute("UPDATE productions SET cost_confirmed_at=NULL, cost_confirmed_cc=NULL")
    c.commit()
    migrations._m004_cost_confirmation(c)
    rows = {r["id"]: r["cost_confirmed_at"] for r in c.execute("SELECT id, cost_confirmed_at FROM productions")}
    assert rows["prod_aaaaaaaaaa"] and rows["prod_cccccccccc"] and rows["prod_bbbbbbbbbb"] is None
    db.close()
