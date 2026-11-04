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


def test_onboarding_persists_per_user(app):
    a = User(app, "tour@exemplo.com")
    assert a.me["user"]["onboarding"] == {"done_at": None, "step": 0}  # conta nova passa pelo kit
    assert a.post("/api/onboarding", {"step": 3})[0] == 200
    assert a.get("/api/me")[1]["user"]["onboarding"] == {"done_at": None, "step": 3}  # retoma de onde parou
    st, body = a.post("/api/onboarding", {"step": 3, "done": True})
    assert st == 200 and body["onboarding"]["done_at"]
    assert a.get("/api/me")[1]["user"]["onboarding"]["done_at"]
    assert a.post("/api/onboarding", {"step": 99})[0] == 400
    b = User(app, "outra@exemplo.com")  # cada usuário tem o seu
    assert b.me["user"]["onboarding"]["done_at"] is None
    assert a.post("/api/onboarding", {"done": False})[1]["onboarding"]["done_at"] is None


# ---------------------------------------------------------------- verificação de e-mail, recuperação e Google
def _mailbox(app):
    box = []
    app.send_mail = lambda to, subject, text: box.append((to, subject, text)) or True
    return box


def test_signup_sends_code_and_verifies(app):
    box = _mailbox(app)
    a = User(app, "novo@x.com")
    assert a.me["user"]["email_verified"] is False  # entra em DEMO, mas o e-mail ainda não foi confirmado
    to, subject, text = box[-1]
    code = subject.rsplit(" ", 1)[-1]
    assert to == "novo@x.com" and len(code) == 6 and code in text
    verify = lambda c: app.handle("POST", "/api/auth/verify", {**CLIENT, "Cookie": a.cookie}, json.dumps({"code": c}).encode())  # noqa: E731
    wrong = "000000" if code != "000000" else "111111"
    r = verify(wrong)
    assert r.status == 400 and "incorreto" in json.loads(r.body)["error"]
    assert verify(code[:3] + " " + code[3:]).status == 200  # espaços e traços são ignorados
    assert a.get("/api/me")[1]["user"]["email_verified"] is True
    r = app.handle("POST", "/api/auth/resend", {**CLIENT, "Cookie": a.cookie}, b"{}")
    assert r.status == 400 and "já está confirmado" in json.loads(r.body)["error"]


def test_verify_needs_session_and_limits_tries(app, settings):
    assert app.handle("POST", "/api/auth/verify", CLIENT, b'{"code":"123456"}').status == 401
    db = Database(settings.db_path)
    acc = Accounts(db)
    uid, _ = acc.create_user("t@x.com", "senha-forte-123")
    code = acc.start_verification(uid)
    with pytest.raises(AuthError, match="aguarde"):
        acc.start_verification(uid)  # reenvio tem intervalo mínimo
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(AuthError):
            acc.verify_email(uid, wrong)
    with pytest.raises(AuthError, match="expirado"):
        acc.verify_email(uid, code)  # esgotou as tentativas: nem o código certo vale
    db.close()


def test_existing_users_stay_verified_after_migration(settings):
    db = Database(settings.db_path)
    db.conn.executescript("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,"
                          " pw_hash TEXT NOT NULL, is_platform_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);"
                          "INSERT INTO users VALUES ('usr_old', 'old@x.com', 'Old', 'x', 0, '2026-01-01T00:00:00+00:00');")
    Accounts(db)
    row = db.conn.execute("SELECT email_verified_at FROM users WHERE id='usr_old'").fetchone()
    assert row[0] == "2026-01-01T00:00:00+00:00"
    db.close()


