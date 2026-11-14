"""Links e dados institucionais das telas Sobre e Minha conta, vindos do ambiente (sem env, o item some).

  STUDIO_HELP_URL, STUDIO_TERMS_URL, STUDIO_PRIVACY_URL, STUDIO_CHANGELOG_URL: só endereço https:// (qualquer outro
  esquema, como `javascript:`, é descartado). STUDIO_SUPPORT_CONTACT: e-mail, https:// ou texto livre (vira
  `contact`). STUDIO_LEGAL_NAME e STUDIO_LEGAL_CNPJ: rodapé "© 2026 Kiroo · Razão · CNPJ 00...". Nada aqui é segredo.
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote

from . import buildinfo


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _https(name: str) -> str | None:
    v = _env(name)
    return v if re.fullmatch(r"https://[^\s<>\"']+", v, re.I) else None


def _text(name: str, limit: int = 120) -> str | None:
    v = " ".join(_env(name).split())[:limit]
    return v or None


def version() -> str:
    """"Versão X": a tag do deploy (STUDIO_BUILD_VERSION), ou os 7 primeiros dígitos do commit; sem nenhum dos dois, vazio."""
    tag = _text("STUDIO_BUILD_VERSION", 40)
    if tag:
        return tag
    c = buildinfo.commit()
    return c[:7] if c != "desconhecido" else ""


def contact() -> dict | None:
    """Fale com a gente: e-mail (mailto), https (link) ou texto sem link. Sem env, None."""
    raw = _env("STUDIO_SUPPORT_CONTACT")
    if not raw:
        return None
    if raw.lower().startswith("https://") and _https("STUDIO_SUPPORT_CONTACT"):
        return {"label": "Falar com a equipe", "href": raw}
    if "@" in raw and " " not in raw and not raw.lower().startswith(("http", "javascript")):
        return {"label": raw, "href": f"mailto:{raw}?subject={quote('Suporte Kiroo')}"}
    return {"label": raw[:120], "href": None}


def view() -> dict:
    """O que a interface recebe em /api/me (`site`): cada chave ausente = item escondido."""
    return {"version": version(), "changelog_url": _https("STUDIO_CHANGELOG_URL"), "help_url": _https("STUDIO_HELP_URL"),
            "terms_url": _https("STUDIO_TERMS_URL"), "privacy_url": _https("STUDIO_PRIVACY_URL"), "contact": contact(),
            "legal_name": _text("STUDIO_LEGAL_NAME"), "legal_cnpj": _text("STUDIO_LEGAL_CNPJ", 30)}
