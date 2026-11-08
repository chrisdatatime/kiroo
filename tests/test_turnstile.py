"""Cloudflare Turnstile: verificação no servidor (siteverify falso por HTTP) em cadastro, login, esqueci a senha e reenvio.
Sucesso, falha, token reutilizado/ausente, timeout, 5xx, redirecionamento, meia configuração, CSP, sem enumeração de
e-mails, limite de requisições e nenhum token/segredo em log, resposta ou /api/config."""

from __future__ import annotations

import json
import logging

import pytest

from studio import turnstile
from studio.config import load_settings, secret_values
from studio.ratelimit import RateLimitConfig, Rule
from studio.web import server as srv
from studio.web.server import App

from .turnstile_fake import GOOD, SECRET, SITE_KEY, FakeTurnstile

H = {"Host": "127.0.0.1:8765", "X-Studio-Client": "game"}
PASSWORD = "uma-senha-longa-123"


@pytest.fixture
def fake():
    f = FakeTurnstile()
    yield f
    f.close()


@pytest.fixture
def on(settings, monkeypatch):
    monkeypatch.setenv("STUDIO_TURNSTILE_SITE_KEY", SITE_KEY)
    monkeypatch.setenv("STUDIO_TURNSTILE_SECRET_KEY", SECRET)
    monkeypatch.setattr(turnstile, "TIMEOUT_S", 0.4)   # o teste de demora não pode levar 5 s
    return settings


def make_app(settings, tmp_path, fake=None, signup="open", rate=False, **kw):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    app = App(8765, settings_loader=loader, sim_pacing=False, signup=signup,
              rate_limits=None if rate else RateLimitConfig(enabled=False), **kw)
    app.send_mail = lambda *a, **k: True
    if fake is not None:
        app.turnstile_url = fake.url
    return app


@pytest.fixture
def app(on, tmp_path, fake):
    return make_app(on, tmp_path, fake)


def post(app, path, body, headers=H, peer=""):
    r = app.handle("POST", path, headers, json.dumps(body).encode(), peer)
    return r.status, json.loads(r.body), r


def signup_body(email="ana@exemplo.com", **extra):
    return {"name": "Ana", "email": email, "password": PASSWORD, "consent": True, **extra}


def user_exists(app, email) -> bool:
    s, db, acc = app._db()
    try:
        return acc.user_by_email(email) is not None
    finally:
        db.close()


# ------------------------------------------------------------------ configuração
def test_off_without_both_keys_in_dev(settings, tmp_path):
    app = make_app(settings, tmp_path)
    assert not app.turnstile_on and not app.turnstile_broken
    assert post(app, "/api/auth/signup", signup_body())[0] == 200      # sem captcha: como antes
    assert json.loads(app.handle("GET", "/api/config", H, b"").body)["turnstile"] is None


