"""Envio de e-mails transacionais (confirmação de e-mail, redefinição de senha), em português do Brasil.

Variáveis:
- STUDIO_SMTP_HOST, STUDIO_SMTP_PORT (587), STUDIO_SMTP_USER, STUDIO_SMTP_PASSWORD (segredo), STUDIO_MAIL_FROM.
- STUDIO_SMTP_SECURITY: starttls | ssl | none. Padrão: ssl na porta 465, starttls nas outras. `none` (texto puro)
  só é aceito para 127.0.0.1/localhost (servidor de teste); credencial nunca viaja sem TLS para fora da máquina.

Resend: STUDIO_SMTP_HOST=smtp.resend.com, STUDIO_SMTP_PORT=465 (ou 587), STUDIO_SMTP_USER=resend,
STUDIO_SMTP_PASSWORD=<chave de API>, STUDIO_MAIL_FROM="Kiroo <nao-responda@SEU-DOMINIO-VERIFICADO>".

Transporte (STUDIO_MAIL_TRANSPORT): `smtp` (padrão) ou `resend_api`. Algumas plataformas (Railway) bloqueiam a saída
SMTP (465/587); `resend_api` envia por HTTPS (POST https://api.resend.com/emails, Authorization: Bearer <chave>) só com
a biblioteca padrão. A chave é a mesma STUDIO_SMTP_PASSWORD; STUDIO_SMTP_HOST/PORT/USER/SECURITY não são usados.

Prazo: o envio inteiro (qualquer transporte) é limitado a DEADLINE_S segundos; estourou, `send()` devolve False e a
resposta ao usuário sai logo (o cadastro nunca espera o timeout do SMTP).

Falha fechado: em staging/produção (STUDIO_ENV=staging|production ou STUDIO_SECURE_COOKIE=1) sem SMTP completo
(host + remetente), nada é enviado e NADA do conteúdo (código, link) vai para o log; `send()` devolve False e a
interface diz a verdade ao usuário. Só em desenvolvimento local o conteúdo aparece no log, para o operador testar.
"""

from __future__ import annotations

import logging
import os
import json
import smtplib
import ssl
import threading
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from . import mail_templates

log = logging.getLogger("studio")

SECURITY_MODES = ("starttls", "ssl", "none")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TRANSPORTS = ("smtp", "resend_api")
TIMEOUT_S = 8              # SMTP: por operação de socket
API_TIMEOUT_S = 10         # API HTTPS do Resend
DEADLINE_S = 12            # teto do envio inteiro, qualquer transporte
RESEND_API_URL = "https://api.resend.com/emails"


class MailConfigError(ValueError):
    pass


def protected_env() -> bool:
    """Staging/produção: nunca registra conteúdo de e-mail no log."""
    env = (os.environ.get("STUDIO_ENV") or "dev").strip().lower()
    return env in ("staging", "production") or os.environ.get("STUDIO_SECURE_COOKIE") == "1"


def _security(host: str, port: int) -> str:
    raw = (os.environ.get("STUDIO_SMTP_SECURITY") or "").strip().lower()
    mode = raw or ("ssl" if port == 465 else "starttls")
    if mode not in SECURITY_MODES:
        raise MailConfigError(f"STUDIO_SMTP_SECURITY deve ser um de: {', '.join(SECURITY_MODES)}")
    if mode == "none" and host.lower() not in LOCAL_HOSTS:
        raise MailConfigError("STUDIO_SMTP_SECURITY=none só é aceito para 127.0.0.1/localhost")
    return mode


def transport() -> str:
    raw = (os.environ.get("STUDIO_MAIL_TRANSPORT") or "").strip().lower()
    if raw and raw not in TRANSPORTS:
        raise MailConfigError(f"STUDIO_MAIL_TRANSPORT deve ser um de: {', '.join(TRANSPORTS)}")
    return raw or "smtp"


def config_error() -> str | None:
    """O que falta para enviar (só nomes de variáveis, nunca valores). None = pronto."""
    try:
        mode = transport()
    except MailConfigError as exc:
        return str(exc)
    if mode == "resend_api":
        if not (os.environ.get("STUDIO_SMTP_PASSWORD") or "").strip():
            return "STUDIO_SMTP_PASSWORD ausente (chave de API do Resend)"
        if not _sender():
            return "STUDIO_MAIL_FROM ausente ou inválido"   # a API do Resend exige remetente em qualquer ambiente
        return None
    host = (os.environ.get("STUDIO_SMTP_HOST") or "").strip()
    if not host:
        return "STUDIO_SMTP_HOST ausente"
    try:
        port = int(os.environ.get("STUDIO_SMTP_PORT") or 587)
    except ValueError:
        return "STUDIO_SMTP_PORT inválida"
    try:
        _security(host, port)
    except MailConfigError as exc:
        return str(exc)
    if protected_env() and not _sender():
        return "STUDIO_MAIL_FROM ausente ou inválido"
    if os.environ.get("STUDIO_SMTP_USER") and not os.environ.get("STUDIO_SMTP_PASSWORD"):
        return "STUDIO_SMTP_PASSWORD ausente"
    return None


