import dataclasses
import json
import time

import pytest

from studio import agent_config
from studio.config import load_settings
from studio.states import ProductionStatus as PS
from studio.web.server import App
from studio.web.view import event_agent

from .conftest import login_app, FAKE_KEY, create, requires_ffmpeg

HOST = {"Host": "127.0.0.1:8765"}


@pytest.fixture
def app(settings, tmp_path):
    loader = lambda: dataclasses.replace(  # noqa: E731
        load_settings(env_file=tmp_path / "none.env", mode="simulated", data_dir=settings.data_dir,
                      assets_dir=settings.assets_dir, profiles_dir=settings.profiles_dir, x264_preset="ultrafast"))
    a = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(a, HOST)
    return a


def post(app, path, body=None, token=True):
    headers = {**HOST, **({"X-Studio-Token": app.token} if token else {})}
    return app.handle("POST", path, headers, json.dumps(body or {}).encode())


def wait_idle(app, pid, timeout=60):
    end = time.time() + timeout
    while app.is_running(pid) and time.time() < end:
        time.sleep(0.1)


def test_index_embeds_token_and_rejects_foreign_host(app):
    r = app.handle("GET", "/painel", HOST, b"")  # painel administrativo leva o token embutido
    assert r.status == 200 and app.token.encode() in r.body
    assert app.handle("GET", "/", {"Host": "evil.example:8765"}, b"").status == 403


def test_game_is_served_and_assets_are_confined(app):
    from studio.web.server import GAME_DIST
    r = app.handle("GET", "/", HOST, b"")
    assert r.status == 200
    if (GAME_DIST / "index.html").is_file():
        assert b'id="root"' in r.body and app.token.encode() not in r.body  # o jogo pede o token via /api/session
    for bad in ("/assets/../../pyproject.toml", "/assets/..%2F..%2Fpyproject.toml", "/assets/nao-existe.js"):
        assert app.handle("GET", bad, HOST, b"").status == 404


def test_post_requires_token(app):
    assert post(app, "/api/demo", token=False).status == 403
    assert post(app, "/api/config", {"settings": {"max_image_attempts": 2}}, token=False).status == 403


def test_state_never_exposes_api_key(app, make_orch, product):
    orch = make_orch()
    create(orch, product)
    r = app.handle("GET", "/api/state", HOST, b"")
    assert r.status == 200
    assert FAKE_KEY.encode() not in r.body
    data = json.loads(r.body)
    assert data["settings"]["api_key_defined"] in (True, False)
    assert {a["id"] for a in data["agents"]} == agent_config.AGENT_IDS


def test_config_validation_and_persistence(app, settings):
    ok = post(app, "/api/config", {"settings": {"image_model": "gemini-3-pro-image", "image_size": "4K",
                                                "max_image_attempts": 2},
                                   "agents": {"images": {"name": "Luna", "color": "#123abc"}}})
    assert ok.status == 200
    s = app.settings()
    assert (s.image_model, s.image_size, s.max_image_attempts) == ("gemini-3-pro-image", "4K", 2)
    assert next(a for a in agent_config.agents_with_overrides(settings.data_dir) if a["id"] == "images")["name"] == "Luna"
    # valores inválidos ou campos sensíveis são recusados
    for bad in ({"image_size": "8K"}, {"max_image_attempts": 99}, {"mode": "real"}, {"allow_paid_calls": True},
                {"gemini_api_key": "x"}):
        assert post(app, "/api/config", {"settings": bad}).status == 400
    assert post(app, "/api/config", {"agents": {"images": {"color": "red"}}}).status == 400
    assert post(app, "/api/config", {"agents": {"hacker": {"name": "x"}}}).status == 400


def test_media_is_confined_to_production(app, make_orch, product):
    orch = make_orch()
    pid = create(orch, product)
    orch.run(pid)
    att = orch.db.attempt(orch.db.scene(pid, 1)["current_image_attempt"])
    url = f"/media/{pid}/{att['output_path']}"
    assert app.handle("GET", url, HOST, b"").status == 404  # produção sem dono não é servida a ninguém
    wid = json.loads(app.handle("GET", "/api/me", HOST, b"").body)["workspace"]["id"]
    orch.db.update_production(pid, workspace_id=wid)
    assert app.handle("GET", url, HOST, b"").file is not None
    for path in (f"/media/{pid}/../../studio.sqlite3", f"/media/{pid}/..%2F..%2Fstudio.sqlite3", "/media/prod_x/a.png",
                 f"/media/{pid}/profiles_snapshot.json.exe"):
        assert app.handle("GET", path, HOST, b"").status in (400, 404)


@requires_ffmpeg
def test_demo_and_approvals_through_api(app):
    r = post(app, "/api/demo", {"budget": 5})
    pid = json.loads(r.body)["pid"]
    wait_idle(app, pid)
    state = json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)
    assert state["production"]["mode"] == "simulated"
    assert state["agent_states"]["operator"]["status"] == "needs_you"
    assert post(app, f"/api/productions/{pid}/reject", {"scene": 1, "stage": "image", "note": ""}).status == 400
    assert post(app, f"/api/productions/{pid}/approve", {"scene": 1, "stage": "image"}).status == 200
    wait_idle(app, pid)
    for _ in range(6):
        state = json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)
        if state["production"]["status"] == PS.AWAITING_FINAL_REVIEW:
            break
        for sc in state["production"]["scenes"]:
            if sc["status"] in ("awaiting_image_approval", "awaiting_video_approval"):
                stage = "image" if sc["status"] == "awaiting_image_approval" else "video"
                assert post(app, f"/api/productions/{pid}/approve", {"scene": sc["idx"], "stage": stage}).status == 200
                wait_idle(app, pid)
    assert state["production"]["status"] == PS.AWAITING_FINAL_REVIEW
    assert state["production"]["delivery"]["final.mp4"].endswith("final.mp4")
    assert post(app, f"/api/productions/{pid}/final", {"decision": "approve"}).status == 200
    state = json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)
    assert state["production"]["status"] == PS.COMPLETED


def test_event_attribution():
    def ev(type_, msg="", to=None):
        return {"type": type_, "message": msg, "to_state": to}
    assert event_agent(ev("attempt_submitted", "image #1 enviado")) == "images"
    assert event_agent(ev("attempt_created", "video #2 (gemini-api/x)")) == "videos"
    assert event_agent(ev("review", "image human: approved")) == "operator"
    assert event_agent(ev("review", "image auto:simulated:none: inconclusive")) == "review"
    assert event_agent(ev("production_status", "", "awaiting_references")) == "prep"
    assert event_agent(ev("scene_status", "", "generating_video")) == "videos"


def test_frontend_script_parses(tmp_path):
    """Pega erros de sintaxe no JavaScript da interface (exige Node.js instalado)."""
    import re
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não instalado")
    html = (Path(__file__).parents[1] / "src/studio/web/static/index.html").read_text(encoding="utf-8")
    script = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    f = tmp_path / "ui.mjs"
    f.write_text("export {};\n" + script, encoding="utf-8")
    proc = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_minigame_rules():
    """Regras da Velha e das Damas brasileiras (frontend/tests/minigames.test.mjs, exige Node.js)."""
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js não instalado")
    root = Path(__file__).parents[1] / "frontend"
    module = (root / "src" / "game" / "minigames.js").resolve().as_uri()
    proc = subprocess.run([node, str(root / "tests" / "minigames.test.mjs"), module], capture_output=True, text=True)
    assert proc.returncode == 0 and "regras ok" in proc.stdout, proc.stderr
