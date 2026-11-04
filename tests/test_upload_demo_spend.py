import base64
import dataclasses
import json
import time

import pytest

from studio import agent_config
from studio.config import load_settings
from studio.db import Database
from studio.ffmpeg import FFmpeg
from studio.orchestrator import Orchestrator
from studio.providers.simulated import (SimulatedImageGenerator, SimulatedPlanner, SimulatedReviewer,
                                        SimulatedVideoGenerator, SimulationScript, placeholder_png)
from studio.spend import month_real_spend, spend_report
from studio.states import ProductionStatus as PS
from studio.web.server import App

from .conftest import login_app, create

HOST = {"Host": "127.0.0.1:8765"}


def png_data_url(seed="x"):
    return "data:image/png;base64," + base64.b64encode(placeholder_png(seed, 90, 160)).decode()


@pytest.fixture
def app(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    a = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(a, HOST)
    return a


def post(app, path, body):
    return app.handle("POST", path, {**HOST, "X-Studio-Token": app.token}, json.dumps(body).encode())


def wait_idle(app, pid, timeout=30):
    end = time.time() + timeout
    while app.is_running(pid) and time.time() < end:
        time.sleep(0.05)


FORM = {
    "name": "Copo com alça", "variant": "azul-claro", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j",
    "visual_attributes": "cor: azul-claro\nalça: lateral", "verified": "cor: azul-claro",
    "seller_claims": "capacidade: 500 ml", "video_context": "Destacar a alça; clima de manhã tranquila.",
    "budget": 5,
}


# ------------------------------------------------------------ chave DEMO
def test_demo_toggle_requires_key_and_cap(settings, monkeypatch):
    d = settings.data_dir
    with pytest.raises(ValueError, match="teto"):
        agent_config.save_runtime(d, mode="real", api_key_defined=True, current_cap=0)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        agent_config.save_runtime(d, mode="real", monthly_cap_usd=10, api_key_defined=False, current_cap=0)
    agent_config.save_runtime(d, mode="real", monthly_cap_usd=10, api_key_defined=True, current_cap=0)
    s = load_settings(env_file=d / "none.env", data_dir=d)
    assert (s.mode, s.allow_paid_calls, s.monthly_cap_usd) == ("real", True, 10.0)
    agent_config.save_runtime(d, mode="simulated", api_key_defined=True, current_cap=10)
    s = load_settings(env_file=d / "none.env", data_dir=d)
    assert (s.mode, s.allow_paid_calls) == ("simulated", False)


def test_real_production_is_frozen_while_demo_is_on(app, settings):
    # modo e teto agora são do workspace (a primeira conta é a do administrador, liberada para o modo real)
    assert post(app, "/api/runtime", {"monthly_cap_usd": 10, "mode": "real"}).status == 200
    r = post(app, "/api/productions", {**FORM, "files": [{"name": "f.png", "data": png_data_url(), "role": "front"}],
                                       "start": False})
    assert r.status == 200 and json.loads(r.body)["mode"] == "real"
    pid = json.loads(r.body)["pid"]
    assert post(app, "/api/runtime", {"mode": "simulated"}).status == 200
    resp = post(app, f"/api/productions/{pid}/run", {})
    assert resp.status == 400 and "DEMO" in json.loads(resp.body)["error"]


# ------------------------------------------------------------- teto mensal
class FakeRealImages(SimulatedImageGenerator):
    """Comporta-se como o adaptador real: a API não informa custo confirmado."""

    provider = "fake-real"
    simulated = False

    def poll(self, op_id):
        result = super().poll(op_id)
        result.confirmed_cost_usd = None
        return result


class FakeRealPlanner(SimulatedPlanner):
    simulated = False


def test_monthly_cap_pauses_before_paid_call(settings, product, tmp_path):
    s = dataclasses.replace(settings, mode="real", allow_paid_calls=True, monthly_cap_usd=0.07)
    ff = FFmpeg(s.ffmpeg_bin, s.ffprobe_bin, s.font_file, "ultrafast")
    script = SimulationScript()
    orch = Orchestrator(s, Database(s.db_path), image_gen=FakeRealImages(s.data_dir, s.image_model, script),
                        video_gen=SimulatedVideoGenerator(s.data_dir, s.video_model, ff, script),
                        planner=SimulatedPlanner(), reviewer=SimulatedReviewer(script), ffmpeg=ff,
                        sleep=lambda _: None, base_dir=tmp_path)
    pid = create(orch, product, budget=50)  # orçamento da produção folgado; o teto do mês é que limita
    orch.run(pid)
    orch.approve(pid, 1, "image")
    orch.run(pid)
    prod = orch.db.production(pid)
    assert prod["status"] == PS.PAUSED and "teto mensal" in prod["status_reason"]
    assert orch.image_gen.submit_count == 1
    assert 0 < month_real_spend(orch.db) <= 0.07
    report = spend_report(orch.db, s.monthly_cap_usd)
    assert report["month_total_usd"] == month_real_spend(orch.db)
    assert report["by_kind"][0]["kind"] == "Imagens"
    assert report["by_production"][0]["id"] == pid
    assert sum(d["usd"] for d in report["daily"]) == pytest.approx(report["all_time_real_usd"])


def test_real_without_monthly_cap_never_spends(settings, product, tmp_path):
    s = dataclasses.replace(settings, mode="real", allow_paid_calls=True, monthly_cap_usd=0)
    ff = FFmpeg(s.ffmpeg_bin, s.ffprobe_bin, s.font_file, "ultrafast")
    orch = Orchestrator(s, Database(s.db_path), image_gen=FakeRealImages(s.data_dir, s.image_model),
                        video_gen=SimulatedVideoGenerator(s.data_dir, s.video_model, ff), planner=SimulatedPlanner(),
                        reviewer=SimulatedReviewer(), ffmpeg=ff, sleep=lambda _: None, base_dir=tmp_path)
    pid = create(orch, product, budget=50)
    orch.run(pid)
    assert orch.db.production(pid)["status"] == PS.PAUSED
    assert orch.image_gen.submit_count == 0


# ------------------------------------------------------------- upload
def test_create_production_with_uploaded_photos_and_context(app, settings):
    files = [{"name": "frente.png", "data": png_data_url("a"), "role": "front", "source": "official_listing"},
             {"name": "lado.PNG", "data": png_data_url("b"), "role": "side", "source": "own_photo"}]
    r = post(app, "/api/productions", {**FORM, "files": files})
    assert r.status == 200, r.body
    pid = json.loads(r.body)["pid"]
    wait_idle(app, pid)
    db = Database(settings.db_path)
    try:
        sheet = json.loads(db.production(pid)["sheet_json"])
        assert [r["role"] for r in sheet["product"]["references"]] == ["front", "side"]
        kinds = {c["kind"] for c in sheet["product"]["claims"]}
        assert kinds == {"verified", "seller_claim"}
        script = json.loads(db.production(pid)["script_json"])
        assert "Destacar a alça" in script["scenes"][0]["image_prompt"]
        assert "OPERATOR CREATIVE DIRECTION" in script["scenes"][0]["animation_prompt"]
    finally:
        db.close()
    assert len(list((settings.data_dir / "uploads").rglob("*.png"))) == 2


@pytest.mark.parametrize("files, msg", [
    ([{"name": "x.png", "data": base64.b64encode(b"not a png").decode(), "role": "front"}], "assinatura|corresponde"),
    ([{"name": "x.exe", "data": "AAAA", "role": "front"}], "não aceito"),
    ([{"name": "x.png", "data": "%%%", "role": "front"}], "corrompido"),
    ([{"name": "x.png", "data": png_data_url(), "role": "hacker"}], "inválido"),
])
def test_bad_uploads_are_rejected(app, files, msg):
    import re
    r = post(app, "/api/productions", {**FORM, "files": files})
    assert r.status == 400 and re.search(msg, json.loads(r.body)["error"])


def test_bad_link_rejected_and_no_production_created(app, settings):
    r = post(app, "/api/productions", {**FORM, "affiliate_link": "https://evil.example/x",
                                       "files": [{"name": "f.png", "data": png_data_url(), "role": "front"}]})
    assert r.status == 400
    db = Database(settings.db_path)
    assert db.productions() == []
    db.close()


def test_add_references_unblocks_production(app, settings):
    r = post(app, "/api/productions", {**FORM, "files": []})
    pid = json.loads(r.body)["pid"]
    wait_idle(app, pid)
    state = json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)
    assert state["production"]["status"] == PS.AWAITING_REFERENCES
    assert any(i["blocking"] for i in state["production"]["sheet"]["issues"])
    r = post(app, f"/api/productions/{pid}/references",
             {"files": [{"name": "f.png", "data": png_data_url(), "role": "front"}]})
    assert r.status == 200
    wait_idle(app, pid)
    state = json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)
    assert state["production"]["status"] == PS.PRODUCING
    assert state["production"]["sheet"]["references"][0]["url"].startswith(f"/media/{pid}/")


def test_spend_endpoint(app):
    r = app.handle("GET", "/api/spend", HOST, b"")
    data = json.loads(r.body)
    assert r.status == 200 and len(data["daily"]) == 30 and "note" in data


def test_edit_attributes_and_context_of_existing_production(app, settings):
    r = post(app, "/api/productions", {**FORM, "files": [{"name": "f.png", "data": png_data_url(), "role": "front"}]})
    pid = json.loads(r.body)["pid"]
    wait_idle(app, pid)
    r = post(app, f"/api/productions/{pid}/references",
             {"files": [], "visual_attributes": "canudo: atravessa a tampa\ninscrição: vertical no corpo",
              "video_context": "Mostrar o canudo."})
    assert r.status == 200, r.body
    wait_idle(app, pid)
    state = json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)
    assert state["production"]["visual_attributes"] == {"canudo": "atravessa a tampa", "inscrição": "vertical no corpo"}
    assert state["production"]["video_context"] == "Mostrar o canudo."
    db = Database(settings.db_path)
    try:
        prompt = json.loads(db.production(pid)["script_json"])["scenes"][0]["image_prompt"]
        assert "canudo: atravessa a tampa" in prompt and "Mostrar o canudo." in prompt
    finally:
        db.close()