def test_partial_config_dev_is_off_with_warning(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_TURNSTILE_SITE_KEY", SITE_KEY)
    app = make_app(settings, tmp_path)
    assert not app.turnstile_on and not app.turnstile_broken
    level, text = turnstile.startup_warning()
    assert level == "warning" and "STUDIO_TURNSTILE_SECRET_KEY" in text and SITE_KEY not in text
    assert post(app, "/api/auth/signup", signup_body())[0] == 200


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("only", ["STUDIO_TURNSTILE_SITE_KEY", "STUDIO_TURNSTILE_SECRET_KEY"])
def test_partial_config_in_staging_and_production_fails_closed(settings, tmp_path, monkeypatch, env, only):
    monkeypatch.setenv("STUDIO_ENV", env)
    monkeypatch.setenv(only, SECRET if "SECRET" in only else SITE_KEY)
    app = make_app(settings, tmp_path)
    level, text = turnstile.startup_warning()
    assert level == "critical" and "RECUSANDO" in text and SECRET not in text and SITE_KEY not in text
    for path, body in [("/api/auth/signup", signup_body()), ("/api/auth/login", {"email": "a@b.co", "password": "x"}),
                       ("/api/auth/forgot", {"email": "a@b.co"}), ("/api/auth/resend", {})]:
        st, d, _ = post(app, path, body)
        assert (st, d["code"]) == (503, "captcha_indisponivel"), path
    assert not user_exists(app, "ana@exemplo.com")
    assert json.loads(app.handle("GET", "/api/config", H, b"").body)["turnstile"] is None


def test_staging_without_any_key_warns_but_runs(monkeypatch):
    monkeypatch.setenv("STUDIO_ENV", "staging")
    for k in ("STUDIO_TURNSTILE_SITE_KEY", "STUDIO_TURNSTILE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    level, text = turnstile.startup_warning()
    assert level == "warning" and "desligado" in text and not turnstile.fail_closed()


def test_secret_is_masked_site_key_is_public(on):
    assert SECRET in secret_values()
    assert SITE_KEY not in secret_values()


def test_api_config_exposes_site_key_never_secret(app):
    raw = app.handle("GET", "/api/config", H, b"").body
    assert json.loads(raw)["turnstile"] == SITE_KEY and SECRET.encode() not in raw
    assert SECRET.encode() not in app.handle("GET", "/api/auth/config", H, b"").body


# ------------------------------------------------------------------ CSP (um lugar só)
def test_csp_allows_only_challenges_cloudflare_for_script_and_frame():
    for csp in (srv.CSP_APP, srv.CSP_PANEL):
        parts = {p.split(" ", 1)[0]: p.split(" ", 1)[1] for p in csp.split("; ")}
        assert "https://challenges.cloudflare.com" in parts["script-src"].split()
        assert parts["frame-src"] == "https://challenges.cloudflare.com"
        assert "unsafe-eval" not in csp and "*" not in csp
        assert parts["default-src"] == "'self'" and parts["frame-ancestors"] == "'none'"
    assert "'unsafe-inline'" not in srv.CSP_APP.split("style-src")[0].split("script-src")[1]   # app: sem script inline
    assert srv.security_headers(False)["Content-Security-Policy"] == srv.CSP_APP


# ------------------------------------------------------------------ verificação nas 4 rotas
def test_missing_or_invalid_token_is_refused_on_all_routes_before_any_lookup(app, fake):
    for path, body in [("/api/auth/signup", signup_body()), ("/api/auth/login", {"email": "ana@exemplo.com", "password": PASSWORD}),
                       ("/api/auth/forgot", {"email": "ana@exemplo.com"}), ("/api/auth/resend", {})]:
        for extra in ({}, {"captcha": ""}, {"captcha": "lixo"}, {"captcha": 123}, {"captcha": "x" * 5000}):
            st, d, _ = post(app, path, {**body, **extra})
            assert (st, d["code"]) == (400, "captcha_invalido"), (path, extra)
            assert set(d) == {"error", "code"}                   # sem detalhes
    assert not user_exists(app, "ana@exemplo.com")
    assert all(r["response"] in ("lixo",) for r in fake.requests)   # vazio/gigante/não-texto nem chegam à Cloudflare


def test_signup_login_forgot_resend_work_with_valid_token(app, fake):
    st, d, r = post(app, "/api/auth/signup", signup_body(captcha=GOOD + "-1"))
    assert st == 200 and d["ok"] and user_exists(app, "ana@exemplo.com")
    cookie = r.headers["Set-Cookie"].split(";")[0]
    st, d, _ = post(app, "/api/auth/resend", {}, {**H, "Cookie": cookie})                  # sem token: recusa
    assert (st, d["code"]) == (400, "captcha_invalido")
    st, d, _ = post(app, "/api/auth/resend", {"captcha": GOOD + "-2"}, {**H, "Cookie": cookie})
    assert st == 400 and "code" not in d and "aguarde" in d["error"]   # passou do captcha; o intervalo de reenvio é outra regra
    assert post(app, "/api/auth/login", {"email": "ana@exemplo.com", "password": PASSWORD, "captcha": GOOD + "-3"})[0] == 200
    st, d, _ = post(app, "/api/auth/forgot", {"email": "ana@exemplo.com", "captcha": GOOD + "-4"})
    assert st == 200 and d["ok"]


def test_sends_secret_response_and_remoteip_per_trust_proxy(on, tmp_path, fake):
    hdr = {**H, "Cf-Connecting-Ip": "203.0.113.9", "X-Forwarded-For": "198.51.100.7"}
    cf = make_app(on, tmp_path, fake, trust_proxy="cloudflare")
    post(cf, "/api/auth/login", {"email": "a@b.co", "password": "x", "captcha": GOOD + "-a"}, hdr)
    assert fake.requests[-1] == {"secret": SECRET, "response": GOOD + "-a", "remoteip": "203.0.113.9"}
    fw = make_app(on, tmp_path, fake, trust_proxy="forwarded")
    post(fw, "/api/auth/login", {"email": "a@b.co", "password": "x", "captcha": GOOD + "-b"}, hdr)
    assert fake.requests[-1]["remoteip"] == "198.51.100.7"
    none = make_app(on, tmp_path, fake)   # cabeçalhos de proxy não valem sem STUDIO_TRUST_PROXY
    post(none, "/api/auth/login", {"email": "a@b.co", "password": "x", "captcha": GOOD + "-c"}, hdr, "192.0.2.5")
    assert fake.requests[-1]["remoteip"] == "192.0.2.5"


def test_reused_token_is_refused(app):
    ok = {"email": "a@b.co", "password": "x", "captcha": GOOD + "-uma-vez"}
    assert post(app, "/api/auth/login", ok)[1].get("code") != "captcha_invalido"      # passou (senha errada é outro erro)
    st, d, _ = post(app, "/api/auth/login", ok)
    assert (st, d["code"]) == (400, "captcha_invalido")


def test_siteverify_failure_is_refused(app, fake):
    st, d, _ = post(app, "/api/auth/signup", signup_body(captcha="token-ruim"))
    assert (st, d["code"]) == (400, "captcha_invalido") and not user_exists(app, "ana@exemplo.com")


@pytest.mark.parametrize("mode", ["slow", "5xx", "garbage", "redirect", "bad-secret"])
def test_cloudflare_down_fails_closed_with_friendly_message(app, fake, mode):
    fake.mode = mode
    st, d, _ = post(app, "/api/auth/signup", signup_body(captcha=GOOD + "-x"))
    assert (st, d["code"]) == (503, "captcha_indisponivel")
    assert "indisponível" in d["error"] and not user_exists(app, "ana@exemplo.com")
    if mode == "redirect":
        assert fake.redirect_hits == 0     # redirecionamento nunca é seguido


def test_no_enumeration_and_invite_not_consumed_on_bad_captcha(on, tmp_path, fake):
    app = make_app(on, tmp_path, fake, signup="invite")
    s, db, acc = app._db()
    code = acc.create_invite(email=None)[0]
    db.close()
    sent = []
    app.send_mail = lambda *a, **k: sent.append(a) or True
    st, d, _ = post(app, "/api/auth/signup", signup_body(invite=code, captcha="ruim"))
    assert (st, d["code"]) == (400, "captcha_invalido")
    st, d, _ = post(app, "/api/auth/signup", signup_body(invite=code, captcha=GOOD + "-i"))   # convite continua válido
    assert st == 200
    # e-mail existente e inexistente: mesma resposta, e nada de e-mail com captcha ruim
    a = post(app, "/api/auth/forgot", {"email": "ana@exemplo.com", "captcha": "ruim"})[:2]
    b = post(app, "/api/auth/forgot", {"email": "ninguem@exemplo.com", "captcha": "ruim"})[:2]
    assert a == b == (400, {"error": srv.CAPTCHA_BAD_MSG, "code": "captcha_invalido"})
    n = len(sent)
    post(app, "/api/auth/forgot", {"email": "ana@exemplo.com", "captcha": "ruim"})
    assert len(sent) == n


def test_bad_captcha_still_counts_against_rate_limit(on, tmp_path, fake):
    cfg = RateLimitConfig(enabled=True, auth=Rule(2, 60))
    app = make_app(on, tmp_path, fake)
    app.limiter = srv.RateLimiter(cfg)
    assert post(app, "/api/auth/login", {"captcha": "ruim"})[0] == 400
    assert post(app, "/api/auth/login", {"captcha": "ruim"})[0] == 400
    st, d, r = post(app, "/api/auth/login", {"captcha": GOOD + "-r"})
    assert st == 429 and r.headers["Retry-After"]


# ------------------------------------------------------------------ segredo nunca em log nem resposta
def test_token_and_secret_never_reach_logs_or_responses(app, fake, caplog):
    caplog.set_level(logging.DEBUG)
    tokens = ["token-ruim-SEGREDO-1", GOOD + "-log"]
    seen = []
    for mode in ("normal", "slow", "5xx", "garbage", "redirect", "bad-secret"):
        fake.mode = mode
        for t in tokens:
            seen.append(post(app, "/api/auth/login", {"email": "a@b.co", "password": "x", "captcha": t})[2].body.decode())
    blob = caplog.text + "".join(seen)
    assert SECRET not in blob
    for t in tokens:
        assert t not in blob
    assert "Turnstile" in caplog.text      # o aviso existe, só que sem valores