def configured() -> bool:
    return config_error() is None


def _sender() -> str | None:
    raw = (os.environ.get("STUDIO_MAIL_FROM") or "").strip()
    if not raw or "\n" in raw or "\r" in raw:
        return None
    _, addr = parseaddr(raw)
    return raw if "@" in addr else None


def build_message(to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    if any(c in to + subject for c in "\r\n"):
        raise MailConfigError("destinatário ou assunto inválido")
    sender = _sender() or "Kiroo <kiroo@localhost>"
    domain = parseaddr(sender)[1].rpartition("@")[2] or "localhost"
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"   # e-mail automático: sem resposta automática de férias
    msg.set_content(text, charset="utf-8")
    if html:   # multipart/alternative: text/plain primeiro, text/html por último (o cliente prefere o último)
        msg.add_alternative(html, subtype="html", charset="utf-8")
    msg["Content-Language"] = "pt-BR"          # depois do set_content, que limpa os cabeçalhos Content-*
    return msg


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # a chave nunca segue um redirecionamento
        return None


def _send_resend_api(to: str, subject: str, text: str, html: str | None = None) -> None:
    key = (os.environ.get("STUDIO_SMTP_PASSWORD") or "").strip()
    if any(c in to + subject + key for c in "\r\n"):
        raise MailConfigError("destinatário, assunto ou chave inválido")
    body = {"from": _sender(), "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(RESEND_API_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "kiroo-studio/1.0"})
    with urllib.request.build_opener(_NoRedirect).open(req, timeout=API_TIMEOUT_S) as resp:
        if not 200 <= resp.status < 300:
            raise OSError(f"HTTP {resp.status}")
        resp.read(65536)


def _send_smtp(to: str, subject: str, text: str, html: str | None = None) -> None:
    host = os.environ["STUDIO_SMTP_HOST"].strip()
    port = int(os.environ.get("STUDIO_SMTP_PORT") or 587)
    user = os.environ.get("STUDIO_SMTP_USER") or ""
    password = os.environ.get("STUDIO_SMTP_PASSWORD") or ""
    msg = build_message(to, subject, text, html)
    mode = _security(host, port)
    ctx = ssl.create_default_context()
    if mode == "ssl":
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=TIMEOUT_S) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=TIMEOUT_S) as s:
            if mode == "starttls":
                s.starttls(context=ctx)
            if user:
                s.login(user, password)
            s.send_message(msg)


def _describe(exc: BaseException) -> str:
    # só o tipo (e o status HTTP): a mensagem do servidor pode ecoar o endereço ou a credencial
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTPError {exc.code}"
    return type(exc).__name__


def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Envia o e-mail. True = aceito pelo servidor (SMTP ou API). False = não enviado (sem configuração, falha ou prazo)."""
    problem = config_error()
    if problem:
        if protected_env():
            # Staging/produção: nunca despeja código de confirmação nem link de senha no log. Falha fechado.
            log.warning("E-mail não enviado (%s). Em staging/produção o conteúdo não vai para o log; configure o envio "
                        "ou use `studio admin reset-link` / `studio admin verify-email`.", problem)
        else:  # desenvolvimento local: o operador lê o código aqui
            log.warning("E-mail para %s (envio não configurado: %s) | %s\n%s", to, problem, subject, text)
        return False
    mode = transport()
    fn = _send_resend_api if mode == "resend_api" else _send_smtp
    outcome: list = []   # [None] = ok, [exc] = falhou

    def run() -> None:
        try:
            fn(to, subject, text, html)
            outcome.append(None)
        except Exception as exc:  # noqa: BLE001 — nada vaza para a resposta do cadastro
            outcome.append(exc)

    t = threading.Thread(target=run, name="studio-mail", daemon=True)
    t.start()
    t.join(DEADLINE_S)
    label = "a API do Resend" if mode == "resend_api" else "SMTP"
    if not outcome:
        log.error("Falha ao enviar e-mail por %s (prazo de %ss estourado)", label, DEADLINE_S)
        return False
    if outcome[0] is not None:
        log.error("Falha ao enviar e-mail por %s (%s)", label, _describe(outcome[0]))
        return False
    return True


# ------------------------------------------------------------------ mensagens (PT-BR)
def verification_email(code: str, minutes: int) -> tuple[str, str, str]:
    """(assunto, texto, html); veja mail_templates."""
    return mail_templates.verification_email(code, minutes)


def reset_email(link: str, minutes: int) -> tuple[str, str, str | None]:
    """(assunto, texto, html). O html só existe se o link for https do STUDIO_PUBLIC_HOST; senão sai só texto."""
    host = (os.environ.get("STUDIO_PUBLIC_HOST") or "").strip().lower()
    return mail_templates.reset_email(link, minutes, public_host=host)


def admin_setup_email(link: str, minutes: int) -> tuple[str, str]:
    return ("Kiroo: defina a senha do administrador",
            f"Olá!\n\nAbra o link para definir a senha do administrador do Kiroo (vale por {minutes} minutos e só "
            f"pode ser usado uma vez):\n\n{link}\n\n— Equipe Kiroo\n")
