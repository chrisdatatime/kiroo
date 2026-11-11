"""Autorização: usuário A (workspace A) tentando ler, mudar, aprovar e baixar coisas do workspace B em todas as rotas
que recebem id; path traversal em /media, /assets e uploads; tipo real, tamanho e nome dos arquivos enviados."""

from __future__ import annotations

import base64
import json

import pytest

from studio.config import load_settings
from studio.db import Database
from studio.providers.simulated import placeholder_png
from studio.web import uploads
from studio.web.server import ACTIONS, App

from .conftest import login_app

PNG_RAW = placeholder_png("x", 90, 160)
PNG = "data:image/png;base64," + base64.b64encode(PNG_RAW).decode()
FORM = {"name": "Garrafa térmica B", "variant": "preta", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j",
        "budget": 5, "files": [{"name": "f.png", "data": PNG, "role": "front"}], "start": False}
# corpo plausível para cada ação (o bastante para a ação agir se a checagem de dono falhasse)
ACTION_BODY = {"approve": {"scene": 1, "stage": "image"}, "reject": {"scene": 1, "stage": "image", "note": "x"},
               "final": {"decision": "approve"}, "budget": {"value": 999}, "retry": {"scene": 1, "stage": "image"},
               "references": {"files": [{"name": "g.png", "data": PNG, "role": "side"}], "replace": True},
               "direction": {"creative": {}}, "go_ahead": {"stage": "images"}, "autonomy": {"mode": "manual"},
               "edit": {"style": "dinamico"}, "music": {"music": "none"}}


class Client:
    def __init__(self, app, email):
        self.app, self.h = app, {}
        self.me = login_app(app, self.h, email=email)
        self.token = app.token

    def get(self, path):
        return self.app.handle("GET", path, self.h, b"")

    def post(self, path, body=None):
        return self.app.handle("POST", path, {**self.h, "X-Studio-Token": self.token}, json.dumps(body or {}).encode())


@pytest.fixture
def world(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    app = App(8765, settings_loader=loader, sim_pacing=False)
    Client(app, "operador@exemplo.com")          # o primeiro do banco vira admin; A e B são contas comuns
    a, b = Client(app, "a@exemplo.com"), Client(app, "b@exemplo.com")
    assert not a.me["admin"] and not b.me["admin"] and a.me["workspace"]["id"] != b.me["workspace"]["id"]
    r = b.post("/api/productions", FORM)
    assert r.status == 200, r.body
    pid_b = json.loads(r.body)["pid"]
    r = a.post("/api/productions", {**FORM, "name": "Copo A"})
    pid_a = json.loads(r.body)["pid"]
    # B tem uma trilha própria e uma referência de treinamento
    wid_b = b.me["workspace"]["id"]
    db = Database(settings.db_path)
    try:
        (settings.data_dir / "music" / wid_b).mkdir(parents=True)
        (settings.data_dir / "music" / wid_b / "mus_b.mp3").write_bytes(b"ID3" + b"0" * 64)
        db.conn.execute("INSERT INTO music_tracks(id, workspace_id, title, file, authorized_at, created_at) "
                        "VALUES ('mus_b', ?, 'Trilha da B', 'mus_b.mp3', 'x', 'x')", (wid_b,))
    finally:
        db.close()
    r = b.post("/api/training/iris/ref", {"title": "Paleta da B", "text": "tons de verde-musgo"})
    assert r.status == 200
    ref_b = json.loads(r.body)["draft"]["refs"][0]["id"] if "draft" in json.loads(r.body) else None
    return {"app": app, "a": a, "b": b, "pid_a": pid_a, "pid_b": pid_b, "wid_b": wid_b, "ref_b": ref_b,
            "settings": settings}


def snapshot_b(w):
    db = Database(w["settings"].db_path)
    try:
        p = dict(db.production(w["pid_b"]))
        events = db.conn.execute("SELECT COUNT(*) FROM events WHERE production_id=?", (w["pid_b"],)).fetchone()[0]
        reviews = db.conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] if db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='reviews'").fetchone() else 0
        track = db.conn.execute("SELECT * FROM music_tracks WHERE id='mus_b'").fetchone()
        return p, events, reviews, dict(track) if track else None
    finally:
        db.close()


# ------------------------------------------------------------------ IDOR
def test_read_production_of_another_workspace(world):
    a, pid_b = world["a"], world["pid_b"]
    r = a.get(f"/api/state?pid={pid_b}")
    assert r.status == 200
    body = r.body.decode()
    assert pid_b not in body and "Garrafa térmica B" not in body
    assert world["b"].get(f"/api/state?pid={pid_b}").status == 200 and pid_b in world["b"].get(f"/api/state?pid={pid_b}").body.decode()


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_every_production_action_on_another_workspace_is_404_and_changes_nothing(world, action):
    before = snapshot_b(world)
    r = world["a"].post(f"/api/productions/{world['pid_b']}/{action}", ACTION_BODY.get(action, {}))
    assert r.status == 404, (action, r.body)
    assert snapshot_b(world) == before
    assert not world["app"].is_running(world["pid_b"])


