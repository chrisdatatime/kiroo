"""`studio admin set-mode` / `set-cap`, teto efetivo (o menor entre conta e plataforma) e teto 0 bloqueando todo gasto."""

from __future__ import annotations

import argparse
import time

import pytest

from studio import cli, paid_gate
from studio.accounts import Accounts
from studio.agent_chat import FALLBACK, AgentChat
from studio.credits import Ledger
from studio.db import Database

from .test_paid_gate import Model, new_production, paused_reason, real_orch, run_two_images
from .test_upload_demo_spend import app  # noqa: F401 (fixture)

EMAIL = "ana@exemplo.com"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in ("STUDIO_ENV", "STUDIO_KILL_SWITCH", "STUDIO_ALLOW_PAID_CALLS", "STUDIO_MONTHLY_CAP_USD",
              "STUDIO_AGENT_DAILY_CAP_USD"):
        monkeypatch.delenv(v, raising=False)


def admin(settings, acao, **kw):
    args = argparse.Namespace(acao=acao, email=EMAIL, name="", admin=False, credits=None, note="", days=7, id=None,
                              yes=False, mode=None, usd=None)
    for k, v in kw.items():
        setattr(args, k, v)
    return cli._admin(settings, args)


@pytest.fixture
def conta(settings):
    db = Database(settings.db_path)
    _, wid = Accounts(db).create_user(EMAIL, "senha-forte-123")
    db.close()
    return wid


def ws(settings, wid):
    db = Database(settings.db_path)
    try:
        return dict(Accounts(db).workspace(wid))
    finally:
        db.close()


def entries(settings, wid):
    db = Database(settings.db_path)
    try:
        return [r["note"] for r in db.conn.execute("SELECT note FROM credit_entries WHERE workspace_id=? AND kind='adjust'", (wid,))]
    finally:
        db.close()


