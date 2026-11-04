import base64
import json
import time

import pytest

from studio.accounts import LOGIN_MAX_FAILS, Accounts, AuthError, hash_password, verify_password
from studio.config import load_settings
from studio.db import Database
from studio.providers.simulated import placeholder_png
from studio.web.server import App

BASE = {"Host": "127.0.0.1:8765"}
CLIENT = {**BASE, "X-Studio-Client": "game"}
PNG = "data:image/png;base64," + base64.b64encode(placeholder_png("x", 90, 160)).decode()
FORM = {"name": "Copo", "variant": "azul", "affiliate_link": "https://s.shopee.com.br/7VHTuA2W1j", "budget": 5,
        "files": [{"name": "f.png", "data": PNG, "role": "front"}], "start": False}


@pytest.fixture
def app(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    return App(8765, settings_loader=loader, sim_pacing=False)


class User:
    def __init__(self, app, email, password="senha-forte-123"):
        self.app = app
        r = app.handle("POST", "/api/auth/signup", CLIENT, json.dumps({"email": email, "password": password}).encode())
        assert r.status == 200, r.body
        self.cookie = r.headers["Set-Cookie"].split(";")[0]
        self.me = self.get("/api/me")[1]

    @property
    def h(self):
        return {**BASE, "Cookie": self.cookie}

    def get(self, path):
        r = self.app.handle("GET", path, self.h, b"")
        try:
            return r.status, json.loads(r.body)
        except ValueError:
            return r.status, r

    def post(self, path, body=None, csrf=None):
        r = self.app.handle("POST", path, {**self.h, "X-Studio-Token": csrf or self.me["csrf"]}, json.dumps(body or {}).encode())
        return r.status, json.loads(r.body or b"{}")


def test_password_hashing():
    h = hash_password("uma senha longa")
    assert h.startswith("scrypt$") and "uma senha" not in h
    assert verify_password("uma senha longa", h) and not verify_password("outra senha", h)
    assert hash_password("uma senha longa") != h  # sal aleatório


def test_signup_rules(app):
    bad = [({"email": "nao-e-email", "password": "senha-forte-123"}, "e-mail"),
           ({"email": "a@b.com", "password": "curta"}, "10 caracteres")]
    for body, msg in bad:
        r = app.handle("POST", "/api/auth/signup", CLIENT, json.dumps(body).encode())
        assert r.status == 400 and msg in json.loads(r.body)["error"]
    User(app, "a@b.com")
    r = app.handle("POST", "/api/auth/signup", CLIENT, json.dumps({"email": "A@B.com", "password": "senha-forte-123"}).encode())
    assert r.status == 400 and "já existe" in json.loads(r.body)["error"]  # e-mail sem diferenciar maiúsculas
    # sem o cabeçalho do cliente (ex.: formulário de outro site) o cadastro é recusado
    assert app.handle("POST", "/api/auth/signup", BASE, b'{"email":"c@d.com","password":"senha-forte-123"}').status == 403


def test_first_account_is_admin_others_are_demo_only(app):
    chris, cliente = User(app, "chris@x.com"), User(app, "cliente@x.com")
    assert chris.me["admin"] is True and chris.me["workspace"]["allow_real"] is True
    assert cliente.me["admin"] is False and cliente.me["workspace"]["allow_real"] is False
    status, body = cliente.post("/api/runtime", {"mode": "real", "monthly_cap_usd": 50})
    assert status == 403 and "DEMO" in body["error"]
    assert cliente.post("/api/productions", FORM)[1]["mode"] == "simulated"
    assert cliente.post("/api/config", {"settings": {"max_image_attempts": 2}})[0] == 403
    assert cliente.get("/painel")[0] == 403


def test_workspaces_are_isolated(app):
    a, b = User(app, "a@x.com"), User(app, "b@x.com")
    pid = a.post("/api/productions", FORM)[1]["pid"]
    a.post(f"/api/productions/{pid}/validate")
    assert [p["id"] for p in a.get("/api/state")[1]["productions"]] == [pid]
    st = b.get(f"/api/state?pid={pid}")[1]
    assert st["productions"] == [] and st["production"] is None  # B não vê nem pelo id
    assert b.post(f"/api/productions/{pid}/cancel")[0] == 404
    assert b.post(f"/api/productions/{pid}/budget", {"value": 999})[0] == 404
    ref = a.get(f"/api/state?pid={pid}")[1]["production"]["sheet"]["references"][0]["url"]
    assert a.get(ref)[0] == 200
    assert b.get(ref)[0] == 404


def test_csrf_and_session_required(app):
    a, b = User(app, "a@x.com"), User(app, "b@x.com")
    assert app.handle("GET", "/api/state", BASE, b"").status == 401
    assert a.post("/api/demo", {}, csrf="errado")[0] == 403
    assert a.post("/api/demo", {}, csrf=b.me["csrf"])[0] == 403  # token de outra sessão não vale
    assert a.post("/api/demo", {})[0] == 200


def test_logout_invalidates_session(app):
    a = User(app, "a@x.com")
    r = app.handle("POST", "/api/auth/logout", {**CLIENT, "Cookie": a.cookie}, b"{}")
    assert r.status == 200 and "Max-Age=0" in r.headers["Set-Cookie"]
    assert a.get("/api/me")[0] == 401


def test_login_and_throttling(app):
    User(app, "a@x.com")
    login = lambda pw: app.handle("POST", "/api/auth/login", {**CLIENT, "X-Forwarded-For": "1.2.3.4"},  # noqa: E731
                                  json.dumps({"email": "a@x.com", "password": pw}).encode())
    assert login("senha-forte-123").status == 200
    for _ in range(LOGIN_MAX_FAILS):
        r = login("errada-errada")
        assert r.status == 400 and "incorretos" in json.loads(r.body)["error"]
    r = login("senha-forte-123")  # bloqueado mesmo com a senha certa
    assert r.status == 400 and "muitas tentativas" in json.loads(r.body)["error"]


def test_password_reset_works_once_and_drops_sessions(settings):
    db = Database(settings.db_path)
    acc = Accounts(db)
    uid, wid = acc.create_user("a@x.com", "senha-forte-123")
    token, _ = acc.create_session(uid, wid)
    assert acc.start_reset("ninguem@x.com") is None
    reset = acc.start_reset("a@x.com")
    acc.finish_reset(reset, "nova-senha-forte")
    assert acc.session(token) is None  # sessões antigas caem
    with pytest.raises(AuthError):
        acc.finish_reset(reset, "outra-senha-forte")  # uso único
    assert acc.login("a@x.com", "nova-senha-forte")[0]
    db.close()


def test_first_account_receives_existing_productions(app, make_orch, product):
    orch = make_orch()
    from .conftest import create
    old = create(orch, product)  # produção de antes das contas (sem dono)
    chris = User(app, "chris@x.com")
    assert old in [p["id"] for p in chris.get("/api/state")[1]["productions"]]
    cliente = User(app, "cliente@x.com")
    assert cliente.get("/api/state")[1]["productions"] == []
