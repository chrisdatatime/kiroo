"""Catálogo de compra de créditos e preço fixo do vídeo em créditos (profiles/billing/catalog.json).

Regras:
  * Valores em CENTAVOS (inteiros) e créditos inteiros. Todo preço é calculado aqui, no servidor: o navegador só
    escolhe um código de pacote ou uma quantidade avulsa, nunca envia valor.
  * O vídeo do motor fal.ai (Claro, e Escuro quando ligado) custa `video_price_credits` créditos FIXOS, independente
    do custo real da fal (que continua na tabela de custos em US$, só para os tetos/orçamento operacional).
  * "Economize X%" é calculado contra o preço unitário do avulso (`unit_price_cents`).
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_FILE = PROJECT_ROOT / "profiles" / "billing" / "catalog.json"


class CatalogError(ValueError):
    """Pedido de compra fora do catálogo (pacote inexistente, avulso fora do mínimo/incremento/máximo)."""


def _file() -> Path:
    raw = (os.environ.get("STUDIO_CREDIT_CATALOG_FILE") or "").strip()
    return Path(raw) if raw else DEFAULT_FILE


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate(data)
    return data


def load() -> dict:
    f = _file()
    return _load(str(f), f.stat().st_mtime)


def _validate(c: dict) -> None:
    def pos_int(v, what):
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise CatalogError(f"catálogo: {what} precisa ser inteiro positivo")
    pos_int(c.get("video_price_credits"), "video_price_credits")
    pos_int(c.get("unit_price_cents"), "unit_price_cents")
    codes = set()
    for p in c.get("packages") or []:
        pos_int(p.get("credits"), f"créditos do pacote {p.get('code')}")
        pos_int(p.get("price_cents"), f"preço do pacote {p.get('code')}")
        if not p.get("code") or p["code"] in codes:
            raise CatalogError("catálogo: código de pacote vazio ou repetido")
        codes.add(p["code"])
    cu = c.get("custom") or {}
    for k in ("unit_price_cents", "min_credits", "step_credits", "max_credits"):
        pos_int(cu.get(k), f"custom.{k}")
    if cu["min_credits"] % cu["step_credits"] or cu["max_credits"] % cu["step_credits"] or cu["min_credits"] > cu["max_credits"]:
        raise CatalogError("catálogo: mínimo e máximo do avulso precisam ser múltiplos do incremento (mínimo <= máximo)")


# ------------------------------------------------------------------ preço do vídeo
def video_price_credits() -> int:
    return int(load()["video_price_credits"])


def video_price_cc() -> int:
    """Preço fixo do vídeo em centésimos de crédito (a unidade do livro-razão)."""
    return video_price_credits() * 100


# ------------------------------------------------------------------ compra
def savings_pct(credits: int, price_cents: int, unit_cents: int) -> int:
    """Desconto do pacote contra o avulso, arredondado para baixo (nunca promete mais do que dá)."""
    full = credits * unit_cents
    if full <= 0 or price_cents >= full:
        return 0
    return math.floor((full - price_cents) * 100 / full)


def package(code: str) -> dict:
    for p in load()["packages"]:
        if p["code"] == code:
            return p
    raise CatalogError("pacote inexistente")


def custom_total_cents(credits) -> int:
    """Total do avulso. Recusa fora do mínimo, do incremento ou do máximo (e qualquer coisa que não seja inteiro)."""
    cu = load()["custom"]
    if isinstance(credits, bool) or not isinstance(credits, int):
        raise CatalogError("quantidade de créditos inválida")
    if credits < cu["min_credits"]:
        raise CatalogError(f"o mínimo do avulso é {cu['min_credits']} créditos")
    if credits > cu["max_credits"]:
        raise CatalogError(f"o máximo por compra avulsa é {cu['max_credits']} créditos")
    if credits % cu["step_credits"]:
        raise CatalogError(f"o avulso vai de {cu['step_credits']} em {cu['step_credits']} créditos")
    return credits * cu["unit_price_cents"]


def quote(package_code: str | None = None, credits=None) -> dict:
    """O que será cobrado: {package_code, credits, amount_cents, label}. `package_code` OU `credits` (avulso)."""
    if package_code:
        p = package(str(package_code))
        return {"package_code": p["code"], "credits": p["credits"], "amount_cents": p["price_cents"],
                "label": f"Pacote {p['name']}"}
    total = custom_total_cents(credits)
    return {"package_code": "avulso", "credits": credits, "amount_cents": total, "label": "Créditos avulsos"}


def public_view() -> dict:
    """Catálogo para a tela "Comprar créditos" (o navegador só exibe; o preço cobrado sai de `quote`)."""
    c = load()
    unit, per_video = c["unit_price_cents"], c["video_price_credits"]
    return {
        "currency": c.get("currency", "BRL"), "video_price_credits": per_video, "unit_price_cents": unit,
        "packages": [{"code": p["code"], "name": p["name"], "credits": p["credits"], "price_cents": p["price_cents"],
                      "highlight": bool(p.get("highlight")), "videos": p["credits"] // per_video,
                      "savings_pct": savings_pct(p["credits"], p["price_cents"], unit)} for p in c["packages"]],
        "custom": {k: c["custom"][k] for k in ("unit_price_cents", "min_credits", "step_credits", "max_credits")}
        | {"shortcuts": list(c["custom"].get("shortcuts") or []),
           "hint_from_credits": c["custom"].get("hint_from_credits"), "hint_package": c["custom"].get("hint_package")},
    }


def brl(cents: int) -> str:
    """7990 -> 'R$ 79,90'."""
    s = f"{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"
