"""Login com Google contra um Google falso por HTTP: sucesso, e-mail não verificado, state errado/repetido,
convite ausente/válido/inválido, conta existente, URI fixa, PKCE, nada vazando e limite de requisições."""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, urlparse

import pytest

from studio.accounts import NO_PASSWORD, TERMS_VERSION, Accounts
from studio.config import load_settings
from studio.db import Database
from studio.ratelimit import RateLimitConfig, Rule
from studio.web.server import App, GoogleFlows

from .google_fake import CLIENT_SECRET, FakeGoogle

PUBLIC = "staging.kiroo.app"
HOST = {"Host": PUBLIC}
CLIENT = {**HOST, "X-Studio-Client": "game"}
CALLBACK = f"https://{PUBLIC}/api/auth/google/callback"


@pytest.fixture
def google():
    with FakeGoogle() as g:
        yield g


def make_app(settings, tmp_path, google, signup="invite", rate_limits=None):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    app = App(8765, settings_loader=loader, sim_pacing=False, signup=signup, public_host=PUBLIC,
              allowed_hosts={"127.0.0.1:8765", "kiroo-staging.up.railway.app"}, rate_limits=rate_limits)
    if google is not None:
        google.attach(app)
    return app


@pytest.fixture
def app(settings, tmp_path, google):
    return make_app(settings, tmp_path, google)


def profile(email="nova@gmail.com", sub="g-nova", verified=True, name="Nova"):
    return {"sub": sub, "email": email, "email_verified": verified, "name": name}


def start(app, query="", headers=HOST):
    r = app.handle("GET", "/api/auth/google/start" + (f"?{query}" if query else ""), headers, b"")
    assert r.status == 302
    return r


def state_cookie(r) -> str:
    c = r.headers["Set-Cookie"]
    assert c.startswith("studio_oauth=") and "HttpOnly" in c and "Secure" in c and "Path=/api/auth/google" in c
    return c.split(";")[0]


def login(app, google, prof, query=""):
    """Fluxo inteiro como o navegador faria: start → Google → callback com o cookie do state."""
    r = start(app, query)
    assert r.headers["Location"].startswith("https://accounts.google.com/"), r.headers["Location"]
    cb = google.consent(r.headers["Location"], prof)
    return app.handle("GET", cb, {**HOST, "Cookie": state_cookie(r)}, b"")


def err(r) -> str | None:
    loc = r.headers["Location"]
    return parse_qs(urlparse(loc).query).get("erro", [None])[0] if loc != "/" else None


def session_cookie(r) -> str:
    cookies = r.headers["Set-Cookie"]
    assert isinstance(cookies, list) and "Max-Age=0" in cookies[0]   # o state é apagado sempre
    return cookies[1].split(";")[0]


def me(app, cookie):
    r = app.handle("GET", "/api/me", {**HOST, "Cookie": cookie}, b"")
    assert r.status == 200, r.body
    return json.loads(r.body)


def db_of(app):
    s, db, acc = app._db()
    return db, acc


def invite(app, email=None) -> str:
    db, acc = db_of(app)
    try:
        return acc.create_invite(email=email)[0]
    finally:
        db.close()


def user_row(app, email):
    db, acc = db_of(app)
    try:
        return acc.user_by_email(email)
    finally:
        db.close()


SIGNUP = "intent=signup&consent=1"


# ------------------------------------------------------------------ início: URI fixa, state, PKCE, flag
def test_start_uses_fixed_redirect_uri_state_and_pkce(app):
    r = start(app)
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["Location"]).query).items()}
    assert q["redirect_uri"] == CALLBACK
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert len(q["state"]) >= 40 and state_cookie(r) == f"studio_oauth={q['state']}"
    assert CLIENT_SECRET not in r.headers["Location"] and "code_verifier" not in r.headers["Location"]
    assert q["state"] != parse_qs(urlparse(start(app).headers["Location"]).query)["state"][0]   # aleatório a cada início