# ------------------------------------------------------------------ set-cap
def test_set_cap_within_platform_cap_is_saved_and_audited(settings, conta, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    assert admin(settings, "set-cap", usd=3.5) == 0
    assert ws(settings, conta)["monthly_cap_usd"] == 3.5
    assert any("set-cap" in n and "3.50" in n for n in entries(settings, conta))
    assert "efetivo US$3.50" in capsys.readouterr().out
    assert admin(settings, "set-cap", usd=0) == 0 and ws(settings, conta)["monthly_cap_usd"] == 0   # zero é válido
    assert admin(settings, "set-cap", usd=5) == 0 and ws(settings, conta)["monthly_cap_usd"] == 5   # igual à plataforma


@pytest.mark.parametrize("usd", [5.01, 100, -1, float("nan"), float("inf")])
def test_set_cap_above_platform_or_invalid_is_refused(settings, conta, monkeypatch, capsys, usd):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    assert admin(settings, "set-cap", usd=2) == 0
    assert admin(settings, "set-cap", usd=usd) == 2
    assert ws(settings, conta)["monthly_cap_usd"] == 2   # nada mudou
    assert "erro:" in capsys.readouterr().err


def test_set_cap_without_platform_cap_only_accepts_zero(settings, conta, capsys):
    assert admin(settings, "set-cap", usd=1) == 2
    assert "STUDIO_MONTHLY_CAP_USD" in capsys.readouterr().err
    assert admin(settings, "set-cap", usd=0) == 0


def test_set_cap_requires_usd_and_known_email(settings, conta, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    assert admin(settings, "set-cap") == 2 and "--usd" in capsys.readouterr().err
    assert admin(settings, "set-cap", usd=1, email="ninguem@exemplo.com") == 2


# ------------------------------------------------------------------ set-mode
def test_set_mode_real_requires_allow_real(settings, conta, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    assert admin(settings, "set-mode", mode="real") == 2
    assert "allow-real" in capsys.readouterr().err and ws(settings, conta)["mode"] == "simulated"
    assert admin(settings, "allow-real") == 0
    assert admin(settings, "set-mode", mode="real") == 0
    assert ws(settings, conta)["mode"] == "real"
    assert any("set-mode" in n and "real" in n for n in entries(settings, conta))
    assert admin(settings, "set-mode", mode="simulated") == 0 and ws(settings, conta)["mode"] == "simulated"


@pytest.mark.parametrize("mode", [None, "", "demo", "REAL2"])
def test_set_mode_rejects_invalid_mode(settings, conta, capsys, mode):
    assert admin(settings, "set-mode", mode=mode) == 2
    assert "simulated" in capsys.readouterr().err and ws(settings, conta)["mode"] == "simulated"


def test_set_mode_real_warns_when_effective_cap_is_zero(settings, conta, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    admin(settings, "allow-real")
    capsys.readouterr()
    assert admin(settings, "set-mode", mode="real") == 0
    assert "teto efetivo é US$0.00" in capsys.readouterr().out


def test_list_shows_mode_cap_and_effective_cap(settings, conta, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    admin(settings, "allow-real")
    admin(settings, "set-cap", usd=4)
    admin(settings, "set-mode", mode="real")
    capsys.readouterr()
    assert admin(settings, "list") == 0
    out = capsys.readouterr().out
    assert "modo=real" in out and "real=sim" in out and "teto=US$4.00" in out and "efetivo=US$4.00" in out
    assert "teto da plataforma: US$5.00" in out


def test_secrets_never_printed(settings, conta, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    admin(settings, "allow-real")
    admin(settings, "set-cap", usd=1)
    admin(settings, "set-mode", mode="real")
    admin(settings, "list")
    out = capsys.readouterr()
    assert "AIza" not in out.out + out.err and "senha-forte" not in out.out + out.err


# ------------------------------------------------------------------ teto efetivo e teto 0
def test_effective_cap_is_the_smaller_one(monkeypatch):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "5")
    assert paid_gate.effective_cap(3) == 3
    assert paid_gate.effective_cap(50) == 5       # conta acima da plataforma: vale a plataforma
    assert paid_gate.effective_cap(0) == 0 and paid_gate.effective_cap(None) == 0 and paid_gate.effective_cap(-2) == 0
    monkeypatch.delenv("STUDIO_MONTHLY_CAP_USD")
    assert paid_gate.effective_cap(7) == 7        # dev sem teto de plataforma: vale a conta


def test_account_cap_above_platform_is_clamped_when_spending(settings, product, tmp_path, monkeypatch):
    """Mesmo que o banco tenha um teto maior que o da plataforma (valor antigo), o gasto para no teto menor."""
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "0.07")
    orch = real_orch(settings, tmp_path)
    acc = Accounts(orch.db)
    _, wid = acc.create_user(EMAIL, "senha-forte-123")
    acc.set_workspace(wid, monthly_cap_usd=500, credits_exempt=1, allow_real=1, mode="real")
    pid = new_production(orch, product, workspace_id=wid)
    run_two_images(orch, pid)
    assert orch.image_gen.submit_count == 1
    assert "limite de gastos do Kiroo" in paused_reason(orch, pid)


def test_zero_cap_blocks_production_spend(settings, product, tmp_path):
    orch = real_orch(settings, tmp_path)
    acc = Accounts(orch.db)
    _, wid = acc.create_user(EMAIL, "senha-forte-123")
    acc.set_workspace(wid, monthly_cap_usd=0, credits_exempt=1, allow_real=1, mode="real")
    pid = new_production(orch, product, workspace_id=wid)
    run_two_images(orch, pid)
    assert orch.image_gen.submit_count == 0 and "teto mensal" in paused_reason(orch, pid)


def test_zero_cap_blocks_chat_ai(settings, monkeypatch):
    db = Database(settings.db_path)
    _, wid = Accounts(db).create_user(EMAIL, "senha-forte-123")
    model = Model()
    ask = lambda: AgentChat(model).reply(db.conn, user_id=f"u{time.perf_counter_ns()}", workspace_id=wid, agent="theo",
                                         text="me conta como fica a luz da cena dois", ctx={})
    res = ask()                                           # conta nova: teto 0
    assert res["source"] == "sem_ia" and res["reply"] == FALLBACK["paused"] and not model.calls
    Accounts(db).set_workspace(wid, monthly_cap_usd=1)
    assert ask()["source"] == "llm" and len(model.calls) == 1


def test_zero_cap_makes_workspace_demo_even_if_real(app, monkeypatch):
    s = app.settings()
    ws_row = {"id": "w", "owner_id": "x", "mode": "real", "allow_real": 1, "monthly_cap_usd": 0}
    assert app.ws_settings(s, ws_row).mode == "simulated"
    ws_row["monthly_cap_usd"] = 3
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "2")
    eff = app.ws_settings(s, ws_row)
    assert eff.monthly_cap_usd == 2 and eff.mode == ("real" if s.gemini_api_key else "simulated")
