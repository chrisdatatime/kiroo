"""Portão único das chamadas pagas (Gemini e Anthropic): kill switch, liberação por ambiente e tetos globais.

Ordem das checagens (a primeira que falhar bloqueia; nada é chamado nem cobrado):
1. STUDIO_KILL_SWITCH=1: bloqueia tudo, em qualquer ambiente, sem exceção.
2. STUDIO_ALLOW_PAID_CALLS: padrão 0 em staging/produção (STUDIO_ENV); em dev o padrão deixa a decisão para o
   workspace/CLI, como antes. Valor explícito vale em qualquer ambiente (0 desliga até em dev).
3. STUDIO_MONTHLY_CAP_USD: teto do mês da PLATAFORMA (soma de todos os workspaces + testes de treinamento + chat).
   Em staging/produção é obrigatório (> 0) para haver chamada paga.
4. STUDIO_AGENT_DAILY_CAP_USD: teto do dia por agente em cada workspace (0 = sem teto).
Os tetos por missão (orçamento da produção) e por workspace (teto mensal + créditos) continuam no orquestrador.

Lido a cada chamada (variáveis de ambiente mudam só com reinício, mas os testes trocam no meio).
"""

from __future__ import annotations

import os
from datetime import datetime

from .providers.base import PermanentError

PROTECTED_ENVS = ("staging", "production")
# etapa do orquestrador -> agente que faz a chamada (mesmos ids da conversa com os agentes)
KIND_AGENT = {"image": "iris", "video": "lia", "review_image": "rui", "review_video": "rui", "plan": "theo", "facts": "theo"}

MESSAGES = {
    "kill_switch": "A geração com IA está pausada pela equipe do Kiroo neste momento. Nada foi cobrado: o que você "
                   "já fez continua salvo e pode ser retomado quando liberarmos.",
    "disabled": "A geração com IA real não está liberada neste ambiente. Nada foi cobrado; continue no modo DEMO.",
    "no_platform_cap": "A geração com IA real está desligada até a equipe do Kiroo definir o limite de gastos. Nada foi cobrado.",
    "platform_cap": "O limite de gastos do Kiroo neste mês foi atingido. Nada foi cobrado: a produção fica pausada "
                    "e pode ser retomada quando o limite for renovado.",
    "agent_cap": "Este agente já usou o limite de hoje. Nada foi cobrado: retome amanhã ou fale com a equipe do Kiroo.",
}


class PaidCallsBlocked(PermanentError):
    """Chamada paga recusada antes de sair da máquina. `reason` é uma chave de MESSAGES."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(MESSAGES[reason])


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "sim", "on"}


def _env() -> str:
    raw = (os.environ.get("STUDIO_ENV") or "dev").strip().lower()
    return raw if raw in ("dev", *PROTECTED_ENVS) else "production"   # valor estranho: trata como o mais fechado


def protected() -> bool:
    return _env() in PROTECTED_ENVS


def _float(name: str) -> float:
    try:
        return max(float(os.environ.get(name) or 0), 0.0)
    except ValueError:
        return 0.0


def platform_cap() -> float:
    return _float("STUDIO_MONTHLY_CAP_USD")


def effective_cap(account_cap: float | None) -> float:
    """Teto mensal efetivo de um estúdio: o MENOR entre o teto da conta e o da plataforma.
    Teto da conta <= 0 → 0 (nenhuma chamada paga). Plataforma sem teto (0, só em dev) não limita além da conta."""
    acc = max(float(account_cap or 0), 0.0)
    plat = platform_cap()
    return min(acc, plat) if plat > 0 else acc


def validate_account_cap(usd: float) -> float:
    """Valida o teto de uma conta: número finito entre 0 e o teto da plataforma (nunca acima). Devolve o valor."""
    import math
    if isinstance(usd, bool) or not isinstance(usd, (int, float)) or not math.isfinite(usd):
        raise ValueError("o teto precisa ser um número em US$")
    if usd < 0:
        raise ValueError("o teto não pode ser negativo")
    plat = platform_cap()
    if usd > plat + 1e-9:
        if plat <= 0:
            raise ValueError("a plataforma não tem teto mensal (STUDIO_MONTHLY_CAP_USD=0): defina-o antes de dar teto "
                             "maior que 0 a uma conta")
        raise ValueError(f"o teto da conta (US${usd:.2f}) não pode passar do teto da plataforma (US${plat:.2f})")
    return round(float(usd), 4)


def agent_daily_cap() -> float:
    return _float("STUDIO_AGENT_DAILY_CAP_USD")


def kill_switch() -> bool:
    return _bool(os.environ.get("STUDIO_KILL_SWITCH"))


def blocked_reason() -> str | None:
    """Motivo de bloqueio que não depende de quanto já foi gasto (None = portão aberto)."""
    if kill_switch():
        return "kill_switch"
    raw = os.environ.get("STUDIO_ALLOW_PAID_CALLS")
    allowed = _bool(raw) if (raw or "").strip() else not protected()
    if not allowed:
        return "disabled"
    if protected() and platform_cap() <= 0:
        return "no_platform_cap"
    return None


def check() -> None:
    """Barreira mínima, usada logo antes de cada chamada de rede paga (adaptadores Gemini e Anthropic)."""
    reason = blocked_reason()
    if reason:
        raise PaidCallsBlocked(reason)


def check_spend(db, estimate: float, *, workspace_id: str | None = None, agent: str | None = None) -> None:
    """Portão + teto da plataforma + teto diário do agente, para uma chamada estimada em `estimate` US$."""
    check()
    if estimate <= 0:
        return
    from .spend import agent_day_spend, platform_month_spend

    cap = platform_cap()
    if cap > 0 and platform_month_spend(db) + estimate > cap + 1e-9:
        raise PaidCallsBlocked("platform_cap")
    acap = agent_daily_cap()
    if agent and acap > 0 and agent_day_spend(db, workspace_id, agent) + estimate > acap + 1e-9:
        raise PaidCallsBlocked("agent_cap")


def status() -> dict:
    """Para a interface e o `studio doctor` (sem valores de segredo)."""
    reason = blocked_reason()
    return {"blocked": bool(reason), "reason": reason, "message": MESSAGES.get(reason) if reason else None,
            "environment": _env(), "platform_cap_usd": platform_cap(), "agent_daily_cap_usd": agent_daily_cap(),
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds")}
