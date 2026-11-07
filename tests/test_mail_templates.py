"""Modelos HTML dos e-mails transacionais e o envio multipart/HTML pelos dois transportes (servidores falsos)."""

from __future__ import annotations

import logging
import re

import pytest

from studio import mail_templates as mt
from studio import mailer

from .resend_fake import FakeResendAPI
from .smtp_fake import FakeSMTP
from .test_mail import API_KEY, FROM, smtp_env
from .test_mail_resend_api import api_env

HOST = "app.kiroo.app"
LINK = f"https://{HOST}/?reset=tok_abc123"


def all_parts():
    ver = mt.verification_email("123456", 30)
    rst = mt.reset_email(LINK, 30, public_host=HOST)
    return {"verificacao": ver, "reset": rst}


def test_verification_has_code_in_subject_text_and_html():
    subject, text, html = mt.verification_email("123456", 30)
    assert "123456" in subject and "123456" in text and "123456" in html
    assert "30 minutos" in text and "30 minutos" in html
    assert "Se você não criou uma conta no Kiroo, ignore este e-mail." in text and in_html(html)


def in_html(html):
    return "Se você não criou uma conta no Kiroo, ignore este e-mail." in html


def test_reset_has_link_in_text_and_html_button():
    subject, text, html = mt.reset_email(LINK, 30, public_host=HOST)
    assert subject == "Kiroo: redefinir sua senha"
    assert LINK in text and f'href="{LINK}"' in html and "30 minutos" in html
    assert "#0E0E10" in html and "#FFFFFF" in html


@pytest.mark.parametrize("name", ["verificacao", "reset"])
def test_html_rules(name):
    _, text, html = all_parts()[name]
    assert '<html lang="pt-BR">' in html
    assert "kiroo" in html and "69.035.469/0001-62" in html and "contato@kiroo.app" in html
    assert "Christian Alves de Souza Junior LTDA" in html
    for color in ("#FAFAF8", "#E7E7E4", "#F2F2EF" if name == "verificacao" else "#0E0E10"):
        assert color in html
    assert "max-width:560px" in html and "<table" in html
    assert "http://" not in html and "<img" not in html and "@import" not in html and "url(" not in html
    assert "<script" not in html and "<link" not in html and "@font-face" not in html
    assert 'display:none' in html          # preheader oculto
    assert html.count("#FF5B2E") == 1      # laranja só no ponto do wordmark
    assert 800 < len(html) < 8000 and len(text) < 1500


def test_orange_is_never_small_text():
    _, _, html = mt.verification_email("123456", 30)
    assert re.search(r'font-size:28px[^"]*">kiroo<span style="color:#FF5B2E;">\.</span>', html)


def test_escape_of_outside_values():
    _, text, html = mt.verification_email("123456", 30, name='<script>alert("x")</script> & Cia')
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp; Cia" in html
    evil = f"https://{HOST}/?a=1&b=2"
    _, _, h2 = mt.reset_email(evil, 30, public_host=HOST)
    assert "a=1&amp;b=2" in h2 and "a=1&b=2" not in h2


def test_code_must_be_six_digits():
    for bad in ("12345", "1234567", "12345a", "<b>123", ""):
        with pytest.raises(mt.TemplateError):
            mt.verification_email(bad, 30)


@pytest.mark.parametrize("link", [
    f"http://{HOST}/?reset=x",               # não é https
    "https://evil.example/?reset=x",         # outro host
    f"https://{HOST}.evil.example/?r=x",     # sufixo enganoso
    f"https://user@{HOST}/?r=x",             # credenciais
    f'https://{HOST}/?r="><script>',         # aspas/tags
    f"https://{HOST}/ ?r=x",                 # espaço
    "javascript:alert(1)",
])
def test_unsafe_links_never_reach_html(link):
    _, text, html = mt.reset_email(link, 30, public_host=HOST)
    assert html is None and link in text      # só texto; o link do servidor segue no texto


