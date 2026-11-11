"""Conversão de custo (US$) em créditos do estúdio e estimativas por etapa.

Fórmula: créditos = custo_US$ × câmbio(R$/US$) × margem ÷ preço_do_crédito(R$), arredondado para cima.
Os parâmetros são PROVISÓRIOS (decisão de 27/10/2026: margem 3x) e configuráveis por ambiente.
O livro-razão de créditos (reserva/débito/estorno) é a Fase C do roteiro.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from . import pricing


@dataclass(frozen=True)
class CreditPolicy:
    fx_brl_per_usd: float
    margin: float
    credit_price_brl: float
    provisional: bool = True

    def credits(self, usd: float) -> int:
        if usd <= 0:
            return 0
        return math.ceil(usd * self.fx_brl_per_usd * self.margin / self.credit_price_brl - 1e-9)

    def usd(self, credits: float) -> float:
        """Inverso de `credits`: quanto custo (US$) cabe em N créditos."""
        if credits <= 0:
            return 0.0
        return credits * self.credit_price_brl / (self.fx_brl_per_usd * self.margin)

    def describe(self) -> str:
        tag = " (provisório)" if self.provisional else ""
        return (f"1 crédito = R$ {self.credit_price_brl:.2f}; custo × câmbio R$ {self.fx_brl_per_usd:.2f} × "
                f"margem {self.margin:g}{tag}")


def policy() -> CreditPolicy:
    env = os.environ.get
    return CreditPolicy(
        fx_brl_per_usd=float(env("STUDIO_FX_BRL_PER_USD") or 5.40),
        margin=float(env("STUDIO_CREDIT_MARGIN") or 3.0),
        credit_price_brl=float(env("STUDIO_CREDIT_PRICE_BRL") or 1.00),
        provisional=(env("STUDIO_CREDIT_POLICY_FINAL") or "").lower() not in {"1", "true", "sim"},
    )


DEFAULT_PRODUCTION_CAP_CREDITS = 80


def default_production_cap_credits() -> int:
    """STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS: limite padrão de uma produção, aplicado no servidor (padrão 80).
    Valor ausente, inválido ou <= 0 volta ao padrão: a produção nunca fica sem limite."""
    try:
        v = int(float(os.environ.get("STUDIO_DEFAULT_PRODUCTION_CAP_CREDITS") or DEFAULT_PRODUCTION_CAP_CREDITS))
    except (ValueError, OverflowError):
        return DEFAULT_PRODUCTION_CAP_CREDITS
    return v if v > 0 else DEFAULT_PRODUCTION_CAP_CREDITS


def default_production_budget_usd(account_cap_usd: float | None = None) -> float:
    """Orçamento (US$) de uma produção nova sem limite informado: o padrão em créditos convertido pela política vigente,
    limitado pelo teto efetivo do estúdio (conta/plataforma) quando houver. Teto efetivo 0 → 0 (a produção pausa)."""
    usd = policy().usd(default_production_cap_credits())
    if account_cap_usd is not None:
        usd = min(usd, max(float(account_cap_usd), 0.0))
    return usd


def stage_estimates(settings, n_scenes: int = 3, n_refs: int = 4) -> dict:
    """Estimativas por etapa paga, em US$ e créditos, com a fonte dos preços."""
    pol = policy()
    from . import budget
    _, img_src = pricing.image_cost(settings.image_model, settings.image_size, n_refs)
    _, vid_src = pricing.video_cost(settings.video_model, settings.video_resolution)
    img, vid = budget.op_cost(settings, "image", n_refs=n_refs), budget.op_cost(settings, "video")
    review = budget.review_cost("review_image")

    def pack(usd: float) -> dict:
        return {"usd": round(usd, 4), "credits": pol.credits(usd)}

    return {
        "images": pack(n_scenes * (img + review)),
        "videos": pack(n_scenes * (vid + review)),
        "redo_image": pack(img + review),
        "redo_video": pack(vid + review),
        "max_tries": {"image": settings.max_image_attempts, "video": settings.max_video_attempts},
        "policy": pol.describe(),
        "sources": {"image": img_src, "video": vid_src},
    }