def test_media_of_another_workspace_is_404(world):
    a, b, pid_b = world["a"], world["b"], world["pid_b"]
    assert b.get(f"/media/{pid_b}/inputs/product_input.json").status == 200   # a dona baixa
    for path in (f"/media/{pid_b}/inputs/product_input.json", f"/media/{pid_b}/profiles_snapshot.json"):
        r = a.get(path)
        assert r.status == 404 and r.file is None


def test_chat_does_not_leak_mission_of_another_workspace(world):
    seen = []
    world["app"].chat._caller = lambda req, timeout: seen.append(req) or {"text": "ok", "input_tokens": 1, "output_tokens": 1}
    world["app"].chat._use_default = False
    assert world["a"].post("/api/runtime", {"monthly_cap_usd": 10}).status == 200   # teto 0 não chama a IA
    r = world["a"].post("/api/chat", {"agent": "theo", "text": "fala da luz da cena dois", "pid": world["pid_b"]})
    assert r.status == 200
    assert seen and "Garrafa térmica B" not in json.dumps(seen, ensure_ascii=False)


def test_switch_to_another_workspace_is_refused(world):
    r = world["a"].post("/api/workspace/switch", {"workspace_id": world["wid_b"]})
    assert r.status == 400
    assert json.loads(world["a"].get("/api/me").body)["workspace"]["id"] != world["wid_b"]


def test_music_of_another_workspace(world):
    a = world["a"]
    before = snapshot_b(world)
    assert a.get("/api/music/file/mus_b").status == 404
    assert world["b"].get("/api/music/file/mus_b").status == 200
    assert a.post("/api/music/update", {"id": "mus_b", "title": "roubada"}).status == 400
    assert a.post("/api/music/delete", {"id": "mus_b"}).status == 400
    a.post("/api/music/favorite", {"id": "mus_b", "on": True})
    assert snapshot_b(world)[3] == before[3]          # trilha da B intacta (título, favorito, arquivo)
    assert (world["settings"].data_dir / "music" / world["wid_b"] / "mus_b.mp3").is_file()
    assert "mus_b" not in a.get("/api/music").body.decode()


def test_training_of_another_workspace(world):
    a, b = world["a"], world["b"]
    assert "Paleta da B" not in a.get("/api/training/iris").body.decode()
    view_b = json.loads(b.get("/api/training/iris").body)
    ref_ids = [r["id"] for r in (view_b.get("draft") or {}).get("refs", [])]
    assert ref_ids
    a.post("/api/training/iris/ref_delete", {"id": ref_ids[0]})
    a.post("/api/training/iris/remove", {"key": "refs", "id": ref_ids[0]})
    assert "Paleta da B" in b.get("/api/training/iris").body.decode()


def test_spend_credits_and_listing_only_show_own_workspace(world):
    a, pid_b = world["a"], world["pid_b"]
    for path in ("/api/spend", "/api/credits", "/api/state", "/api/me"):
        r = a.get(path)
        assert r.status == 200 and pid_b not in r.body.decode() and world["wid_b"] not in r.body.decode()


def test_without_session_everything_is_401(world):
    app = world["app"]
    h = {"Host": "127.0.0.1:8765"}
    for path in (f"/api/state?pid={world['pid_b']}", f"/media/{world['pid_b']}/inputs/product_input.json",
                 "/api/music/file/mus_b", "/api/training/iris"):
        assert app.handle("GET", path, h, b"").status == 401
    assert app.handle("POST", f"/api/productions/{world['pid_b']}/approve", h, b"{}").status == 401


def test_csrf_token_of_another_user_is_refused(world):
    a, b = world["a"], world["b"]
    r = world["app"].handle("POST", f"/api/productions/{world['pid_a']}/pause", {**a.h, "X-Studio-Token": b.token}, b"{}")
    assert r.status == 403


# ------------------------------------------------------------------ path traversal
@pytest.mark.parametrize("tail", [
    "../{pid_b}/inputs/product_input.json",
    "..%2f{pid_b}%2finputs%2fproduct_input.json",
    "%2e%2e/%2e%2e/segredo.json",
    "../../segredo.json",
    "..%5c..%5csegredo.json",
    "..\\..\\segredo.json",
    "/{data_dir}/segredo.json",
    "inputs/../../../segredo.json",
])
def test_media_path_traversal(world, tail):
    s = world["settings"]
    (s.data_dir / "segredo.json").write_text('{"segredo": "nao"}', encoding="utf-8")
    path = f"/media/{world['pid_a']}/" + tail.format(pid_b=world["pid_b"], data_dir=s.data_dir.as_posix().lstrip("/"))
    r = world["a"].get(path)
    assert r.status == 404 and r.file is None
    assert b"segredo" not in r.body and b"Garrafa" not in r.body


