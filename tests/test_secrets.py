"""Segredos: secret_values() cobre Gemini, Anthropic, Google OAuth, SMTP e MP_*; nenhum aparece em log (inclusive
traceback), /readyz, resposta de erro ou erro mostrado na interface; stack trace nunca vai ao cliente."""

from __future__ import annotations

import http.client
import json
import logging
import threading
import urllib.error

import pytest

from studio.config import load_settings, secret_values
from studio.logs import JsonFormatter, redact, setup_logging
from studio.providers.gemini import _classify
from studio.web import server as srv
from studio.web.server import App, make_handler

from .conftest import FAKE_KEY

SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-FAKE-anthropic-0123456789",
    "STUDIO_GOOGLE_CLIENT_SECRET": "GOCSPX-FAKE-google-secret-0123",
    "STUDIO_SMTP_PASSWORD": "re_FAKE_smtp_password_0123456789",
    "MP_ACCESS_TOKEN": "APP_USR-FAKE-mercadopago-0123456789",
    "MP_WEBHOOK_SECRET": "whsec-FAKE-mercadopago-0123456789",
    "MP_CLIENT_SECRET": "mpcs-FAKE-client-secret-0123456789",
    "BACKUP_R2_SECRET_ACCESS_KEY": "r2-FAKE-secret-access-key-0123456789",
}
ALL = [FAKE_KEY, *SECRETS.values()]


@pytest.fixture
def secrets_env(settings, monkeypatch):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    return settings


@pytest.fixture
def app(secrets_env, tmp_path):
    s = secrets_env

    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=s.data_dir, assets_dir=s.assets_dir,
                             profiles_dir=s.profiles_dir, x264_preset="ultrafast")
    return App(8765, settings_loader=loader, sim_pacing=False)


def leaked(text) -> list[str]:
    return [s for s in ALL if s in str(text)]


def test_secret_values_covers_every_provider(secrets_env, monkeypatch):
    values = secrets_env.secret_values()
    assert set(ALL) <= set(values)
    monkeypatch.setenv("MP_PUBLIC_KEY_NOVO", "APP_USR-qualquer-coisa-nova")   # qualquer MP_* novo entra sozinho
    assert "APP_USR-qualquer-coisa-nova" in secret_values()
    assert "STUDIO_SMTP_USER" not in "".join(values)


def test_log_file_and_traceback_are_masked(secrets_env, tmp_path):
    log_dir = tmp_path / "logs"
    setup_logging(log_dir, secrets_env.secret_values())
    log = logging.getLogger("studio")
    try:
        try:
            raise RuntimeError("provedor recusou: " + " ".join(ALL))
        except RuntimeError:
            log.error("falhou com %s", SECRETS["ANTHROPIC_API_KEY"], exc_info=True)
        log.warning("chave %s", FAKE_KEY)
    finally:
        for h in list(log.handlers):
            h.close()
            log.removeHandler(h)
    text = (log_dir / "studio.log").read_text(encoding="utf-8")
    assert "Traceback" in text and "***" in text and not leaked(text)


def test_json_logs_are_masked(secrets_env):
    rec = logging.LogRecord("studio", logging.ERROR, __file__, 1, "x %s", (SECRETS["MP_ACCESS_TOKEN"],), None)
    try:
        raise ValueError(FAKE_KEY)
    except ValueError:
        import sys
        rec.exc_info = sys.exc_info()
    line = JsonFormatter(secrets_env.secret_values()).format(rec)
    assert not leaked(line) and json.loads(line)["error"] == "ValueError"


def test_readyz_never_shows_secrets(app, monkeypatch):
    r = app.health("/readyz")
    assert r.status == 200 and not leaked(r.body)
    monkeypatch.setattr(app, "settings", lambda: (_ for _ in ()).throw(RuntimeError("falha " + FAKE_KEY)))
    r = app.health("/readyz")
    assert r.status == 503 and not leaked(r.body) and b"falha" not in r.body


def test_error_responses_are_masked(app, monkeypatch):
    from .conftest import login_app
    h = {}
    login_app(app, h)

    def boom(*a, **k):
        raise ValueError("o provedor disse: chave " + SECRETS["ANTHROPIC_API_KEY"] + " inválida")
    monkeypatch.setattr(app, "_get", boom)
    r = app.handle("GET", "/api/spend", h, b"")
    assert r.status == 400 and not leaked(r.body) and "***" in json.loads(r.body)["error"]


def test_production_error_shown_in_ui_is_masked(app, monkeypatch):
    monkeypatch.setattr(app, "orch_for", lambda pid: (_ for _ in ()).throw(RuntimeError("Gemini 403 key=" + FAKE_KEY)))
    app._run("prod_0123456789")
    assert "RuntimeError" in app.errors["prod_0123456789"] and not leaked(app.errors["prod_0123456789"])


def test_provider_error_saved_on_attempt_is_masked(secrets_env):
    err = _classify(RuntimeError(f"400 Bad Request for url ...?key={FAKE_KEY}"))
    assert not leaked(str(err)) and "***" in str(err)
    assert redact("x " + SECRETS["MP_WEBHOOK_SECRET"]) == "x ***"


def test_google_login_failure_logs_no_secret(app, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    app.google_client_id, app.google_client_secret = "cliente.apps.googleusercontent.com", SECRETS["STUDIO_GOOGLE_CLIENT_SECRET"]

    def fail(url, data=None, headers=None):
        raise urllib.error.URLError(f"recusado: client_secret={data and data.get('client_secret')}")
    app.google_http = fail
    base = {"Host": "127.0.0.1:8765"}
    start = app.handle("GET", "/api/auth/google/start", base, b"")   # state real: guardado no servidor, uso único
    state = start.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
    h = {**base, "Cookie": f"studio_oauth={state}"}
    r = app.handle("GET", f"/api/auth/google/callback?state={state}&code=abc", h, b"")
    assert r.status == 302 and "google_failed" in r.headers["Location"]
    assert not leaked(caplog.text) and "URLError" in caplog.text


def test_unexpected_exception_returns_generic_500_without_stack_trace(app, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")

    def explode(*a, **k):
        raise RuntimeError("detalhe interno " + FAKE_KEY + " em /srv/app/studio/web/server.py")
    monkeypatch.setattr(app, "handle", explode)
    httpd = srv.StudioHTTPServer(("127.0.0.1", 0), make_handler(app))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        for method in ("GET", "POST"):
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
            c.request(method, "/api/state", body=b"{}" if method == "POST" else None)
            resp = c.getresponse()
            body = resp.read()
            c.close()
            assert resp.status == 500 and json.loads(body) == {"error": "erro interno"}
            assert b"Traceback" not in body and b"server.py" not in body and not leaked(body)
            assert resp.getheader("X-Request-Id")
    finally:
        httpd.shutdown()
        httpd.server_close()
