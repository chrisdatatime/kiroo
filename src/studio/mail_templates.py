"""Modelos dos e-mails transacionais do Kiroo (código de confirmação e link de nova senha), em PT-BR.

Funções puras: devolvem (assunto, texto, html) e não leem ambiente, rede nem log. O texto é a versão text/plain
(mesmo conteúdo de sempre); o HTML usa só tabelas e CSS inline (Gmail/Outlook), fontes do sistema, nenhuma imagem
nem conteúdo remoto. Tudo que vem de fora (nome, link) é escapado; o link só entra se for https do host público.
"""

from __future__ import annotations

import html as _html
from urllib.parse import urlsplit

BG = "#FAFAF8"
CARD_BORDER = "#E7E7E4"
CODE_BG = "#F2F2EF"
INK = "#0E0E10"
MUTED = "#55555A"
ORANGE = "#FF5B2E"   # só no ponto do wordmark (texto grande e decorativo), nunca como texto pequeno
FOOTER_LEGAL = "Christian Alves de Souza Junior LTDA · CNPJ 69.035.469/0001-62 · contato@kiroo.app"
FOOTER_NOTE = "Se você não criou uma conta no Kiroo, ignore este e-mail."
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "SFMono-Regular,Menlo,Consolas,'Liberation Mono','Courier New',monospace"


class TemplateError(ValueError):
    pass


def _esc(value: str) -> str:
    return _html.escape(str(value), quote=True)


def safe_link(link: str, public_host: str | None) -> str | None:
    """O link só é aceito se for https://<host público>/... sem credenciais, espaços ou caracteres de controle."""
    host = (public_host or "").strip().lower()
    if not host or not isinstance(link, str) or any(c.isspace() or ord(c) < 32 or c in "<>\"'" for c in link):
        return None
    try:
        parts = urlsplit(link)
        if parts.scheme != "https" or parts.netloc.lower() != host or "@" in parts.netloc:
            return None
    except ValueError:
        return None
    return link


def _greeting(name: str | None) -> str:
    return f"Olá, {name.strip()}!" if name and name.strip() else "Olá!"


def _layout(*, preheader: str, title: str, greeting: str, intro: str, body_html: str, outro: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_esc(title)}</title>
</head>
<body style="margin:0;padding:0;background-color:{BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG};mso-hide:all;">{_esc(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{BG};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
<tr><td style="padding:0 4px 16px 4px;font-family:{FONT};font-size:28px;font-weight:700;letter-spacing:-0.5px;color:{INK};">kiroo<span style="color:{ORANGE};">.</span></td></tr>
<tr><td style="background-color:#FFFFFF;border:1px solid {CARD_BORDER};border-radius:12px;padding:32px 28px;font-family:{FONT};color:{INK};">
<h1 style="margin:0 0 16px 0;font-family:{FONT};font-size:20px;line-height:1.3;font-weight:700;color:{INK};">{_esc(title)}</h1>
<p style="margin:0 0 12px 0;font-family:{FONT};font-size:16px;line-height:1.5;color:{INK};">{_esc(greeting)}</p>
<p style="margin:0 0 20px 0;font-family:{FONT};font-size:16px;line-height:1.5;color:{INK};">{_esc(intro)}</p>
{body_html}
<p style="margin:20px 0 0 0;font-family:{FONT};font-size:14px;line-height:1.5;color:{MUTED};">{_esc(outro)}</p>
</td></tr>
<tr><td style="padding:20px 4px 0 4px;font-family:{FONT};font-size:12px;line-height:1.6;color:{MUTED};">
{_esc(FOOTER_NOTE)}<br>{_esc(FOOTER_LEGAL)}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def verification_email(code: str, minutes: int = 30, name: str | None = None) -> tuple[str, str, str]:
    """Código de confirmação (6 dígitos). Devolve (assunto, texto, html)."""
    code = str(code)
    if not (code.isascii() and code.isdigit() and len(code) == 6):
        raise TemplateError("o código de confirmação deve ter 6 dígitos")
    subject = f"Kiroo: seu código de confirmação é {code}"
    greet = _greeting(name)
    text = (f"{greet}\n\nSeu código de confirmação do Kiroo é:\n\n    {code}\n\n"
            f"Ele vale por {minutes} minutos e só pode ser usado uma vez.\n\n"
            f"{FOOTER_NOTE}\n\n— Equipe Kiroo\n")
    box = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
           f'<td align="center" style="background-color:{CODE_BG};border-radius:8px;padding:20px 12px;'
           f'font-family:{MONO};font-size:34px;line-height:1.2;font-weight:700;letter-spacing:10px;color:{INK};">'
           f'{_esc(code)}</td></tr></table>')
    page = _layout(preheader=f"Seu código de confirmação vale por {minutes} minutos.",
                   title="Confirme seu e-mail", greeting=greet,
                   intro="Use o código abaixo para confirmar seu e-mail no Kiroo:", body_html=box,
                   outro=f"Ele vale por {minutes} minutos e só pode ser usado uma vez.")
    return subject, text, page


def reset_email(link: str, minutes: int = 30, name: str | None = None, *,
                public_host: str | None = None) -> tuple[str, str, str | None]:
    """Link de nova senha. O HTML só sai (html != None) se o link for https do `public_host`; senão, só texto."""
    subject = "Kiroo: redefinir sua senha"
    greet = _greeting(name)
    text = (f"{greet}\n\nRecebemos um pedido para criar uma nova senha no Kiroo. Abra o link abaixo:\n\n"
            f"{link}\n\nO link vale por {minutes} minutos e só pode ser usado uma vez. Ao trocar a senha, as outras "
            "sessões abertas são encerradas.\n\nSe você não pediu isso, ignore este e-mail: sua senha continua a "
            "mesma.\n\n— Equipe Kiroo\n")
    url = safe_link(link, public_host)
    if url is None:
        return subject, text, None
    href = _esc(url)
    body = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center"><tr>'
            f'<td align="center" bgcolor="{INK}" style="background-color:{INK};border-radius:8px;">'
            f'<a href="{href}" target="_blank" style="display:inline-block;padding:14px 28px;font-family:{FONT};'
            f'font-size:16px;font-weight:700;line-height:1.2;color:#FFFFFF;text-decoration:none;">Criar nova senha</a>'
            f'</td></tr></table>'
            f'<p style="margin:20px 0 0 0;font-family:{FONT};font-size:13px;line-height:1.5;color:{MUTED};">'
            f'Se o botão não abrir, copie este endereço no navegador:<br>'
            f'<span style="word-break:break-all;color:{INK};">{href}</span></p>')
    page = _layout(preheader=f"O link para criar uma nova senha vale por {minutes} minutos.",
                   title="Criar nova senha", greeting=greet,
                   intro="Recebemos um pedido para criar uma nova senha no Kiroo.", body_html=body,
                   outro=f"O link vale por {minutes} minutos e só pode ser usado uma vez. Ao trocar a senha, as outras "
                         "sessões abertas são encerradas. Se você não pediu isso, ignore este e-mail: sua senha "
                         "continua a mesma.")
    return subject, text, page
