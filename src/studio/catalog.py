"""Catálogo de planos e créditos avulsos (Stripe) e preço fixo do vídeo em créditos (profiles/billing/catalog.json).

Regras:
  * Valores em CENTAVOS (inteiros) e créditos inteiros, só para EXIBIR. Quem cobra é o preço da Stripe, cujo id vem de
    variável de ambiente (`price_env` de cada plano e do avulso): nenhum id da Stripe fica no código.
  * O vídeo do motor fal.ai custa `video_price_credits` créditos FIXOS (20), independente do custo real da fal.
  * Avulso: quantidade livre, inteira, entre TOPUP_MIN_CREDITS e TOPUP_MAX_CREDITS (padrão 50 e 1.000, do catálogo).
    O servidor valida SEMPRE (`topup_quote`); o navegador só manda a quantidade, nunca valor.
  * Planos só mensais na v1 (`annual_enabled: false`); cada plano já tem o lugar do preço anual (`annual`).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_FILE = PROJECT_ROOT / "profiles" / "billing" / "catalog.json"
INTERVALS = ("month", "year")


class CatalogError(ValueError):
    """Pedido fora do catálogo (plano inexistente, avulso fora do mínimo/máximo, quantidade que não é inteira)."""


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


def _pos_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _validate(c: dict) -> None:
    def need(v, what):
        if not _pos_int(v):
            raise CatalogError(f"catálogo: {what} precisa ser inteiro positivo")
    need(c.get("video_price_credits"), "video_price_credits")
    codes = set()
    for p in c.get("plans") or []:
        need(p.get("credits"), f"créditos do plano {p.get('code')}")
        need(p.get("price_cents"), f"preço do plano {p.get('code')}")
        if not p.get("code") or p["code"] in codes or not p.get("price_env"):
            raise CatalogError("catálogo: plano sem código, repetido ou sem price_env")
        codes.add(p["code"])
    t = c.get("topup") or {}
    for k in ("unit_price_cents", "credits_per_unit", "min_credits", "max_credits"):
        need(t.get(k), f"topup.{k}")
    if not t.get("price_env") or t["min_credits"] > t["max_credits"]:
        raise CatalogError("catálogo: topup sem price_env ou com mínimo maior que o máximo")


# ------------------------------------------------------------------ preço do vídeo
def video_price_credits() -> int:
    return int(load()["video_price_credits"])


def video_price_cc() -> int:
    """Preço fixo do vídeo em centésimos de crédito (a unidade do livro-razão)."""
    return video_price_credits() * 100


# ------------------------------------------------------------------ planos
def plans() -> list[dict]:
    return list(load().get("plans") or [])


def plan(code: str) -> dict:
    for p in plans():
        if p["code"] == code:
            return p
    raise CatalogError("plano inexistente")


def annual_enabled() -> bool:
    return bool(load().get("annual_enabled"))


def _env(name: str | None) -> str | None:
    if not name:
        return None
    return (os.environ.get(name) or "").strip() or None


def price_id(code: str, interval: str = "month") -> str | None:
    """Id do preço da Stripe do plano (variável de ambiente). None = não configurado."""
    p = plan(code)
    if interval == "year":
        return _env((p.get("annual") or {}).get("price_env"))
    return _env(p.get("price_env"))


def plan_for_price(price: str | None) -> tuple[dict, str] | None:
    """(plano, intervalo) do preço da Stripe, ou None se o preço não é de nenhum plano configurado."""
    if not price:
        return None
    for p in plans():
        if _env(p.get("price_env")) == price:
            return p, "month"
        if _env((p.get("annual") or {}).get("price_env")) == price:
            return p, "year"
    return None


def price_envs() -> list[str]:
    """Variáveis de preço obrigatórias com a compra ligada (os planos mensais e o avulso; anual só se ligado)."""
    out = [p["price_env"] for p in plans()]
    if annual_enabled():
        out += [(p.get("annual") or {}).get("price_env") for p in plans() if (p.get("annual") or {}).get("price_env")]
    out.append(load()["topup"]["price_env"])
    return out


# ------------------------------------------------------------------ avulso
def _limit(env: str, default: int) -> int:
    raw = (os.environ.get(env) or "").strip()
    if not raw:
        return int(default)
    try:
        v = int(raw)
    except ValueError as exc:
        raise CatalogError(f"{env} precisa ser um inteiro") from exc
    if v <= 0:
        raise CatalogError(f"{env} precisa ser positivo")
    return v


def topup_limits() -> tuple[int, int]:
    """(mínimo, máximo) de créditos por compra avulsa: TOPUP_MIN_CREDITS / TOPUP_MAX_CREDITS ou o catálogo."""
    t = load()["topup"]
    lo, hi = _limit("TOPUP_MIN_CREDITS", t["min_credits"]), _limit("TOPUP_MAX_CREDITS", t["max_credits"])
    if lo > hi:
        raise CatalogError("TOPUP_MIN_CREDITS maior que TOPUP_MAX_CREDITS")
    return lo, hi


def topup_price_id() -> str | None:
    return _env(load()["topup"]["price_env"])


def topup_quote(credits) -> dict:
    """O que será cobrado no avulso: {credits, quantity, amount_cents}. Recusa o que não for inteiro (decimal, texto,
    booleano), negativo, abaixo do mínimo ou acima do máximo. O valor exibido é quantidade × preço unitário."""
    if isinstance(credits, bool) or not isinstance(credits, int):
        raise CatalogError("Escolha uma quantidade inteira de créditos.")
    lo, hi = topup_limits()
    if credits < lo:
        raise CatalogError(f"O mínimo do avulso é {lo} créditos.")
    if credits > hi:
        raise CatalogError(f"O máximo por compra avulsa é {hi:,} créditos.".replace(",", "."))
    t = load()["topup"]
    per = int(t["credits_per_unit"])
    if credits % per:
        raise CatalogError(f"O avulso vai de {per} em {per} créditos.")
    qty = credits // per
    return {"credits": credits, "quantity": qty, "amount_cents": qty * int(t["unit_price_cents"]),
            "unit_price_cents": int(t["unit_price_cents"])}


# ------------------------------------------------------------------ tela
def public_view() -> dict:
    """Catálogo para a tela de Planos (o navegador só exibe; quem cobra é a Stripe). Itens `show: false` ficam fora."""
    from .welcome import credits as welcome_credits
    c = load()
    per_video = c["video_price_credits"]
    lo, hi = topup_limits()
    t = c["topup"]
    return {
        "currency": c.get("currency", "BRL"), "video_price_credits": per_video, "welcome_credits": welcome_credits(),
        "annual_enabled": annual_enabled(),
        "plans": [{"code": p["code"], "name": p["name"], "credits": p["credits"], "price_cents": p["price_cents"],
                   "annual_price_cents": (p.get("annual") or {}).get("price_cents"),
                   "highlight": bool(p.get("highlight")), "videos": p["credits"] // per_video,
                   "tagline": p.get("tagline") or "", "note": p.get("note") or "", "contact_note": bool(p.get("contact_note")),
                   "features_lead": p.get("features_lead") or "",
                   "features": [{"text": str(f.get("text") or "")} for f in p.get("features") or [] if f.get("show", True)]}
                  for p in c["plans"]],
        "topup": {"unit_price_cents": int(t["unit_price_cents"]), "min_credits": lo, "max_credits": hi,
                  "shortcuts": [n for n in t.get("shortcuts") or [] if isinstance(n, int) and lo <= n <= hi]},
    }


def brl(cents: int) -> str:
    """3990 -> 'R$ 39,90'."""
    s = f"{cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"
