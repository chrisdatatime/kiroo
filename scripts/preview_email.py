"""Gera docs/preview-email.html com os dois e-mails (código fictício 123456, link fictício) para abrir no navegador.

Uso: python scripts/preview_email.py
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from studio import mail_templates as mt  # noqa: E402

HOST = "app.kiroo.app"


def main() -> None:
    ver = mt.verification_email("123456", 30)
    rst = mt.reset_email(f"https://{HOST}/?reset=EXEMPLO-FICTICIO", 30, public_host=HOST)
    frames = ""
    for title, (subject, _text, page) in (("Código de confirmação", ver), ("Redefinição de senha", rst)):
        frames += (f"<h2>{html.escape(title)}</h2><p><b>Assunto:</b> {html.escape(subject)}</p>"
                   f'<iframe title="{html.escape(title)}" srcdoc="{html.escape(page, quote=True)}"></iframe>')
    out = ROOT / "docs" / "preview-email.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>Pré-visualização dos e-mails</title>'
        "<style>body{font-family:system-ui,sans-serif;margin:24px;background:#ddd}h2{margin:32px 0 4px}"
        "iframe{width:100%;max-width:640px;height:620px;border:0;background:#fff;display:block}</style></head><body>"
        f"<h1>Pré-visualização (dados fictícios)</h1>{frames}</body></html>", encoding="utf-8")
    print(f"gerado: {out}")


if __name__ == "__main__":
    main()
