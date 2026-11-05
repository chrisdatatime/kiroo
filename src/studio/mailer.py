"""Envio de e-mails transacionais (verificação de e-mail, redefinição de senha).

Com `STUDIO_SMTP_HOST` definido, envia por SMTP (STARTTLS na 587, SSL na 465). Sem ele, a mensagem vai para o log do
servidor (só o operador vê) e `send()` devolve False, para a interface dizer a verdade ao usuário.

Variáveis: STUDIO_SMTP_HOST, STUDIO_SMTP_PORT (587), STUDIO_SMTP_USER, STUDIO_SMTP_PASSWORD, STUDIO_MAIL_FROM.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("studio")


def configured() -> bool:
    return bool(os.environ.get("STUDIO_SMTP_HOST"))


def send(to: str, subject: str, text: str) -> bool:
    """Envia o e-mail. Devolve True se saiu por SMTP, False se só foi registrado no log."""
    host = os.environ.get("STUDIO_SMTP_HOST")
    if not host:
        log.warning("E-mail para %s (sem SMTP configurado) | %s\n%s", to, subject, text)
        return False
    port = int(os.environ.get("STUDIO_SMTP_PORT") or 587)
    user = os.environ.get("STUDIO_SMTP_USER") or ""
    password = os.environ.get("STUDIO_SMTP_PASSWORD") or ""
    msg = EmailMessage()
    msg["From"] = os.environ.get("STUDIO_MAIL_FROM") or user or "kiroo@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
                if user:
                    s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls(context=ctx)
                if user:
                    s.login(user, password)
                s.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.error("Falha ao enviar e-mail para %s: %s", to, exc)
        return False
