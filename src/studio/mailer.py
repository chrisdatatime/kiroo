"""Envio de e-mails transacionais (confirmação de e-mail, redefinição de senha), em português do Brasil.

Variáveis:
- STUDIO_SMTP_HOST, STUDIO_SMTP_PORT (587), STUDIO_SMTP_USER, STUDIO_SMTP_PASSWORD (segredo), STUDIO_MAIL_FROM.
- STUDIO_SMTP_SECURITY: starttls | ssl | none. Padrão: ssl na porta 465, starttls nas outras. `none` (texto puro)
  só é aceito para 127.0.0.1/localhost (servidor de teste); credencial nunca viaja sem TLS para fora da máquina.

Resend: STUDIO_SMTP_HOST=smtp.resend.com, STUDIO_SMTP_PORT=465 (ou 587), STUDIO_SMTP_USER=resend,
STUDIO_SMTP_PASSWORD=<chave de API>, STUDIO_MAIL_FROM="Kiroo <nao-responda@SEU-DOMINIO-VERIFICADO>".

Falha fechado: em staging/produção (STUDIO_ENV=staging|production ou STUDIO_SECURE_COOKIE=1) sem SMTP completo
(host + remetente), nada é enviado e NADA do conteúdo (código, link) vai para o log; `send()` devolve False e a
interface diz a verdade ao usuário. Só em desenvolvimento local o conteúdo aparece no log, para o operador testar.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

log = logging.getLogger("studio")

SECURITY_MODES = ("starttls", "ssl", "none")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
TIMEOUT_S = 15


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


def config_error() -> str | None:
    """O que falta para enviar (só nomes de variáveis, nunca valores). None = pronto."""
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


def build_message(to: str, subject: str, text: str) -> EmailMessage:
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
    msg["Content-Language"] = "pt-BR"          # depois do set_content, que limpa os cabeçalhos Content-*
    return msg


def send(to: str, subject: str, text: str) -> bool:
    """Envia o e-mail. True = aceito pelo servidor SMTP. False = não enviado (sem configuração ou falha)."""
    problem = config_error()
    if problem:
        if protected_env():
            # Staging/produção: nunca despeja código de confirmação nem link de senha no log. Falha fechado.
            log.warning("E-mail não enviado (%s). Em staging/produção o conteúdo não vai para o log; configure o SMTP "
                        "ou use `studio admin reset-link` / `studio admin verify-email`.", problem)
        else:  # desenvolvimento local: o operador lê o código aqui
            log.warning("E-mail para %s (SMTP não configurado: %s) | %s\n%s", to, problem, subject, text)
        return False
    host = os.environ["STUDIO_SMTP_HOST"].strip()
    port = int(os.environ.get("STUDIO_SMTP_PORT") or 587)
    user = os.environ.get("STUDIO_SMTP_USER") or ""
    password = os.environ.get("STUDIO_SMTP_PASSWORD") or ""
    try:
        msg = build_message(to, subject, text)
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
        return True
    except (OSError, smtplib.SMTPException, MailConfigError) as exc:
        # só o tipo: a mensagem do servidor pode ecoar o endereço ou a credencial
        log.error("Falha ao enviar e-mail por SMTP (%s)", type(exc).__name__)
        return False


# ------------------------------------------------------------------ mensagens (PT-BR)
def verification_email(code: str, minutes: int) -> tuple[str, str]:
    return (f"Kiroo: seu código de confirmação é {code}",
            f"Olá!\n\nSeu código de confirmação do Kiroo é:\n\n    {code}\n\n"
            f"Ele vale por {minutes} minutos e só pode ser usado uma vez.\n\n"
            "Se você não criou uma conta no Kiroo, ignore este e-mail.\n\n— Equipe Kiroo\n")


def reset_email(link: str, minutes: int) -> tuple[str, str]:
    return ("Kiroo: redefinir sua senha",
            "Olá!\n\nRecebemos um pedido para criar uma nova senha no Kiroo. Abra o link abaixo:\n\n"
            f"{link}\n\nO link vale por {minutes} minutos e só pode ser usado uma vez. Ao trocar a senha, as outras "
            "sessões abertas são encerradas.\n\nSe você não pediu isso, ignore este e-mail: sua senha continua a "
            "mesma.\n\n— Equipe Kiroo\n")


def admin_setup_email(link: str, minutes: int) -> tuple[str, str]:
    return ("Kiroo: defina a senha do administrador",
            f"Olá!\n\nAbra o link para definir a senha do administrador do Kiroo (vale por {minutes} minutos e só "
            f"pode ser usado uma vez):\n\n{link}\n\n— Equipe Kiroo\n")