def test_media_only_serves_known_types(world):
    s, pid_a = world["settings"], world["pid_a"]
    (s.data_dir / "productions" / pid_a / "x.sqlite3").write_bytes(b"SQLite format 3")
    (s.data_dir / "productions" / pid_a / "x.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    for name in ("x.sqlite3", "x.html"):
        assert world["a"].get(f"/media/{pid_a}/{name}").status == 404


def test_static_assets_path_traversal(world):
    app = world["app"]
    for path in ("/assets/../../pyproject.toml", "/assets/%2e%2e/%2e%2e/pyproject.toml", "/assets/..\\..\\pyproject.toml"):
        r = app.handle("GET", path, {"Host": "127.0.0.1:8765"}, b"")
        assert r.status in (401, 404) and r.file is None


# ------------------------------------------------------------------ uploads: nome, tamanho, tipo real
def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


MP4_HEAD = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


@pytest.mark.parametrize("name,data,msg", [
    ("foto.jpg", b64(PNG_RAW), "não é um arquivo JPG"),                 # PNG renomeado para .jpg
    ("foto.png", b64(b"<html><script>x</script></html>"), "não é um arquivo PNG"),
    ("foto.webp", b64(b"RIFF\x00\x00\x00\x00AVI LIST"), "não é um arquivo WEBP"),
    ("video.mp4", b64(b"MZ\x90\x00" + b"\x00" * 64), "não é um arquivo MP4"),  # executável com nome de vídeo
    ("../../etc/passwd.png", b64(PNG_RAW), "nome de arquivo inválido"),
    ("..\\..\\x.png", b64(PNG_RAW), "nome de arquivo inválido"),
    ("C:x.png", b64(PNG_RAW), "nome de arquivo inválido"),
    ("foto\x00.png", b64(PNG_RAW), "nome de arquivo inválido"),
    ("foto\n.png", b64(PNG_RAW), "nome de arquivo inválido"),
    (".png", b64(PNG_RAW), "nome de arquivo inválido"),
    ("a" * 300 + ".png", b64(PNG_RAW), "longo demais"),
    ("", b64(PNG_RAW), "sem nome"),
    ("vazio.png", "", "vazio"),
    ("grande.png", "A" * (uploads.UPLOAD_MAX_IMAGE_BYTES * 4 // 3 + 16), "acima de 20 MB"),
])
def test_bad_upload_is_refused_and_nothing_is_written(world, name, data, msg):
    s = world["settings"]
    before = sorted(p for p in (s.data_dir / "uploads").rglob("*") if p.is_file())
    r = world["a"].post("/api/productions", {**FORM, "files": [{"name": name, "data": data, "role": "front"}]})
    assert r.status == 400 and msg in json.loads(r.body)["error"], r.body
    assert sorted(p for p in (s.data_dir / "uploads").rglob("*") if p.is_file()) == before


def test_bad_second_file_does_not_leave_the_first_on_disk(world):
    s = world["settings"]
    before = sorted(p for p in (s.data_dir / "uploads").rglob("*") if p.is_file())
    files = [{"name": "ok.png", "data": PNG, "role": "front"}, {"name": "ruim.png", "data": b64(b"xx"), "role": "side"}]
    assert world["a"].post("/api/productions", {**FORM, "files": files}).status == 400
    assert sorted(p for p in (s.data_dir / "uploads").rglob("*") if p.is_file()) == before


def test_valid_uploads_get_generated_names(world):
    files = [{"name": "Minha Foto (1).png", "data": PNG, "role": "front"},
             {"name": "tela.mp4", "data": b64(MP4_HEAD), "role": "front"}]
    r = world["a"].post("/api/productions", {**FORM, "files": files})
    assert r.status == 200, r.body
    names = sorted(p.name for p in (world["settings"].data_dir / "uploads").rglob("*") if p.is_file())
    assert "Minha Foto (1).png" not in names and any(n.endswith("_context.mp4") for n in names)


def test_training_reference_file_type_is_checked(world):
    a = world["a"]
    r = a.post("/api/training/iris/ref", {"title": "x", "file": {"name": "x.webp", "data": b64(PNG_RAW)}})
    assert r.status == 400 and "não é uma imagem" in json.loads(r.body)["error"]
    r = a.post("/api/training/iris/ref", {"title": "x", "file": {"name": "x.txt", "data": b64(b"MZ\x00\x00binario")}})
    assert r.status == 400 and "binário" in json.loads(r.body)["error"]
    r = a.post("/api/training/iris/ref", {"title": "ok", "file": {"name": "x.png", "data": b64(PNG_RAW)}})
    assert r.status == 200


def test_positive_control_owner_can_act_on_own_production(world):
    """Controle: as mesmas rotas funcionam para a dona (o 404 acima é a checagem de dono, não rota quebrada)."""
    assert world["a"].post(f"/api/productions/{world['pid_a']}/budget", {"value": 7}).status == 200
    assert world["a"].post(f"/api/productions/{world['pid_a']}/pause", {}).status == 200
    assert world["a"].get(f"/media/{world['pid_a']}/inputs/product_input.json").status == 200
