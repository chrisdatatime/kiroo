"""Portão único das chamadas pagas (Gemini e Anthropic): kill switch, liberação por ambiente e tetos globais.

Ordem das checagens (a primeira que falhar bloqueia; nada é chamado nem cobrado):
1. STUDIO_KILL_SWITCH=1: bloqueia tudo, em qualquer ambiente, sem exceção.
2. STUDIO_ALLOW_PAID_CALLS: padrão 0 em staging/produção (STUDIO_ENV); em dev o padrão deixa a decisão para o
   workspace/CLI, como antes. Valor explícito vale em qualquer ambiente (0 desliga até em dev).
3. STUDIO_MONTHLY_CAP_USD: teto do mês da PLATAFORMA (soma de todos os workspaces + testes de treinamento + chat).
   Em staging/produção é obrigatório (> 0) para haver chamada paga.
4. STUDIO_AGENT_DAILY_CAP_USD: teto do dia por agente em cada workspace (0 = sem teto).
5. STUDIO_FAL_DAILY_BUDGET_USD / STUDIO_FAL_MONTHLY_BUDGET_USD: teto GLOBAL de gasto com a fal.ai (todas as contas),
   no dia e no mês (padrões 30 e 300; 0 desliga aquele teto). Estourou: produção nova é recusada antes de reservar
   créditos e antes de chamar a fal, com a mensagem de alta demanda; cada recusa vira um `platform_events`.
Os tetos por missão (orçamento da produção) e por workspace (teto mensal + créditos) continuam no orquestrador.

Lido a cada chamada (variáveis de ambiente mudam só com reinício, mas os testes trocam no meio).
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime

from .providers.base import PermanentError

log = logging.getLogger("studio")

PROTECTED_ENVS = ("staging", "production")
FAL_DAILY_DEFAULT_USD = 30.0
FAL_MONTHLY_DEFAULT_USD = 300.0
# etapa do orquestrador -> agente que faz a chamada (mesmos ids da conversa com os agentes)
KIND_AGENT = {"image": "iris", "video": "lia", "review_image": "rui", "review_video": "rui", "plan": "theo", "facts": "theo",
              "workflow": "lia"}

MESSAGES = {
    "kill_switch": "A geração com IA está pausada pela equipe do Kiroo neste momento. Nada foi cobrado: o que você "
                   "já fez continua salvo e pode ser retomado quando liberarmos.",
    "disabled": "A geração com IA real não está liberada neste ambiente. Nada foi cobrado; continue no modo DEMO.",
    "no_platform_cap": "A geração com IA real está desligada até a equipe do Kiroo definir o limite de gastos. Nada foi cobrado.",
    "platform_cap": "O limite de gastos do Kiroo neste mês foi atingido. Nada foi cobrado: a produção fica pausada "
                    "e pode ser retomada quando o limite for renovado.",
    "agent_cap": "Este agente já usou o limite de hoje. Nada foi cobrado: retome amanhã ou fale com a equipe do Kiroo.",
    "fal_budget": "Estamos com alta demanda, tente mais tarde. Nada foi cobrado.",
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


def effective_cap(account_cap: float | None, unlimited: bool = False) -> float:
    """Teto mensal efetivo de um estúdio: o MENOR entre o teto da conta e o da plataforma.
    Teto da conta <= 0 → 0 (nenhuma chamada paga). Plataforma sem teto (0, só em dev) não limita além da conta.
    `unlimited` (workspaces.no_individual_cap = 1): a conta não tem teto próprio e segue só o da plataforma; sem
    teto da plataforma fica 0 (falha fechada: DEMO), nunca "infinito"."""
    plat = platform_cap()
    if unlimited:
        return plat
    acc = max(float(account_cap or 0), 0.0)
    return min(acc, plat) if plat > 0 else acc


def ws_unlimited(ws) -> bool:
    """A conta está sem teto individual (coluna da migração 14; bancos antigos: nunca)."""
    return bool(ws is not None and "no_individual_cap" in ws.keys() and ws["no_individual_cap"])


def ws_cap(ws, fallback: float = 0.0) -> float:
    """Teto efetivo a partir da linha do workspace; sem workspace (CLI antiga) usa `fallback` como teto da conta."""
    if ws is None:
        return effective_cap(fallback)
    return effective_cap(ws["monthly_cap_usd"], ws_unlimited(ws))


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


def _budget(name: str, default: float) -> float:
    """Teto global da fal.ai: ausente ou inválido → padrão; 0 desliga aquele teto (escolha explícita do operador)."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return v if math.isfinite(v) and v >= 0 else default