def test_no_public_host_means_text_only():
    assert mt.reset_email("http://127.0.0.1:8765/?reset=x", 30, public_host=None)[2] is None
    assert mt.reset_email(LINK, 30, public_host="")[2] is None


def test_mailer_wrappers_use_public_host(monkeypatch):
    monkeypatch.setenv("STUDIO_PUBLIC_HOST", HOST)
    assert mailer.reset_email(LINK, 30)[2] is not None
    monkeypatch.delenv("STUDIO_PUBLIC_HOST")
    assert mailer.reset_email(LINK, 30)[2] is None
    assert mailer.verification_email("123456", 30)[2]


# --------------------------------------------------------------- transportes
def test_smtp_sends_multipart_alternative(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    with FakeSMTP(credentials=("resend", API_KEY)) as smtp:
        smtp_env(monkeypatch, smtp.port)
        assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is True
        msg = smtp.messages[0]["msg"]
    assert msg.get_content_type() == "multipart/alternative"
    plain, html = msg.get_body(("plain",)), msg.get_body(("html",))
    assert "654321" in plain.get_content() and "654321" in html.get_content()
    assert html.get_content().lstrip().startswith("<!DOCTYPE html>")
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]
    assert "654321" not in caplog.text and API_KEY not in caplog.text


def test_smtp_without_html_stays_plain(monkeypatch):
    with FakeSMTP(credentials=("resend", API_KEY)) as smtp:
        smtp_env(monkeypatch, smtp.port)
        assert mailer.send("ana@exemplo.com", "Kiroo", "oi") is True
        assert smtp.messages[0]["msg"].get_content_type() == "text/plain"


def test_resend_api_sends_html_and_text(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="studio")
    monkeypatch.setenv("STUDIO_PUBLIC_HOST", HOST)
    with FakeResendAPI("ok") as api:
        api_env(monkeypatch, api)
        assert mailer.send("ana@exemplo.com", *mailer.reset_email(LINK, 30)) is True
        body = api.requests[0]["json"]
    assert LINK in body["text"] and f'href="{LINK}"' in body["html"] and body["from"] == FROM
    assert "tok_abc123" not in caplog.text and API_KEY not in caplog.text


def test_resend_api_without_html_omits_field(monkeypatch):
    with FakeResendAPI("ok") as api:
        api_env(monkeypatch, api)
        assert mailer.send("ana@exemplo.com", "Kiroo", "oi") is True
        assert "html" not in api.requests[0]["json"]


def test_code_and_link_never_logged_on_failure_paths(monkeypatch, caplog):
    """Falha fechada (sem configuração) e erro HTTP: nem código nem link nem HTML no log (em staging)."""
    caplog.set_level(logging.DEBUG, logger="studio")
    monkeypatch.setenv("STUDIO_PUBLIC_HOST", HOST)
    monkeypatch.setenv("STUDIO_ENV", "staging")
    monkeypatch.delenv("STUDIO_SMTP_HOST", raising=False)
    monkeypatch.delenv("STUDIO_MAIL_TRANSPORT", raising=False)
    assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is False
    assert mailer.send("ana@exemplo.com", *mailer.reset_email(LINK, 30)) is False
    with FakeResendAPI("401") as api:
        api_env(monkeypatch, api)
        assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is False
        assert mailer.send("ana@exemplo.com", *mailer.reset_email(LINK, 30)) is False
    for leak in ("654321", "tok_abc123", "<html", "<table"):
        assert leak not in caplog.text


def test_dev_log_never_contains_html(monkeypatch, caplog):
    """Em dev sem envio configurado o operador lê o texto; o HTML (grande) nunca vai para o log."""
    caplog.set_level(logging.DEBUG, logger="studio")
    for var in ("STUDIO_ENV", "STUDIO_SECURE_COOKIE", "STUDIO_SMTP_HOST", "STUDIO_MAIL_TRANSPORT"):
        monkeypatch.delenv(var, raising=False)
    assert mailer.send("ana@exemplo.com", *mailer.verification_email("654321", 30)) is False
    assert "654321" in caplog.text and "<html" not in caplog.text and "<table" not in caplog.text
