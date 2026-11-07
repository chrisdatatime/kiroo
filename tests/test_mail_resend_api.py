"""Transporte `resend_api` (HTTPS) contra um servidor HTTP falso: sucesso, 401, 429, travado, redirecionamento;
o cadastro responde rápido quando o envio falha; chave e código nunca aparecem no log."""

from __future__ import annotations

import json
import logging
import time

import pytest

from studio import mailer
from studio.config import load_settings
from studio.web.server import SEND_FAILED_MSG, App

from .resend_fake import FakeResendAPI

API_KEY = "re_FAKE_resend_key_0123456789"
FROM = "Kiroo <nao-responda@kiroo.app>"
CLIENT = {"Host": "127.0.0.1:8765", "X-Studio-Client": "game"}


@pytest.fixture
def app(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    return App(8765, settings_loader=loader, sim_pacing=False, signup="open")


def api_env(monkeypatch, api, *, sender=FROM, key=API_KEY):
    monkeypatch.setenv("STUDIO_ENV", "staging")
    monkeypatch.setenv("STUDIO_MAIL_TRANSPORT", "resend_api")
    monkeypatch.delenv("STUDIO_SMTP_HOST", raising=False)   # SMTP não é necessário neste transporte
    if key:
        monkeypatch.setenv("STUDIO_SMTP_PASSWORD", key)
    if sender:
        monkeypatch.setenv("STUDIO_MAIL_FROM", sender)
    monkeypatch.setattr(mailer, "RESEND_API_URL", api.url)


def signup(app, email):
    return app.handle("POST", "/api/auth/signup", CLIENT,
                      json.dumps({"email": email, "password": "senha-forte-123", "consent": True}).encode())


def test_success_posts_json_with_bearer_and_sender(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    with FakeResendAPI("ok") as api:
        api_env(monkeypatch, api)
        assert mailer.configured() and mailer.transport() == "resend_api"
        assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is True
        r = api.requests[0]
    assert r["path"] == "/emails" and r["auth"] == f"Bearer {API_KEY}" and r["ctype"] == "application/json"
    assert r["json"]["from"] == FROM and r["json"]["to"] == ["ana@exemplo.com"]
    assert "654321" in r["json"]["text"] and "654321" in r["json"]["subject"]
    assert "654321" not in caplog.text and API_KEY not in caplog.text


@pytest.mark.parametrize("mode,expected", [("401", "HTTPError 401"), ("429", "HTTPError 429")])
def test_http_errors_fail_closed_and_log_only_status(monkeypatch, caplog, mode, expected):
    caplog.set_level(logging.DEBUG, logger="studio")
    with FakeResendAPI(mode) as api:
        api_env(monkeypatch, api)
        assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is False
    assert expected in caplog.text and "Resend" in caplog.text
    for leak in ("654321", API_KEY, "RECUSADA", "ana@exemplo.com"):
        assert leak not in caplog.text


def test_redirect_is_not_followed_so_the_key_stays_put(monkeypatch, caplog):
    with FakeResendAPI("redirect") as api:
        api_env(monkeypatch, api)
        assert mailer.send("ana@exemplo.com", "Kiroo", "oi") is False
        assert [x["path"] for x in api.requests] == ["/emails"]
    assert API_KEY not in caplog.text


def test_timeout_returns_false_quickly(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    monkeypatch.setattr(mailer, "API_TIMEOUT_S", 0.5)
    monkeypatch.setattr(mailer, "DEADLINE_S", 3)
    with FakeResendAPI("hang") as api:
        api_env(monkeypatch, api)
        t0 = time.monotonic()
        assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is False
        assert time.monotonic() - t0 < 3
    assert "Falha ao enviar e-mail" in caplog.text
    assert "654321" not in caplog.text and API_KEY not in caplog.text


def test_overall_deadline_caps_a_stuck_transport(monkeypatch, caplog):
    """Mesmo que o transporte ignore o timeout de socket (DNS travado), send() sai no prazo."""
    caplog.set_level(logging.DEBUG, logger="studio")
    monkeypatch.setattr(mailer, "DEADLINE_S", 0.3)
    monkeypatch.setattr(mailer, "_send_smtp", lambda *a: time.sleep(3))
    monkeypatch.setenv("STUDIO_ENV", "staging")
    monkeypatch.setenv("STUDIO_SMTP_HOST", "smtp.resend.com")
    monkeypatch.setenv("STUDIO_SMTP_PASSWORD", API_KEY)
    monkeypatch.setenv("STUDIO_MAIL_FROM", FROM)
    t0 = time.monotonic()
    assert mailer.send("ana@exemplo.com", "Kiroo", "oi") is False
    assert time.monotonic() - t0 < 2 and "prazo" in caplog.text


@pytest.mark.parametrize("drop", ["STUDIO_SMTP_PASSWORD", "STUDIO_MAIL_FROM"])
def test_missing_key_or_sender_fails_closed(monkeypatch, caplog, drop):
    monkeypatch.setenv("STUDIO_ENV", "staging")
    monkeypatch.setenv("STUDIO_MAIL_TRANSPORT", "resend_api")
    monkeypatch.setenv("STUDIO_SMTP_PASSWORD", API_KEY)
    monkeypatch.setenv("STUDIO_MAIL_FROM", FROM)
    monkeypatch.delenv(drop)
    monkeypatch.setattr(mailer.urllib.request, "build_opener", lambda *a: (_ for _ in ()).throw(AssertionError("conectou")))
    assert not mailer.configured() and drop in mailer.config_error()
    assert mailer.send("ana@exemplo.com", "Kiroo: teste", "código 654321") is False
    assert "654321" not in caplog.text and API_KEY not in caplog.text


def test_unknown_transport_is_refused(monkeypatch):
    monkeypatch.setenv("STUDIO_MAIL_TRANSPORT", "pombo")
    assert not mailer.configured() and "STUDIO_MAIL_TRANSPORT" in mailer.config_error()
    assert mailer.send("ana@exemplo.com", "x", "y") is False


def test_header_injection_is_refused(monkeypatch):
    with FakeResendAPI("ok") as api:
        api_env(monkeypatch, api)
        assert mailer.send("ana@exemplo.com\r\nBcc: x@y.com", "Kiroo", "oi") is False
        assert not api.requests


def test_signup_answers_fast_with_message_when_send_fails(app, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    monkeypatch.setattr(mailer, "API_TIMEOUT_S", 0.5)
    monkeypatch.setattr(mailer, "DEADLINE_S", 3)
    with FakeResendAPI("hang") as api:
        api_env(monkeypatch, api)
        t0 = time.monotonic()
        r = signup(app, "ana@exemplo.com")
        elapsed = time.monotonic() - t0
    data = json.loads(r.body)
    assert r.status == 200 and data["sent"] is False
    assert data["message"] == SEND_FAILED_MSG and "administrador" in data["message"]
    assert elapsed < 4
    assert "Set-Cookie" in r.headers   # a conta entra mesmo assim (modo DEMO); o código fica com o administrador
    assert API_KEY not in caplog.text


def test_signup_success_has_no_failure_message(app, monkeypatch):
    with FakeResendAPI("ok") as api:
        api_env(monkeypatch, api)
        data = json.loads(signup(app, "bia@exemplo.com").body)
        assert data["sent"] is True and "message" not in data and len(api.requests) == 1
