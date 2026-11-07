"""Gasto: portão único das chamadas pagas (kill switch, padrão desligado em staging/produção) e os tetos que de fato
bloqueiam antes de chamar o provedor: plataforma (STUDIO_MONTHLY_CAP_USD), agente/dia, missão (orçamento) e workspace."""

from __future__ import annotations

import dataclasses
import json
import time

import pytest

from studio import paid_gate
from studio.accounts import Accounts
from studio.agent_chat import FALLBACK, AgentChat, anthropic_caller
from studio.db import Database
from studio.ffmpeg import FFmpeg
from studio.orchestrator import Orchestrator
from studio.providers.gemini import GeminiImageGenerator, GeminiPlanner
from studio.providers.simulated import SimulatedPlanner, SimulatedReviewer, SimulatedVideoGenerator, SimulationScript
from studio.states import ProductionStatus as PS

from .conftest import FAKE_KEY
from .test_upload_demo_spend import FORM, FakeRealImages, app, png_data_url, post  # noqa: F401 (fixture app)

GATE_VARS = ("STUDIO_ENV", "STUDIO_KILL_SWITCH", "STUDIO_ALLOW_PAID_CALLS", "STUDIO_MONTHLY_CAP_USD",
             "STUDIO_AGENT_DAILY_CAP_USD", "STUDIO_SECURE_COOKIE")


@pytest.fixture(autouse=True)
def clean_gate_env(monkeypatch):
    for v in GATE_VARS:
        monkeypatch.delenv(v, raising=False)


def real_orch(settings, tmp_path, **overrides):
    s = dataclasses.replace(settings, mode="real", allow_paid_calls=True, monthly_cap_usd=50, **overrides)
    ff = FFmpeg(s.ffmpeg_bin, s.ffprobe_bin, s.font_file, "ultrafast")
    script = SimulationScript()
    return Orchestrator(s, Database(s.db_path), image_gen=FakeRealImages(s.data_dir, s.image_model, script),
                        video_gen=SimulatedVideoGenerator(s.data_dir, s.video_model, ff, script),
                        planner=SimulatedPlanner(), reviewer=SimulatedReviewer(script), ffmpeg=ff,
                        sleep=lambda _: None, base_dir=tmp_path)


def new_production(orch, product, budget=50.0, workspace_id=None):
    return orch.create_production(product, format_id="maos_3cenas_15s", art_direction="cozinha_sp_alto_padrao",
                                  presenter="bia", budget_usd=budget, workspace_id=workspace_id)


def run_two_images(orch, pid):
    """Cena 1 sai primeiro; aprovada, as outras imagens pedem novas chamadas pagas."""
    orch.run(pid)
    if orch.db.production(pid)["status"] == PS.PAUSED:
        return
    orch.approve(pid, 1, "image")
    orch.run(pid)


def paused_reason(orch, pid):
    p = orch.db.production(pid)
    assert p["status"] == PS.PAUSED
    return p["status_reason"]


# ------------------------------------------------------------------ portão
@pytest.mark.parametrize("env,allow,cap,kill,expected", [
    ("dev", None, None, None, None),                      # dev sem variável: decide o workspace/CLI, como antes
    ("dev", "0", None, None, "disabled"),                 # 0 explícito desliga até em dev
    ("staging", None, "100", None, "disabled"),           # padrão 0 em staging
    ("production", None, "100", None, "disabled"),        # e em produção
    ("staging", "1", None, None, "no_platform_cap"),      # liberado, mas sem teto da plataforma: continua fechado
    ("production", "1", "100", None, None),
    ("staging", "1", "100", "1", "kill_switch"),          # kill switch vence tudo
    ("dev", "1", "100", "1", "kill_switch"),
    ("qualquer", None, "100", None, "disabled"),          # STUDIO_ENV estranho = o mais fechado
])
def test_gate_defaults(monkeypatch, env, allow, cap, kill, expected):
    monkeypatch.setenv("STUDIO_ENV", env)
    for name, value in (("STUDIO_ALLOW_PAID_CALLS", allow), ("STUDIO_MONTHLY_CAP_USD", cap), ("STUDIO_KILL_SWITCH", kill)):
        if value is not None:
            monkeypatch.setenv(name, value)
    assert paid_gate.blocked_reason() == expected


