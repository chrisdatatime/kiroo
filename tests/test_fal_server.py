"""Servidor: criacao do fluxo fal.ai (foto + estilo + id do cliente), estado, galeria e download individual com a mesma
autorizacao por workspace. Tudo em DEMO (workflow simulado): nenhuma rede, nenhum custo."""

from __future__ import annotations

import base64
import json
import time

import pytest

from studio.config import load_settings
from studio.providers.simulated import placeholder_png
from studio.web.server import App

from .conftest import login_app, requires_ffmpeg

HOST = {"Host": "127.0.0.1:8765"}
PNG = "data:image/png;base64," + base64.b64encode(placeholder_png("x", 540, 960)).decode()
BODY = {"style": "light", "client_request_id": "cliente-0001", "files": [{"name": "foto.png", "data": PNG}]}


@pytest.fixture
def app(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_VIDEO_ENGINE", "fal")

    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    a = App(8765, settings_loader=loader, sim_pacing=False)
    login_app(a, HOST)
    return a


def post(app, path, body=None, host=None):
    r = app.handle("POST", path, {**(host or HOST), "X-Studio-Token": app.token}, json.dumps(body or {}).encode())
    return r.status, json.loads(r.body)


def get(app, path, host=None):
    return app.handle("GET", path, host or HOST, b"")


def wait_idle(app, pid, timeout=60):
    end = time.time() + timeout
    while app.is_running(pid) and time.time() < end:
        time.sleep(0.05)


def state(app, pid):
    return json.loads(get(app, f"/api/state?pid={pid}").body)


def test_engine_comes_from_the_global_setting_and_the_workspace_overrides_it(app):
    assert state(app, "prod_0000000000")["settings"]["video_engine"] == "fal"
    s, db, acc = app._db()
    try:
        wid = acc.workspaces_of(acc.user_by_email("chris@example.com")["id"])[0]["id"]
        acc.set_workspace(wid, video_engine="gemini")
    finally:
        db.close()
    d = state(app, "prod_0000000000")["settings"]
    assert d["video_engine"] == "gemini" and [x["id"] for x in d["fal_styles"]] == ["light"]
    with pytest.raises(Exception):
        s, db, acc = app._db()
        try:
            acc.set_workspace(wid, video_engine="outro")
        finally:
            db.close()


@requires_ffmpeg
def test_create_run_gallery_and_individual_downloads(app):
    code, d = post(app, "/api/productions", BODY)
    assert code == 200 and d["ok"] and d["duplicate"] is False
    pid = d["pid"]
    wait_idle(app, pid)
    P = state(app, pid)["production"]
    assert P["engine"] == "fal" and P["style"] == "light" and P["status"] == "awaiting_final_review"
    assert P["delivery_status"] == "complete" and P["scenes"] == [] and P["fal"]["finalizing"] is False
    assert (P["fal"]["image"]["role"], P["fal"]["image"]["label"]) == ("hero", "Hero Shot") and P["fal"]["image"]["url"]
    assert set(P["delivery"]) == {"final.mp4", "product_image_01.jpg", "cover.jpg", "caption.txt"}
    assert P["confirmation"]["required"] is False                      # DEMO: sem custo
    plain = get(app, P["delivery"]["final.mp4"])
    assert plain.status == 200 and "Content-Disposition" not in plain.headers
    for name in ("final.mp4", "product_image_01.jpg"):
        r = get(app, P["delivery"][name] + "?download=1")
        assert r.status == 200 and r.headers["Content-Disposition"] == f'attachment; filename="{name}"'
        assert r.headers["Cache-Control"] == "private, no-store"


@requires_ffmpeg
def test_download_is_denied_to_other_workspaces(app):
    pid = post(app, "/api/productions", BODY)[1]["pid"]
    wait_idle(app, pid)
    url = f"/media/{pid}/delivery/product_image_01.jpg?download=1"
    assert get(app, url).status == 200
    other: dict = {}
    login_app(app, other, email="outra@example.com")
    assert get(app, url, other).status == 404
    assert get(app, f"/media/{pid}/delivery/final.mp4", other).status == 404
    assert get(app, f"/media/{pid}/delivery/../inputs/x.png?download=1", other).status == 404
    assert get(app, url, {"Host": HOST["Host"]}).status in (401, 302)       # sem sessao


@requires_ffmpeg
def test_double_click_is_one_production(app):
    r1 = post(app, "/api/productions", BODY)[1]
    r2 = post(app, "/api/productions", BODY)[1]
    assert r1["pid"] == r2["pid"] and r2["duplicate"] is True
    wait_idle(app, r1["pid"])
    assert len(state(app, r1["pid"])["productions"]) == 1
    r3 = post(app, "/api/productions", {**BODY, "client_request_id": "cliente-0002"})[1]
    assert r3["pid"] != r1["pid"] and r3["duplicate"] is False            # refacao: outra execucao
    wait_idle(app, r3["pid"])


@pytest.mark.parametrize("patch,msg", [({"style": "neon"}, "Escuro ou Claro"), ({"style": "dark"}, "Use o estilo Claro"),
                                       ({"client_request_id": "curto"}, "identificador"),
                                       ({"client_request_id": "tem espaco e / barra"}, "identificador"),
                                       ({"files": []}, "exatamente uma foto"),
                                       ({"files": [{"name": "a.png", "data": PNG}, {"name": "b.png", "data": PNG}]},
                                        "exatamente uma foto"),
                                       ({"files": [{"name": "video.mp4", "data": PNG}]}, "exatamente uma foto")])
def test_invalid_creation_is_refused_before_anything_is_saved(app, patch, msg):
    code, d = post(app, "/api/productions", {**BODY, **patch})
    assert code == 400 and msg in d["error"]
    assert not (app.settings().data_dir / "uploads").exists() or not list((app.settings().data_dir / "uploads").iterdir())
    assert state(app, "prod_0000000000")["productions"] == []


def test_only_the_light_style_is_offered_and_it_is_the_default(app):
    assert [x["id"] for x in state(app, "prod_0000000000")["settings"]["fal_styles"]] == ["light"]
    code, d = post(app, "/api/productions", {k: v for k, v in BODY.items() if k != "style"})      # sem estilo: Claro
    assert code == 200
    wait_idle(app, d["pid"])
    assert state(app, d["pid"])["production"]["style"] == "light"


def test_dark_is_ready_but_off_until_the_flag_is_turned_on(app, monkeypatch):
    code, d = post(app, "/api/productions", {**BODY, "style": "dark"})
    assert code == 400 and "Claro" in d["error"]
    monkeypatch.setenv("STUDIO_FAL_DARK_ENABLED", "true")
    assert [x["id"] for x in state(app, "prod_0000000000")["settings"]["fal_styles"]] == ["dark", "light"]
    code, d = post(app, "/api/productions", {**BODY, "style": "dark", "client_request_id": "cliente-dark1"})
    assert code == 200
    wait_idle(app, d["pid"])
    assert state(app, d["pid"])["production"]["style"] == "dark"


def test_a_wrong_extension_with_png_bytes_is_still_refused(app):
    code, d = post(app, "/api/productions", {**BODY, "files": [{"name": "foto.png", "data": "data:image/png;base64,AAAA"}]})
    assert code == 400


def test_gemini_workspace_keeps_the_old_creation_flow(app):
    s, db, acc = app._db()
    try:
        wid = acc.workspaces_of(acc.user_by_email("chris@example.com")["id"])[0]["id"]
        acc.set_workspace(wid, video_engine="gemini")
    finally:
        db.close()
    code, d = post(app, "/api/productions", {"name": "Copo", "variant": "azul", "flow": "game", "start": False,
                                             "files": [{"name": "f.png", "data": PNG, "role": "front"}]})
    assert code == 200 and "duplicate" not in d
    row = state(app, d["pid"])["production"]
    assert row["engine"] == "gemini" and row["fal"] is None