def fal_daily_budget() -> float:
    return _budget("STUDIO_FAL_DAILY_BUDGET_USD", FAL_DAILY_DEFAULT_USD)


def fal_monthly_budget() -> float:
    return _budget("STUDIO_FAL_MONTHLY_BUDGET_USD", FAL_MONTHLY_DEFAULT_USD)


def fal_budget_block(db, estimate: float) -> dict | None:
    """Teto global da fal.ai (soma de todas as contas). None = cabe; senão {window, spent_usd, cap_usd, estimate_usd}."""
    from .spend import fal_day_spend, fal_month_spend

    est = max(float(estimate or 0), 0.0)
    for window, cap, spent in (("daily", fal_daily_budget(), fal_day_spend),
                               ("monthly", fal_monthly_budget(), fal_month_spend)):
        if cap <= 0:
            continue
        used = spent(db)
        if used + est > cap + 1e-9:
            return {"window": window, "spent_usd": round(used, 4), "cap_usd": cap, "estimate_usd": round(est, 4)}
    return None


def record_platform_event(db, type_: str, data: dict) -> None:
    """Evento estruturado da plataforma (sem produção): tabela `platform_events` + linha de log em JSON.
    Nunca derruba quem chamou."""
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    log.warning("platform_event %s %s", type_, payload)
    try:
        db.conn.execute("INSERT INTO platform_events(type, data_json, created_at) VALUES (?,?,?)",
                        (type_, payload, datetime.now().astimezone().isoformat(timespec="seconds")))
    except Exception:  # noqa: BLE001 — banco sem a migração 14: fica só o log
        pass


def fal_budget_metrics(db) -> dict:
    """Para o painel admin (aba Métricas) e `studio admin metrics`: gasto da fal.ai contra o teto global e recusas."""
    from .spend import fal_day_spend, fal_month_spend

    today = datetime.now().astimezone()
    day, month = today.strftime("%Y-%m-%d"), today.strftime("%Y-%m")
    refused_day = refused_month = 0
    last = None
    try:
        rows = db.conn.execute("SELECT created_at FROM platform_events WHERE type='fal_budget_refused' AND "
                               "substr(created_at, 1, 7)=? ORDER BY id", (month,)).fetchall()
        refused_month = len(rows)
        refused_day = sum(1 for r in rows if r[0][:10] == day)
        last = rows[-1][0] if rows else None
    except Exception:  # noqa: BLE001 — banco sem a migração 14
        pass
    d_cap, m_cap = fal_daily_budget(), fal_monthly_budget()
    d_used, m_used = fal_day_spend(db), fal_month_spend(db)
    return {"daily_cap_usd": d_cap, "monthly_cap_usd": m_cap, "spent_today_usd": round(d_used, 4),
            "spent_month_usd": round(m_used, 4), "daily_reached": d_cap > 0 and d_used >= d_cap - 1e-9,
            "monthly_reached": m_cap > 0 and m_used >= m_cap - 1e-9, "refused_today": refused_day,
            "refused_month": refused_month, "last_refused_at": last}


def check_fal_budget(db, estimate: float, *, where: str, workspace_id: str | None = None,
                     production_id: str | None = None) -> None:
    """Recusa ANTES de chamar a fal.ai (e antes de reservar créditos) quando o teto global estourou.
    Registra `fal_budget_refused` (painel admin, aba Métricas)."""
    block = fal_budget_block(db, estimate)
    if block is None:
        return
    record_platform_event(db, "fal_budget_refused", {**block, "where": where, "workspace_id": workspace_id,
                                                      "production_id": production_id})
    raise PaidCallsBlocked("fal_budget")


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


def check_spend(db, estimate: float, *, workspace_id: str | None = None, agent: str | None = None,
                fal: bool = False, production_id: str | None = None, where: str = "call") -> None:
    """Portão + teto da plataforma + teto diário do agente (+ teto global da fal.ai quando `fal`), para uma chamada
    estimada em `estimate` US$."""
    check()
    if estimate <= 0:
        return
    if fal:
        check_fal_budget(db, estimate, where=where, workspace_id=workspace_id, production_id=production_id)
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
            "fal_daily_budget_usd": fal_daily_budget(), "fal_monthly_budget_usd": fal_monthly_budget(),
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds")}