def test_redirect_uri_never_comes_from_host_header(app):
    # outro host permitido (domínio do Railway): o início é mandado para o host público, sem montar URI com ele
    r = app.handle("GET", "/api/auth/google/start?intent=signup&consent=1&invite=X", {"Host": "kiroo-staging.up.railway.app"}, b"")
    assert r.status == 302 and r.headers["Location"] == f"https://{PUBLIC}/api/auth/google/start?intent=signup&consent=1&invite=X"
    assert "Set-Cookie" not in r.headers
    # host fora da lista: nem chega ao Google
    assert app.handle("GET", "/api/auth/google/start", {"Host": "evil.example"}, b"").status == 403
    # sem host público (dev local): endereço local fixo, não o Host
    local = App(8765, settings_loader=app.load_settings, sim_pacing=False, signup="open",
                allowed_hosts={"127.0.0.1:8765", "localhost:8765"})
    local.google_client_id, local.google_client_secret = "cid", "s"
    r = local.handle("GET", "/api/auth/google/start", {"Host": "localhost:8765"}, b"")
    assert parse_qs(urlparse(r.headers["Location"]).query)["redirect_uri"] == ["http://127.0.0.1:8765/api/auth/google/callback"]


def test_config_flag_follows_server_credentials(settings, tmp_path, google):
    off = make_app(settings, tmp_path, None)
    off.google_client_id = off.google_client_secret = None
    assert json.loads(off.handle("GET", "/api/config", HOST, b"").body)["google"] is False
    r = off.handle("GET", "/api/auth/google/start", HOST, b"")
    assert err(r) == "google_off" and "accounts.google.com" not in r.headers["Location"]
    off.google_client_id = "só-o-id"   # metade configurada continua desligado
    assert json.loads(off.handle("GET", "/api/config", HOST, b"").body)["google"] is False
    on = make_app(settings, tmp_path, google)
    body = json.loads(on.handle("GET", "/api/config", HOST, b"").body)
    assert body["google"] is True and CLIENT_SECRET not in json.dumps(body) and "cid" not in json.dumps(body)


# ------------------------------------------------------------------ sucesso e convite
def test_signup_with_valid_invite_creates_verified_account(app, google):
    code = invite(app)
    r = login(app, google, profile(email="Nova@Gmail.com"), f"{SIGNUP}&invite={code}")
    assert err(r) is None and r.headers["Location"] == "/"
    m = me(app, session_cookie(r))
    assert m["user"]["email"] == "nova@gmail.com" and m["user"]["email_verified"] is True and m["admin"] is False
    u = user_row(app, "nova@gmail.com")
    assert u["google_sub"] == "g-nova" and u["pw_hash"] == NO_PASSWORD and u["terms_version"] == TERMS_VERSION
    db, acc = db_of(app)
    try:
        inv = acc.invites()[0]
        assert inv["used_by"] == u["id"] and inv["used_at"]
    finally:
        db.close()
    # o token trocado levou o code_verifier certo (o Google falso confere o PKCE) e a URI fixa
    assert google.token_requests[-1]["redirect_uri"] == CALLBACK and len(google.token_requests[-1]["code_verifier"]) >= 43
    # o mesmo convite não serve duas vezes
    r = login(app, google, profile(email="outra@gmail.com", sub="g-outra"), f"{SIGNUP}&invite={code}")
    assert err(r) == "convite_invalido" and user_row(app, "outra@gmail.com") is None


def test_invite_missing_is_refused_clearly(app, google):
    # sem convite no cadastro: recusado já no início, sem ir ao Google
    r = start(app, SIGNUP)
    assert err(r) == "convite" and "accounts.google.com" not in r.headers["Location"]
    # "Continuar com Google" (entrar) com e-mail sem conta: recusado, nada criado
    r = login(app, google, profile())
    assert err(r) == "convite" and user_row(app, "nova@gmail.com") is None
    # sem aceite dos Termos: recusado no início
    assert err(start(app, f"intent=signup&invite={invite(app)}")) == "google_consent"


def test_invalid_or_other_email_invite_is_refused_and_counted(app, google):
    r = login(app, google, profile(), f"{SIGNUP}&invite=KIROO-AAAA-BBBB-CCCC")
    assert err(r) == "convite_invalido" and user_row(app, "nova@gmail.com") is None
    code = invite(app, email="dona@x.com")   # convite preso a outro e-mail
    r = login(app, google, profile(), f"{SIGNUP}&invite={code}")
    assert err(r) == "convite_invalido" and user_row(app, "nova@gmail.com") is None
    db, acc = db_of(app)
    try:
        assert acc.invites()[0]["used_at"] is None   # continua disponível para a dona
        assert db.conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key LIKE 's:%'").fetchone()[0] == 2
    finally:
        db.close()


