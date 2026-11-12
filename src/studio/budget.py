"""Dois freios diferentes, que não se misturam:

(a) SALDO DO CLIENTE — créditos comprados/concedidos ao estúdio (credits.Ledger). Antes de começar, a produção RESERVA
    o PRÉ-ORÇAMENTO (custo estimado do vídeo completo). Sem saldo para isso a produção não começa. O cliente nunca paga
    mais do que o pré-orçamento + os ajustes extras que ele mesmo autorizou; falha técnica não é cobrada.
(b) ORÇAMENTO OPERACIONAL DA PRODUÇÃO — freio interno do Kiroo (productions.budget_usd) contra laço ou estimativa ruim.
    Atingi-lo NUNCA vira cobrança nem pedido de upgrade: pausa as chamadas externas com o código estável
    `ops_budget_reached`, avisa o administrador e o cliente vê só "estamos finalizando".

O teto mensal (paid_gate / `studio admin set-cap`) é um terceiro freio, independente: vale o que bloquear primeiro.
As estimativas saem da tabela de custos por operação (profiles/billing/operation_costs.json), não de números soltos.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from functools import lru_cache
from pathlib import Path

from . import pricing
from .config import PROJECT_ROOT

log = logging.getLogger("studio")

DEFAULT_COSTS_FILE = PROJECT_ROOT / "profiles" / "billing" / "operation_costs.json"
OPERATIONS = ("plan", "image", "review_image", "video", "review_video")

# Códigos estáveis do motivo de pausa (a interface e o administrador leem o código, não o texto).
OPS_BUDGET_REACHED = "ops_budget_reached"
CREDITS_INSUFFICIENT = "credits_insufficient"
MONTHLY_CAP = "monthly_cap"
PAID_GATE = "paid_gate"
PROVIDER_BILLING = "provider_billing"

CLIENT_MESSAGES = {
    OPS_BUDGET_REACHED: "Estamos finalizando seu vídeo. A equipe do Kiroo já foi avisada e avisaremos quando estiver "
                        "pronto. Nada a mais será cobrado por isso.",
}


class AdjustmentNeedsAuthorization(Exception):
    """Ajuste além dos incluídos: só segue com autorização explícita do cliente, com o custo visível."""

    def __init__(self, scene: int, stage: str, cost_cc: int, included: int, used: int):
        self.scene, self.stage, self.cost_cc, self.included, self.used = scene, stage, cost_cc, included, used
        super().__init__(f"ajuste extra da cena {scene} custa {cost_cc / 100:.2f} créditos e precisa de autorização")


# ------------------------------------------------------------------ configuração
def _int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        v = int(float(os.environ.get(name) or default))
    except (ValueError, OverflowError):
        return default
    return v if v >= minimum else default


def _float_env(name: str, default: float, minimum: float) -> float:
    try:
        v = float(os.environ.get(name) or default)
    except ValueError:
        return default
    return v if math.isfinite(v) and v >= minimum else default


def image_tries_per_scene() -> int:
    """STUDIO_ESTIMATE_IMAGE_TRIES_PER_SCENE (padrão 2): imagens previstas por cena no pré-orçamento."""
    return _int_env("STUDIO_ESTIMATE_IMAGE_TRIES_PER_SCENE", 2, 1)


def video_tries_per_scene() -> int:
    """STUDIO_ESTIMATE_VIDEO_TRIES_PER_SCENE (padrão 2): takes previstos por cena no pré-orçamento."""
    return _int_env("STUDIO_ESTIMATE_VIDEO_TRIES_PER_SCENE", 2, 1)


def included_adjustments_per_scene() -> int:
    """STUDIO_INCLUDED_ADJUSTMENTS_PER_SCENE (padrão 1): ajustes pedidos pelo cliente já cobertos pelo pré-orçamento."""
    return _int_env("STUDIO_INCLUDED_ADJUSTMENTS_PER_SCENE", 1, 0)


def ops_budget_factor() -> float:
    """STUDIO_OPS_BUDGET_FACTOR (padrão 1.5): orçamento operacional = pré-orçamento × fator (folga interna)."""
    return _float_env("STUDIO_OPS_BUDGET_FACTOR", 1.5, 1.0)


@lru_cache(maxsize=8)
def _load_table(path: str, mtime: float) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ops = data.get("operations") or {}
    missing = [op for op in OPERATIONS if op not in ops]
    if missing:
        raise ValueError(f"tabela de custos sem as operações {missing}")
    for op, row in ops.items():
        usd = row.get("usd")
        if usd is not None and (not isinstance(usd, (int, float)) or usd < 0 or not math.isfinite(usd)):
            raise ValueError(f"custo inválido para {op}")
    return data


def cost_table() -> dict:
    path = Path(os.environ.get("STUDIO_OPERATION_COSTS_FILE") or DEFAULT_COSTS_FILE)
    return _load_table(str(path), path.stat().st_mtime)


def op_cost(settings, op: str, *, n_refs: int = 4) -> float:
    """Custo estimado (US$) de UMA operação. usd null na tabela → tabela de preços do modelo configurado."""
    row = cost_table()["operations"][op]
    if row.get("usd") is not None:
        return float(row["usd"])
    if op == "image":
        return pricing.image_cost(settings.image_model, settings.image_size, n_refs)[0]
    if op == "video":
        return pricing.video_cost(settings.video_model, settings.video_resolution)[0]
    raise ValueError(f"operação {op} sem custo na tabela")


def review_cost(op: str = "review_image") -> float:
    """Reserva por conferência/roteiro (chamadas de texto) — também vem da tabela."""
    ops = cost_table()["operations"]
    # "facts" (ficha técnica visual) é chamada de texto como o roteiro: tabelas antigas sem a linha usam a do roteiro
    usd = (ops.get(op) or (ops.get("plan") if op == "facts" else None) or ops[op]).get("usd")
    return float(usd) if usd is not None else 0.0


# ------------------------------------------------------------------ estimativas
def adjustment_cost_usd(settings, stage: str) -> float:
    """Um ajuste refaz a etapa e tudo que depende dela: imagem → imagem, conferência, take e conferência."""
    video = op_cost(settings, "video") + op_cost(settings, "review_video")
    if stage == "image":
        return op_cost(settings, "image") + op_cost(settings, "review_image") + video
    return video


def estimate_production(settings, n_scenes: int = 3) -> dict:
    """Pré-orçamento do vídeo completo: roteiro + por cena (imagens e takes previstos, cada um com conferência)
    + ajustes incluídos por cena. Devolve o detalhamento em US$ e o total em centésimos de crédito."""
    from .credits import to_cc
    img_t, vid_t, adj = image_tries_per_scene(), video_tries_per_scene(), included_adjustments_per_scene()
    image = op_cost(settings, "image") + op_cost(settings, "review_image")
    video = op_cost(settings, "video") + op_cost(settings, "review_video")
    parts = {
        "plan": op_cost(settings, "plan") + review_cost("facts"),   # roteiro + ficha técnica visual
        "images": n_scenes * img_t * image,
        "videos": n_scenes * vid_t * video,
        "included_adjustments": n_scenes * adj * adjustment_cost_usd(settings, "image"),
    }
    usd = round(sum(parts.values()), 4)
    return {"usd": usd, "cc": to_cc(usd), "parts_usd": {k: round(v, 4) for k, v in parts.items()},
            "scenes": n_scenes, "image_tries_per_scene": img_t, "video_tries_per_scene": vid_t,
            "included_adjustments_per_scene": adj}


def ops_budget_usd(estimate_usd: float, default_usd: float) -> float:
    """Orçamento operacional de uma produção com pré-orçamento: nunca menor que o padrão do servidor nem que
    pré-orçamento × fator. (O teto mensal continua valendo à parte.)"""
    return round(max(default_usd, estimate_usd * ops_budget_factor()), 4)


# ------------------------------------------------------------------ "Seu próximo vídeo"
NO_EXTRA_COST = "Nenhum custo adicional será aplicado sem sua autorização."


def next_video_summary(db, settings, pid: str) -> dict:
    """Resumo mostrado ANTES de gastar: produto, formato, cenas, ajustes incluídos, custo total autorizado (créditos;
    R$ só com STUDIO_CREDIT_PRICE_BRL), saldo e a garantia de que nada além disso é cobrado sem autorização."""
    from . import billing
    from .credits import Ledger, fmt
    p = db.production(pid)
    profile = json.loads(p["profiles_json"])["format"]["data"]
    product = json.loads(p["product_json"])
    led = Ledger(db)
    wid = p["workspace_id"]
    total = p["prebudget_cc"] or 0
    pool = led.pool_state(pid)
    exempt = led.exempt(wid)
    # saldo atual = o que o estúdio tem agora, contando o que já está reservado para este vídeo
    balance = led.balance(wid) + (pool["remaining_cc"] if not pool["closed"] else 0)
    price = billing.credit_price_brl_configured()
    brl = round(total / 100 * price, 2) if price else None
    return {
        "product": product.get("name") or "", "format": profile.get("aspect_ratio") or "9:16",
        "scenes": len(profile.get("scenes") or []) or 3,
        "included_adjustments_per_scene": included_adjustments_per_scene(),
        "total_cc": total, "total_credits": fmt(total),
        "total_brl": (f"{brl:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if brl is not None else None),
        "balance_cc": balance, "balance": fmt(balance), "exempt": exempt,
        "balance_after": fmt(led.balance(wid)),   # o que sobra livre depois de reservar este vídeo
        "no_extra_cost": NO_EXTRA_COST,
    }


# ------------------------------------------------------------------ aviso ao administrador
def notify_admin(db, pid: str, code: str, detail: str) -> None:
    """Registra o alerta (evento `ops_alert`, que `studio admin ops-alerts` lista), loga e, se houver e-mail
    configurado, avisa os administradores da plataforma em segundo plano. Nunca leva segredo nem dado do cliente."""
    db.add_event(pid, "ops_alert", f"{code}: {detail}"[:500], data={"code": code})
    log.warning("[%s] alerta operacional %s: %s", pid, code, detail)
    try:
        emails = [r[0] for r in db.conn.execute("SELECT email FROM users WHERE is_platform_admin=1")]
    except Exception:  # noqa: BLE001 — banco sem contas (CLI antiga)
        emails = []
    if not emails:
        return
    from . import mailer
    if not mailer.configured():
        return
    subject = f"Kiroo: produção {pid} pausada ({code})"
    text = (f"A produção {pid} pausou pelo freio interno ({code}).\n\n{detail}\n\nO cliente vê apenas que estamos "
            "finalizando. Revise e, se for o caso, ajuste com `studio budget {pid} --set <US$>` e "
            f"`studio resume {pid}`.")

    def run() -> None:
        for to in emails:
            mailer.send(to, subject, text)

    threading.Thread(target=run, name="studio-ops-alert", daemon=True).start()
