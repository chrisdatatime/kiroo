import base64
import json
import sqlite3
import time

import pytest

from studio import billing
from studio.config import load_settings
from studio.db import Database
from studio.providers.simulated import placeholder_png
from studio.states import SceneStatus as SS
from studio.web.server import App

from .conftest import login_app, create, requires_ffmpeg

HOST = {"Host": "127.0.0.1:8765"}
PNG = "data:image/png;base64," + base64.b64encode(placeholder_png("x", 90, 160)).decode()
BASE = {"name": "Copo com alça", "variant": "azul-claro", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j",
        "budget": 10, "flow": "game", "start": False,
        "files": [{"name": "f.png", "data": PNG, "role": "front"}]}


@pytest.fixture
def app(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    a = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(a, HOST)
    return a


def post(app, path, body=None):
    r = app.handle("POST", path, {**HOST, "X-Studio-Token": app.token}, json.dumps(body or {}).encode())
    return r.status, json.loads(r.body)


def state(app, pid):
    return json.loads(app.handle("GET", f"/api/state?pid={pid}", HOST, b"").body)["production"]


def wait_idle(app, pid, timeout=40):
    end = time.time() + timeout
    while app.is_running(pid) and time.time() < end:
        time.sleep(0.05)


def test_paid_stages_wait_for_explicit_go_ahead(make_orch, product):
    orch = make_orch()
    pid = orch.create_production(product, format_id="maos_3cenas_15s", art_direction="cozinha_sp_alto_padrao",
                                 presenter="bia", budget_usd=10, go_ahead="none")
    orch.run(pid)
    assert orch.image_gen.submit_count == 0  # roteiro pronto, nenhuma geração paga
    assert all(s["status"] == SS.PENDING for s in orch.db.scenes(pid))
    orch.set_go_ahead(pid, "images")
    orch.run(pid)
    assert orch.image_gen.submit_count == 1
    from studio.orchestrator import OrchestratorError
    with pytest.raises(OrchestratorError):
        orch.set_go_ahead(pid, "none")  # não existe "desliberar"
    orch.set_go_ahead(pid, "images")    # repetir não muda nada
    assert orch.db.production(pid)["go_ahead"] == "images"


def test_legacy_database_is_migrated(tmp_path):
    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE productions (id TEXT PRIMARY KEY, status TEXT NOT NULL, resume_status TEXT, status_reason TEXT,"
                " mode TEXT NOT NULL, format_id TEXT NOT NULL, product_json TEXT NOT NULL, sheet_json TEXT, script_json TEXT,"
                " profiles_json TEXT NOT NULL, budget_usd REAL NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    con.execute("INSERT INTO productions VALUES ('prod_0123456789','completed',NULL,NULL,'real','f','{}',NULL,NULL,'{}',1,'t','t')")
    con.commit(); con.close()
    db = Database(path)
    assert db.production("prod_0123456789")["go_ahead"] == "all"  # produções antigas não ficam travadas
    db.close()


def test_credit_policy_rounds_up_and_is_provisional():
    pol = billing.CreditPolicy(fx_brl_per_usd=5.4, margin=3, credit_price_brl=1.0)
    assert pol.credits(1.0) == 17  # 16,2 → 17
    assert pol.credits(0) == 0
    assert "provisório" in pol.describe()


@requires_ffmpeg
def test_game_flow_through_api(app):
    status, data = post(app, "/api/productions", BASE)
    assert status == 200
    pid = data["pid"]
    assert state(app, pid)["status"] == "received" and state(app, pid)["go_ahead"] == "none"

    assert post(app, f"/api/productions/{pid}/validate")[1]["ok"] is True
    assert state(app, pid)["status"] == "validated"

    post(app, f"/api/productions/{pid}/direction", {"creative": {"presentation": "product_only", "environment": "sala"}})
    wait_idle(app, pid)
    p = state(app, pid)
    assert p["gate"] == "images" and p["status"] == "producing"
    assert p["estimates"]["images"]["credits"] > 0 and p["credits"]["spent"] == 0  # roteiro simulado não gasta

    post(app, f"/api/productions/{pid}/go_ahead", {"stage": "images"})
    wait_idle(app, pid)
    for _ in range(3):
        p = state(app, pid)
        for sc in p["scenes"]:
            if sc["status"] == "awaiting_image_approval":
                assert post(app, f"/api/productions/{pid}/approve", {"scene": sc["idx"], "stage": "image"})[0] == 200
                wait_idle(app, pid)
    p = state(app, pid)
    assert p["gate"] == "videos" and all(s["status"] == "image_approved" for s in p["scenes"])

    post(app, f"/api/productions/{pid}/go_ahead", {"stage": "videos"})
    wait_idle(app, pid)
    for _ in range(3):
        p = state(app, pid)
        for sc in p["scenes"]:
            if sc["status"] == "awaiting_video_approval":
                post(app, f"/api/productions/{pid}/approve", {"scene": sc["idx"], "stage": "video"})
                wait_idle(app, pid)
    p = state(app, pid)
    assert p["status"] == "awaiting_final_review" and p["caption"] and p["delivery"]["final.mp4"]


def test_me_requires_session_and_allowed_host(app):
    r = app.handle("GET", "/api/me", HOST, b"")
    assert r.status == 200 and json.loads(r.body)["csrf"] == app.token
    assert app.handle("GET", "/api/me", {"Host": "127.0.0.1:8765"}, b"").status == 401  # sem cookie
    assert app.handle("GET", "/api/me", {**HOST, "Host": "evil.example"}, b"").status == 403


# ------------------------------------------------------------------ autonomia (piloto)
from studio.models import ReviewDecision as RD  # noqa: E402
from studio.providers.simulated import SimulatedReviewer, SimulationScript  # noqa: E402


def _create_auto(orch, product, autonomy, go_ahead="all"):
    return orch.create_production(product, format_id="maos_3cenas_15s", art_direction="cozinha_sp_alto_padrao",
                                  presenter="bia", budget_usd=20, go_ahead=go_ahead, autonomy=autonomy)


def test_manual_never_retries_on_its_own(make_orch, product):
    orch = make_orch(SimulationScript(image_reviews=[RD.REJECTED] * 5))
    pid = _create_auto(orch, product, "manual")
    orch.run(pid)
    assert orch.image_gen.submit_count == 1  # reprovação do revisor vem para você
    assert orch.db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL


def test_assisted_approves_what_reviewer_approves_and_stops_on_doubt(make_orch, product):
    orch = make_orch(SimulationScript(image_reviews=[RD.APPROVED, RD.APPROVED, RD.INCONCLUSIVE]))
    pid = _create_auto(orch, product, "assistido")
    orch.run(pid)
    statuses = {s["idx"]: s["status"] for s in orch.db.scenes(pid)}
    assert statuses[1] != SS.AWAITING_IMAGE_APPROVAL  # aprovada pelo piloto, seguiu adiante
    assert SS.AWAITING_IMAGE_APPROVAL in statuses.values()  # a inconclusiva espera você
    assert any(r["reviewer"] == "piloto" for r in orch.db.reviews(pid))


@requires_ffmpeg
def test_automatic_runs_to_final_review_without_human(make_orch, product):
    orch = make_orch()
    pid = _create_auto(orch, product, "automatico")
    assert orch.run(pid) == "awaiting_final_review"  # revisão final continua sendo sua
    assert not any(r["reviewer"] == "human" for r in orch.db.reviews(pid))


def test_switching_to_assisted_releases_paid_stages(make_orch, product):
    orch = make_orch()
    pid = _create_auto(orch, product, "manual", go_ahead="none")
    orch.run(pid)
    assert orch.image_gen.submit_count == 0
    orch.set_autonomy(pid, "assistido")
    assert orch.db.production(pid)["go_ahead"] == "all"


class SlowRealReviewer(SimulatedReviewer):
    """Revisor 'real' (não simulado) que demora: a revisão deve rodar em paralelo, sem travar o laço."""
    simulated = False

    def review_image(self, spec, image, references):
        time.sleep(0.3)
        return super().review_image(spec, image, references)


def test_real_reviews_run_in_background(settings, product, tmp_path):
    import dataclasses
    from studio.db import Database
    from studio.orchestrator import Orchestrator
    from studio.ffmpeg import FFmpeg
    from studio.providers.simulated import SimulatedImageGenerator, SimulatedPlanner, SimulatedVideoGenerator
    s = dataclasses.replace(settings, poll_interval_s=0.0)
    ff = FFmpeg(s.ffmpeg_bin, s.ffprobe_bin, s.font_file, "ultrafast")
    orch = Orchestrator(s, Database(s.db_path), image_gen=SimulatedImageGenerator(s.data_dir, s.image_model),
                        video_gen=SimulatedVideoGenerator(s.data_dir, s.video_model, ff), planner=SimulatedPlanner(),
                        reviewer=SlowRealReviewer(), ffmpeg=ff, sleep=lambda _: time.sleep(0.05), base_dir=tmp_path)
    pid = _create_auto(orch, product, "classico")
    assert orch.run(pid, wait=False) == "producing"
    assert orch.db.scene(pid, 1)["status"] == SS.GENERATING_IMAGE  # revisão em andamento, laço não travou
    orch.run(pid)
    assert orch.db.scene(pid, 1)["status"] == SS.AWAITING_IMAGE_APPROVAL
    assert [a["kind"] for a in orch.db.attempts(pid, 1)].count("review_image") == 1


def test_resume_approves_scene_left_waiting_by_a_crash_between_review_and_approval(make_orch, product):
    """Regressão do travamento do kill -9: o processo morre depois de gravar a revisão e antes da aprovação do piloto.
    A cena fica em awaiting_* e, sem reconciliação, a produção ficava em `producing` com o laço ocioso para sempre."""
    orch = make_orch(SimulationScript(image_reviews=[RD.APPROVED] * 3))
    pid = _create_auto(orch, product, "manual")
    orch.run(pid)
    waiting = [s["idx"] for s in orch.db.scenes(pid) if s["status"] == SS.AWAITING_IMAGE_APPROVAL]
    assert waiting  # estado idêntico ao deixado pela morte: revisão automática gravada, aprovação não
    orch.db.update_production(pid, autonomy="assistido")  # sem set_autonomy: nada reconcilia a não ser o laço
    orch.run(pid)
    assert not any(s["status"] == SS.AWAITING_IMAGE_APPROVAL for s in orch.db.scenes(pid))
    assert orch._reconcile_autopilot(pid) == 0  # idempotente