def test_closed_and_open_modes(settings, tmp_path, google):
    closed = make_app(settings, tmp_path, google, signup="closed")
    assert err(start(closed, SIGNUP)) == "convite"
    assert err(login(closed, google, profile())) == "convite"
    opened = make_app(settings, tmp_path, google, signup="open")
    assert err(login(opened, google, profile())) == "google_consent"   # entrar não cria conta sem aceite dos Termos
    r = login(opened, google, profile(), SIGNUP)
    assert err(r) is None and user_row(opened, "nova@gmail.com")["terms_version"] == TERMS_VERSION


# ------------------------------------------------------------------ e-mail verificado
@pytest.mark.parametrize("flag", [False, "false", "true", None, 1])
def test_unverified_email_is_refused(app, google, flag):
    r = login(app, google, profile(verified=flag), f"{SIGNUP}&invite={invite(app)}")
    assert err(r) == "google_unverified" and user_row(app, "nova@gmail.com") is None


def test_already_linked_account_still_needs_verified_email(app, google):
    assert err(login(app, google, profile(), f"{SIGNUP}&invite={invite(app)}")) is None
    assert err(login(app, google, profile(verified=False))) == "google_unverified"
    assert err(login(app, google, profile())) is None


# ------------------------------------------------------------------ conta existente
def _local_user(app, email, verified=True):
    db, acc = db_of(app)
    try:
        uid, wid = acc.create_user(email, "senha-forte-123", "Ana", verified=verified)
        token, _ = acc.create_session(uid, wid)
        return uid, wid, token
    finally:
        db.close()


def test_existing_verified_account_is_linked_by_verified_email(app, google):
    uid, wid, _ = _local_user(app, "ana@x.com")
    r = login(app, google, profile(email="ANA@x.com", sub="g-ana"))
    m = me(app, session_cookie(r))
    assert m["workspace"]["id"] == wid
    u = user_row(app, "ana@x.com")
    assert u["google_sub"] == "g-ana" and u["pw_hash"] != NO_PASSWORD   # senha dela continua valendo
    db, acc = db_of(app)
    try:
        assert acc.login("ana@x.com", "senha-forte-123")[0]
    finally:
        db.close()


def test_existing_unverified_account_loses_password_and_sessions(app, google):
    """Alguém cadastrou o e-mail da vítima com senha própria e nunca confirmou: ao entrar pelo Google (dono real),
    a senha do intruso é anulada e as sessões dele caem."""
    uid, wid, intruder = _local_user(app, "vitima@gmail.com", verified=False)
    r = login(app, google, profile(email="vitima@gmail.com", sub="g-vitima"))
    assert err(r) is None and me(app, session_cookie(r))["user"]["email_verified"] is True
    assert user_row(app, "vitima@gmail.com")["pw_hash"] == NO_PASSWORD
    assert app.handle("GET", "/api/me", {**HOST, "Cookie": f"studio_session={intruder}"}, b"").status == 401


def test_email_linked_to_another_google_account_is_not_relinked(app, google):
    assert err(login(app, google, profile(email="ana@gmail.com", sub="g-1"), f"{SIGNUP}&invite={invite(app)}")) is None
    r = login(app, google, profile(email="ana@gmail.com", sub="g-2"))
    assert err(r) == "google_other" and user_row(app, "ana@gmail.com")["google_sub"] == "g-1"


# ------------------------------------------------------------------ state
def test_wrong_state_is_refused_without_calling_google(app, google):
    r = start(app)
    cb = google.consent(r.headers["Location"], profile())
    for cookie in ("studio_oauth=outro", ""):
        x = app.handle("GET", cb, {**HOST, "Cookie": cookie} if cookie else HOST, b"")
        assert err(x) == "google_state"
    assert google.token_requests == []
    # o state de quem começou não foi gasto por tentativa alheia: o dono ainda termina
    assert err(app.handle("GET", cb, {**HOST, "Cookie": state_cookie(r)}, b"")) == "convite"
    assert len(google.token_requests) == 1