def test_forgot_sends_link_and_reset_verifies_email(app):
    box = _mailbox(app)
    a = User(app, "esq@x.com")
    r = app.handle("POST", "/api/auth/forgot", CLIENT, b'{"email":"ninguem@x.com"}')
    assert r.status == 200 and len(box) == 1  # e-mail desconhecido: mesma resposta, nada enviado
    r = app.handle("POST", "/api/auth/forgot", CLIENT, b'{"email":"ESQ@x.com"}')
    assert r.status == 200 and box[-1][0] == "esq@x.com"
    token = box[-1][2].split("?reset=")[1].split()[0]
    assert box[-1][2].count("http://127.0.0.1:8765/?reset=") == 1
    assert app.handle("POST", "/api/auth/reset", CLIENT, json.dumps({"token": token, "password": "nova-senha-forte"}).encode()).status == 200
    assert a.get("/api/me")[0] == 401  # sessões antigas caem
    r = app.handle("POST", "/api/auth/login", CLIENT, b'{"email":"esq@x.com","password":"nova-senha-forte"}')
    assert r.status == 200


def test_auth_config_is_public(app):
    r = app.handle("GET", "/api/auth/config", BASE, b"")
    assert r.status == 200 and json.loads(r.body) == {"signup": True, "google": False, "email": False}
    r = app.handle("GET", "/api/auth/google/start", BASE, b"")  # sem credenciais: volta ao login com aviso
    assert r.status == 302 and "erro=google_off" in r.headers["Location"]


def _google_app(app, info):
    app.google_client_id, app.google_client_secret = "cid", "segredo"
    calls = []

    def fake(url, data=None, headers=None):
        calls.append((url, data, headers))
        return {"access_token": "at"} if data is not None else info
    app.google_http = fake
    return calls


def _google_login(app):
    r = app.handle("GET", "/api/auth/google/start", BASE, b"")
    assert r.status == 302 and r.headers["Location"].startswith("https://accounts.google.com/")
    state = r.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
    assert f"state={state}" in r.headers["Location"] and "segredo" not in r.headers["Location"]
    return app.handle("GET", f"/api/auth/google/callback?state={state}&code=abc",
                      {**BASE, "Cookie": f"studio_oauth={state}"}, b"")


def test_google_creates_first_account_as_admin_and_links_later(app):
    calls = _google_app(app, {"sub": "g-1", "email": "Chris@Gmail.com", "email_verified": True, "name": "Chris"})
    r = _google_login(app)
    assert r.status == 302 and r.headers["Location"] == "/"
    cookies = r.headers["Set-Cookie"]
    assert isinstance(cookies, list) and "Max-Age=0" in cookies[0] and cookies[1].startswith("studio_session=")
    assert calls[0][1]["client_secret"] == "segredo" and calls[0][1]["redirect_uri"] == "http://127.0.0.1:8765/api/auth/google/callback"
    st, me = app.handle("GET", "/api/me", {**BASE, "Cookie": cookies[1].split(";")[0]}, b""), None
    me = json.loads(st.body)
    assert me["admin"] is True and me["user"]["email"] == "chris@gmail.com" and me["user"]["email_verified"] is True
    # conta sem senha não entra por senha
    r = app.handle("POST", "/api/auth/login", CLIENT, b'{"email":"chris@gmail.com","password":"!"}')
    assert r.status == 400


def test_google_links_existing_email_account_and_rejects_bad_state(app):
    a = User(app, "ana@x.com")
    _google_app(app, {"sub": "g-ana", "email": "ana@x.com", "email_verified": True})
    r = _google_login(app)
    cookie = r.headers["Set-Cookie"][1].split(";")[0]
    me = json.loads(app.handle("GET", "/api/me", {**BASE, "Cookie": cookie}, b"").body)
    assert me["workspace"]["id"] == a.me["workspace"]["id"]  # mesma conta, mesmo estúdio
    r = app.handle("GET", "/api/auth/google/callback?state=x&code=abc", {**BASE, "Cookie": "studio_oauth=y"}, b"")
    assert r.status == 302 and "erro=google_state" in r.headers["Location"]
    _google_app(app, {"sub": "g-2", "email": "outra@x.com", "email_verified": False})
    assert "erro=google_unverified" in _google_login(app).headers["Location"]