# --------------------------------------------------------- Gemini (orquestrador e adaptador)
def test_kill_switch_pauses_before_any_gemini_call_and_resumes_after(settings, product, tmp_path, monkeypatch):
    orch = real_orch(settings, tmp_path)
    pid = new_production(orch, product)
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    orch.run(pid)
    assert paused_reason(orch, pid) == paid_gate.MESSAGES["kill_switch"]
    assert "Nada foi cobrado" in paid_gate.MESSAGES["kill_switch"]
    assert orch.image_gen.submit_count == 0 and not [a for a in orch.db.attempts(pid) if not a["simulated"]]
    monkeypatch.delenv("STUDIO_KILL_SWITCH")
    orch.resume(pid)
    orch.run(pid)
    assert orch.image_gen.submit_count == 1


@pytest.mark.parametrize("env,reason", [("staging", "disabled"), ("production", "disabled")])
def test_staging_and_production_default_to_no_paid_calls(settings, product, tmp_path, monkeypatch, env, reason):
    monkeypatch.setenv("STUDIO_ENV", env)
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "100")
    orch = real_orch(settings, tmp_path)
    pid = new_production(orch, product)
    orch.run(pid)
    assert paused_reason(orch, pid) == paid_gate.MESSAGES[reason] and orch.image_gen.submit_count == 0


def test_gemini_adapters_refuse_before_opening_a_client(monkeypatch):
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    gen, planner = GeminiImageGenerator(FAKE_KEY, "m"), GeminiPlanner(FAKE_KEY, "m")
    with pytest.raises(paid_gate.PaidCallsBlocked):
        gen._create(input=[])
    with pytest.raises(paid_gate.PaidCallsBlocked):
        planner._ask_json([])
    assert gen._c is None and planner._c is None   # nem o cliente do SDK foi criado


# ---------------------------------------------------------------- tetos
def test_platform_monthly_cap_blocks(settings, product, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "0.07")    # cabe uma imagem; o teto do workspace/CLI é 50
    orch = real_orch(settings, tmp_path)
    pid = new_production(orch, product)
    run_two_images(orch, pid)
    assert paused_reason(orch, pid) == paid_gate.MESSAGES["platform_cap"]
    assert orch.image_gen.submit_count == 1


def test_platform_cap_counts_other_workspaces_and_chat(settings, product, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "0.5")
    orch = real_orch(settings, tmp_path)
    orch.db.conn.execute("INSERT INTO chat_log(user_id, workspace_id, agent, at, source, cost_usd) VALUES "
                         "('u', 'ws_outro', 'theo', ?, 'llm', 0.6)", (time.time(),))
    pid = new_production(orch, product)
    orch.run(pid)
    assert paused_reason(orch, pid) == paid_gate.MESSAGES["platform_cap"] and orch.image_gen.submit_count == 0


def _workspace(orch, cap=50.0):
    acc = Accounts(orch.db)
    _, wid = acc.create_user("dona@exemplo.com", "senha-forte-123")
    acc.set_workspace(wid, monthly_cap_usd=cap, credits_exempt=1, allow_real=1, mode="real")
    return wid


