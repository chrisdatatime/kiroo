"""E-mail transacional ponta a ponta com um servidor SMTP falso: confirmação de e-mail e nova senha em PT-BR,
códigos de uso único e expiração curta, falha fechada em staging/produção sem SMTP (nada de código ou link no log)."""

from __future__ import annotations

import json
import logging
import re

import pytest

from studio import accounts as accounts_mod
from studio import mailer
from studio.config import load_settings
from studio.web.server import App

from .smtp_fake import FakeSMTP

BASE = {"Host": "127.0.0.1:8765"}
CLIENT = {**BASE, "X-Studio-Client": "game"}
API_KEY = "re_FAKE_resend_key_0123456789"
FROM = "Kiroo <nao-responda@kiroo.app>"


@pytest.fixture
def app(settings, tmp_path):
    def loader():
        return load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                             profiles_dir=settings.profiles_dir, x264_preset="ultrafast")
    return App(8765, settings_loader=loader, sim_pacing=False, signup="open")


def smtp_env(monkeypatch, port, *, env="staging", sender=FROM, security="none"):
    monkeypatch.setenv("STUDIO_ENV", env)
    monkeypatch.setenv("STUDIO_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("STUDIO_SMTP_PORT", str(port))
    monkeypatch.setenv("STUDIO_SMTP_SECURITY", security)
    monkeypatch.setenv("STUDIO_SMTP_USER", "resend")
    monkeypatch.setenv("STUDIO_SMTP_PASSWORD", API_KEY)
    if sender:
        monkeypatch.setenv("STUDIO_MAIL_FROM", sender)


def call(app, method, path, body=None, headers=None):
    r = app.handle(method, path, headers or CLIENT, json.dumps(body or {}).encode())
    return r, (json.loads(r.body) if r.body else {})


def body_of(m) -> str:
    return m["msg"].get_body(("plain",)).get_content()


def test_signup_verify_and_reset_end_to_end_over_smtp(app, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    with FakeSMTP(credentials=("resend", API_KEY)) as smtp:
        smtp_env(monkeypatch, smtp.port)
        assert call(app, "GET", "/api/auth/config")[1]["email"] is True

        r, data = call(app, "POST", "/api/auth/signup", {"email": "Ana@Exemplo.com", "password": "senha-forte-123", "consent": True})
        assert r.status == 200 and data["sent"] is True
        cookie = r.headers["Set-Cookie"].split(";")[0]
        sess = {**CLIENT, "Cookie": cookie}

        m = smtp.messages[0]
        assert m["auth"] == ("resend", API_KEY)              # usuário "resend" + chave de API como senha
        assert m["to"] == ["ana@exemplo.com"] and m["msg"]["To"] == "ana@exemplo.com"
        assert m["msg"]["From"] == FROM and m["from"] == "nao-responda@kiroo.app"
        assert m["msg"]["Content-Language"] == "pt-BR" and m["msg"]["Message-ID"].endswith("@kiroo.app>")
        text = body_of(m)
        assert "código de confirmação" in text and "uma vez" in text and "30 minutos" in text
        code = re.search(r"\b(\d{6})\b", text).group(1)
        assert code in m["msg"]["Subject"]

        wrong = "000000" if code != "000000" else "111111"
        assert call(app, "POST", "/api/auth/verify", {"code": wrong}, sess)[0].status == 400
        assert call(app, "POST", "/api/auth/verify", {"code": code}, sess)[0].status == 200
        r, data = call(app, "POST", "/api/auth/verify", {"code": code}, sess)   # uso único
        assert r.status == 400 and "expirado" in data["error"]
        assert json.loads(app.handle("GET", "/api/me", {**BASE, "Cookie": cookie}, b"").body)["user"]["email_verified"]

        # esqueci a senha: dois pedidos seguidos => só o último link vale
        for _ in range(2):
            r, data = call(app, "POST", "/api/auth/forgot", {"email": "ana@exemplo.com"})
            assert r.status == 200 and data["sent"] is True
        links = [re.search(r"(http://127\.0\.0\.1:8765/\?reset=([\w-]+))", body_of(x)) for x in smtp.messages[1:3]]
        assert all(links) and smtp.messages[1]["msg"]["Subject"] == "Kiroo: redefinir sua senha"
        assert "só pode ser usado uma vez" in body_of(smtp.messages[1])
        old, new = links[0].group(2), links[1].group(2)
        assert call(app, "POST", "/api/auth/reset", {"token": old, "password": "outra-senha-456"})[0].status == 400
        assert call(app, "POST", "/api/auth/reset", {"token": new, "password": "outra-senha-456"})[0].status == 200
        assert call(app, "POST", "/api/auth/reset", {"token": new, "password": "mais-uma-789xx"})[0].status == 400
        assert app.handle("GET", "/api/me", {**BASE, "Cookie": cookie}, b"").status == 401   # sessões antigas caem
        assert call(app, "POST", "/api/auth/login", {"email": "ana@exemplo.com", "password": "outra-senha-456"})[0].status == 200

        # pedido para e-mail sem conta: mesma resposta, nenhum e-mail
        n = len(smtp.messages)
        r, data = call(app, "POST", "/api/auth/forgot", {"email": "ninguem@exemplo.com"})
        assert r.status == 200 and len(smtp.messages) == n

    for secret in (code, old, new, API_KEY):
        assert secret not in caplog.text


def test_codes_expire_quickly(app, monkeypatch):
    with FakeSMTP() as smtp:
        smtp_env(monkeypatch, smtp.port)
        r, _ = call(app, "POST", "/api/auth/signup", {"email": "bia@exemplo.com", "password": "senha-forte-123", "consent": True})
        sess = {**CLIENT, "Cookie": r.headers["Set-Cookie"].split(";")[0]}
        code = re.search(r"\b(\d{6})\b", body_of(smtp.messages[0])).group(1)
        call(app, "POST", "/api/auth/forgot", {"email": "bia@exemplo.com"})
        token = re.search(r"reset=([\w-]+)", body_of(smtp.messages[1])).group(1)
    assert accounts_mod.VERIFY_MINUTES <= 30 and accounts_mod.RESET_MINUTES <= 30
    s, db, _ = app._db()
    try:
        db.conn.execute("UPDATE email_codes SET expires_at='2000-01-01T00:00:00+00:00'")
        db.conn.execute("UPDATE password_resets SET expires_at='2000-01-01T00:00:00+00:00'")
    finally:
        db.close()
    assert call(app, "POST", "/api/auth/verify", {"code": code}, sess)[0].status == 400
    assert call(app, "POST", "/api/auth/reset", {"token": token, "password": "outra-senha-456"})[0].status == 400


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize("partial", [False, True])
def test_staging_and_production_without_smtp_fail_closed(app, monkeypatch, caplog, env, partial):
    """Sem SMTP (ou sem remetente): sent=false e nenhum código/link vai para o log, em nenhum nível."""
    caplog.set_level(logging.DEBUG, logger="studio")
    monkeypatch.setenv("STUDIO_ENV", env)
    if partial:   # host definido mas sem STUDIO_MAIL_FROM: também não envia
        monkeypatch.setenv("STUDIO_SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("STUDIO_SMTP_SECURITY", "none")
    codes, tokens = [], []
    real_code, real_reset = accounts_mod.Accounts.start_verification, accounts_mod.Accounts.start_reset
    monkeypatch.setattr(accounts_mod.Accounts, "start_verification", lambda self, uid: codes.append(real_code(self, uid)) or codes[-1])
    monkeypatch.setattr(accounts_mod.Accounts, "start_reset", lambda self, e: tokens.append(real_reset(self, e)) or tokens[-1])
    sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", lambda *a, **k: sent.append(a) or (_ for _ in ()).throw(AssertionError("não deveria conectar")))

    assert call(app, "GET", "/api/auth/config")[1]["email"] is False
    r, data = call(app, "POST", "/api/auth/signup", {"email": "caio@exemplo.com", "password": "senha-forte-123", "consent": True})
    assert r.status == 200 and data["sent"] is False
    r, data = call(app, "POST", "/api/auth/forgot", {"email": "caio@exemplo.com"})
    assert r.status == 200 and data["sent"] is False and "administrador" in data["message"]
    assert codes and tokens and not sent
    for secret in codes + tokens:
        assert secret not in caplog.text
    assert "E-mail não enviado" in caplog.text


def test_dev_without_smtp_still_shows_the_code_to_the_local_operator(app, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    codes = []
    real_code = accounts_mod.Accounts.start_verification
    monkeypatch.setattr(accounts_mod.Accounts, "start_verification", lambda self, uid: codes.append(real_code(self, uid)) or codes[-1])
    r, data = call(app, "POST", "/api/auth/signup", {"email": "dev@exemplo.com", "password": "senha-forte-123", "consent": True})
    assert data["sent"] is False and codes[0] in caplog.text


class _Recorder:
    calls: list = []

    def __init__(self, host, port, **kw):
        self.calls.append(("open", type(self).__name__, host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def login(self, user, pw):
        self.calls.append(("login", user, pw))

    def send_message(self, msg):
        self.calls.append(("send", msg["From"], msg["To"]))


class _SMTP(_Recorder):
    pass


class _SMTP_SSL(_Recorder):
    pass


@pytest.mark.parametrize("port,cls,steps", [(465, "_SMTP_SSL", ["open", "login", "send"]),
                                            (587, "_SMTP", ["open", "starttls", "login", "send"])])
def test_resend_settings_use_tls_and_api_key_as_password(monkeypatch, port, cls, steps):
    for var in ("STUDIO_SMTP_SECURITY", "STUDIO_ENV", "STUDIO_SECURE_COOKIE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STUDIO_SMTP_HOST", "smtp.resend.com")
    monkeypatch.setenv("STUDIO_SMTP_PORT", str(port))
    monkeypatch.setenv("STUDIO_SMTP_USER", "resend")
    monkeypatch.setenv("STUDIO_SMTP_PASSWORD", API_KEY)
    monkeypatch.setenv("STUDIO_MAIL_FROM", FROM)
    _Recorder.calls = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _SMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _SMTP_SSL)
    assert mailer.send("ana@exemplo.com", *mailer.verification_email("123456", 30)) is True
    assert [c[0] for c in _Recorder.calls] == steps
    assert _Recorder.calls[0][1:] == (cls, "smtp.resend.com", port)
    assert ("login", "resend", API_KEY) in _Recorder.calls
    assert ("send", FROM, "ana@exemplo.com") in _Recorder.calls


def test_plaintext_smtp_is_refused_outside_localhost(monkeypatch, caplog):
    monkeypatch.setenv("STUDIO_ENV", "staging")
    monkeypatch.setenv("STUDIO_SMTP_HOST", "smtp.resend.com")
    monkeypatch.setenv("STUDIO_SMTP_SECURITY", "none")
    monkeypatch.setenv("STUDIO_SMTP_USER", "resend")
    monkeypatch.setenv("STUDIO_SMTP_PASSWORD", API_KEY)
    monkeypatch.setenv("STUDIO_MAIL_FROM", FROM)
    monkeypatch.setattr(mailer.smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(AssertionError("conectou")))
    assert not mailer.configured() and "localhost" in mailer.config_error()
    assert mailer.send("ana@exemplo.com", "Kiroo: teste", "código 654321") is False
    assert "654321" not in caplog.text and API_KEY not in caplog.text


def test_smtp_failure_logs_only_the_error_type(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    with FakeSMTP(credentials=("resend", "outra-chave")) as smtp:   # servidor recusa a credencial
        smtp_env(monkeypatch, smtp.port)
        assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is False
        assert not smtp.messages
    assert "SMTPAuthenticationError" in caplog.text
    assert "654321" not in caplog.text and API_KEY not in caplog.text


def test_header_injection_is_refused(monkeypatch):
    with FakeSMTP() as smtp:
        smtp_env(monkeypatch, smtp.port)
        assert mailer.send("ana@exemplo.com\r\nBcc: x@y.com", "Kiroo", "oi") is False
        assert not smtp.messages