def test_state_is_single_use(app, google):
    code = invite(app)
    r = start(app, f"{SIGNUP}&invite={code}")
    cookie = state_cookie(r)
    cb = google.consent(r.headers["Location"], profile())
    assert err(app.handle("GET", cb, {**HOST, "Cookie": cookie}, b"")) is None
    again = app.handle("GET", cb, {**HOST, "Cookie": cookie}, b"")
    assert err(again) == "google_state" and len(google.token_requests) == 1


def test_expired_flow_and_cancel(app, google):
    t = [0.0]
    app.google_flows = GoogleFlows(clock=lambda: t[0])
    r = start(app)
    cb = google.consent(r.headers["Location"], profile())
    t[0] = 601
    assert err(app.handle("GET", cb, {**HOST, "Cookie": state_cookie(r)}, b"")) == "google_state"
    r = start(app)
    st = state_cookie(r).split("=", 1)[1]
    x = app.handle("GET", f"/api/auth/google/callback?state={st}&error=access_denied", {**HOST, "Cookie": state_cookie(r)}, b"")
    assert err(x) == "google_cancel" and len(app.google_flows) == 0


def test_flow_store_is_bounded():
    f = GoogleFlows(cap=3)
    for i in range(10):
        f.put(f"s{i}", {"i": i})
    assert len(f) == 3 and f.take("s0") is None and f.take("s9") == {"i": 9} and f.take("s9") is None


# ------------------------------------------------------------------ nada vaza; limite
def test_no_code_token_or_secret_leaks(app, google, caplog):
    caplog.set_level(logging.DEBUG)
    google.token_mode = "fail"   # o Google responde ecoando segredo e código
    r = start(app)
    cb = google.consent(r.headers["Location"], profile())
    x = app.handle("GET", cb, {**HOST, "Cookie": state_cookie(r)}, b"")
    assert err(x) == "google_failed"
    code = parse_qs(urlparse(cb).query)["code"][0]
    verifier = google.token_requests[-1]["code_verifier"]
    blob = caplog.text + json.dumps(x.headers) + x.body.decode()
    for secret in (CLIENT_SECRET, code, verifier):
        assert secret not in blob
    # sucesso: a resposta só tem o cookie de sessão, nada do Google
    google.token_mode = "ok"
    ok = login(app, google, profile(), f"{SIGNUP}&invite={invite(app)}")
    blob = caplog.text + json.dumps(ok.headers) + ok.body.decode()
    assert "ya29" not in blob and CLIENT_SECRET not in blob and "4/0FALSO" not in blob
    assert ok.headers["Cache-Control"] == "no-store" and ok.headers["Referrer-Policy"] == "no-referrer"


def test_google_unreachable_is_a_clean_error(app):
    app.google_token_url = "http://127.0.0.1:9/token"   # porta fechada
    r = start(app)
    st = state_cookie(r)
    x = app.handle("GET", f"/api/auth/google/callback?state={st.split('=', 1)[1]}&code=abc", {**HOST, "Cookie": st}, b"")
    assert err(x) == "google_failed"


def test_routes_are_rate_limited(settings, tmp_path, google):
    app = make_app(settings, tmp_path, google, rate_limits=RateLimitConfig(auth=Rule(3, 300)))
    for _ in range(3):
        app.handle("GET", "/api/auth/google/callback?state=a&code=b", HOST, b"")
    assert app.handle("GET", "/api/auth/google/callback?state=a&code=b", HOST, b"").status == 429
    assert app.handle("GET", "/api/auth/google/start", HOST, b"").status == 429


def test_google_session_is_scoped_to_own_workspace(app, google):
    """IDOR: quem entra pelo Google só enxerga o próprio estúdio, mesmo com conta antiga de outra pessoa no banco."""
    _, other_wid, _ = _local_user(app, "outra@x.com")
    r = login(app, google, profile(), f"{SIGNUP}&invite={invite(app)}")
    cookie = session_cookie(r)
    m = me(app, cookie)
    assert m["workspace"]["id"] != other_wid and all(w["id"] != other_wid for w in m.get("workspaces", []))
    db = Database(app.settings().db_path)
    try:
        sess = Accounts(db).session(cookie.split("=", 1)[1])
        assert sess["workspace_id"] != other_wid
    finally:
        db.close()