def test_agent_daily_cap_blocks(settings, product, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_AGENT_DAILY_CAP_USD", "0.07")   # Iris (imagens) pode gastar uma imagem por dia
    orch = real_orch(settings, tmp_path)
    wid = _workspace(orch)
    pid = new_production(orch, product, workspace_id=wid)
    run_two_images(orch, pid)
    assert paused_reason(orch, pid) == paid_gate.MESSAGES["agent_cap"]
    assert orch.image_gen.submit_count == 1
    from studio.spend import agent_day_spend
    assert 0 < agent_day_spend(orch.db, wid, "iris") <= 0.07 and agent_day_spend(orch.db, wid, "lia") == 0


def test_mission_budget_blocks(settings, product, tmp_path):
    orch = real_orch(settings, tmp_path)
    pid = new_production(orch, product, budget=0.07)
    run_two_images(orch, pid)
    assert "orçamento insuficiente" in paused_reason(orch, pid) and orch.image_gen.submit_count == 1


def test_workspace_monthly_cap_blocks(settings, product, tmp_path):
    orch = real_orch(settings, tmp_path)
    wid = _workspace(orch, cap=0.07)
    pid = new_production(orch, product, workspace_id=wid)
    run_two_images(orch, pid)
    assert "teto mensal atingido" in paused_reason(orch, pid) and orch.image_gen.submit_count == 1


# ---------------------------------------------------------------- Anthropic (chat)
class Model:
    def __init__(self):
        self.calls = []

    def __call__(self, req, timeout):
        self.calls.append(req)
        return {"text": "Tô montando a cena 1.", "input_tokens": 400, "output_tokens": 40, "cache_read_tokens": 0}


def _chat(db, model, agent="theo", text="me conta como fica a luz da cena dois"):
    user = f"u{len(model.calls)}_{agent}_{time.perf_counter_ns()}"   # usuário novo: sem cooldown entre os pedidos
    return AgentChat(model).reply(db.conn, user_id=user, workspace_id="ws_1", agent=agent, text=text, ctx={})


def test_kill_switch_blocks_anthropic_with_friendly_message(settings, monkeypatch):
    db = Database(settings.db_path)
    model = Model()
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    res = _chat(db, model)
    assert res["source"] == "sem_ia" and res["reply"] == FALLBACK["paused"] and res["ai"] is False
    assert not model.calls
    with pytest.raises(paid_gate.PaidCallsBlocked):
        anthropic_caller({}, 1.0)   # trava final, antes até de importar o SDK
    monkeypatch.delenv("STUDIO_KILL_SWITCH")
    assert _chat(db, model, text="e a trilha, vai ser animada?")["source"] == "llm" and len(model.calls) == 1


def test_staging_default_keeps_chat_without_ai(settings, monkeypatch):
    db = Database(settings.db_path)
    monkeypatch.setenv("STUDIO_ENV", "staging")
    model = Model()
    assert _chat(db, model)["source"] == "sem_ia" and not model.calls


def test_agent_and_platform_caps_block_chat(settings, monkeypatch):
    db = Database(settings.db_path)
    model = Model()
    monkeypatch.setenv("STUDIO_AGENT_DAILY_CAP_USD", "0.001")
    db.conn.execute("INSERT INTO chat_log(user_id, workspace_id, agent, at, source, cost_usd) VALUES "
                    "('u0', 'ws_1', 'theo', ?, 'llm', 0.001)", (time.time(),))
    assert _chat(db, model, agent="theo")["reply"] == FALLBACK["paused"] and not model.calls
    assert _chat(db, model, agent="iris")["source"] == "llm"          # outro agente tem o próprio teto
    monkeypatch.setenv("STUDIO_MONTHLY_CAP_USD", "0.0005")              # plataforma já passou do teto
    assert _chat(db, model, agent="lia")["reply"] == FALLBACK["paused"] and len(model.calls) == 1


# ---------------------------------------------------------------- interface
def test_ui_warns_and_refuses_real_production_while_blocked(app, monkeypatch):  # noqa: F811
    assert post(app, "/api/runtime", {"monthly_cap_usd": 10, "mode": "real"}).status == 200
    monkeypatch.setenv("STUDIO_KILL_SWITCH", "1")
    r = post(app, "/api/productions", {**FORM, "files": [{"name": "f.png", "data": png_data_url(), "role": "front"}],
                                       "start": False})
    body = json.loads(r.body)
    assert r.status == 409 and body["error"] == paid_gate.MESSAGES["kill_switch"] and body["paid_calls_blocked"]
    me = json.loads(app.handle("GET", "/api/me", {"Host": "127.0.0.1:8765", "Cookie": app_cookie(app)}, b"").body)
    assert me["paid_calls"] == {"blocked": True, "message": paid_gate.MESSAGES["kill_switch"]}
    assert post(app, "/api/runtime", {"mode": "real"}).status == 409
    assert post(app, "/api/runtime", {"mode": "simulated"}).status == 200   # voltar ao DEMO sempre funciona


def app_cookie(app):
    from .test_upload_demo_spend import HOST
    return HOST["Cookie"]
