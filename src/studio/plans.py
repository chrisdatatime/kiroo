"""Plano da conta e as vantagens que ele dá (tela de Planos, Fase 6).

Plano = a ASSINATURA da Stripe que vale agora (`subscriptions`, status active/trialing/past_due): basico, pro ou estudio.
Sem assinatura valendo: free. Cancelou: o plano continua até o fim do período pago (a Stripe só manda
`customer.subscription.deleted` no fim); depois volta para free sozinho. Avulso e bônus de boas-vindas não dão plano.

Vantagens (precisam existir de verdade, não só no texto):
  * fila prioritária (pro, estudio): com produções esperando vaga no motor fal.ai (STUDIO_FAL_MAX_INFLIGHT), saem antes;
    ordem de chegada dentro do mesmo nível; o teto nunca é ultrapassado (`SlotQueue`, usado por fal_pipeline).
  * suporte por WhatsApp (pro, estudio): link wa.me de STUDIO_SUPPORT_WHATSAPP (sem a variável, o botão não aparece).
  * acesso antecipado a novidades (estudio): cenário com `early_access_plan` em `prompts.production.SCENES` só é
    liberado para quem tem o plano (hoje nenhum cenário tem: todos liberados; o servidor recusa com 403 e a tela mostra
    o cadeado).
"""

from __future__ import annotations

import os
import re
import threading
import time

from .db import Database

TIERS = ("free", "basico", "pro", "estudio")
RANK = {t: i for i, t in enumerate(TIERS)}
LABELS = {"free": "Free", "basico": "Básico", "pro": "Pro", "estudio": "Estúdio"}
PRIORITY_TIERS = {"pro", "estudio"}
WHATSAPP_TIERS = {"pro", "estudio"}
EARLY_ACCESS_TIER = "estudio"
LIVE_STATUSES = ("active", "trialing", "past_due")   # past_due: a Stripe ainda tenta cobrar; o plano segue até cancelar


def subscription(db: Database, wid: str | None):
    """Assinatura que vale agora (a mais recente), ou None."""
    if not wid:
        return None
    try:
        return db.conn.execute(
            f"SELECT * FROM subscriptions WHERE workspace_id=? AND status IN ({','.join('?' * len(LIVE_STATUSES))})"
            " ORDER BY updated_at DESC LIMIT 1", (wid, *LIVE_STATUSES)).fetchone()
    except Exception:  # noqa: BLE001 — banco antes da migração 16: ninguém assina
        return None


def plan_of(db: Database, wid: str | None) -> str:
    """Plano da assinatura que vale agora (free se nenhuma)."""
    sub = subscription(db, wid)
    return sub["plan"] if sub is not None and sub["plan"] in RANK else "free"


def has_paid_purchase(db: Database, wid: str | None) -> bool:
    """Alguma compra paga (assinatura ou avulso)."""
    if not wid:
        return False
    try:
        return db.conn.execute("SELECT 1 FROM payments WHERE account_id=? AND status='paid' LIMIT 1", (wid,)).fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def priority(plan: str) -> int:
    """Nível na fila do motor fal.ai: 1 = prioritária (pro/estudio), 0 = normal."""
    return 1 if plan in PRIORITY_TIERS else 0


def at_least(plan: str, tier: str) -> bool:
    return RANK.get(plan, 0) >= RANK.get(tier, 0)


def whatsapp_url() -> str | None:
    """STUDIO_SUPPORT_WHATSAPP: número com DDI (só dígitos contam) ou já um https://wa.me/... Vazio → sem botão."""
    raw = (os.environ.get("STUDIO_SUPPORT_WHATSAPP") or "").strip()
    if not raw:
        return None
    m = re.fullmatch(r"https://wa\.me/(\d{10,15})(\?.*)?", raw)
    digits = m.group(1) if m else re.sub(r"\D", "", raw)
    if not 10 <= len(digits) <= 15:
        return None
    return f"https://wa.me/{digits}"


def support_email() -> str | None:
    raw = (os.environ.get("STUDIO_SUPPORT_CONTACT") or "").strip()
    return raw if "@" in raw and " " not in raw and not raw.lower().startswith("http") else None


def view(db: Database, wid: str | None) -> dict:
    """O que a interface recebe em /api/me e no catálogo: plano, assinatura, se já comprou e o canal de suporte."""
    sub = subscription(db, wid)
    plan = sub["plan"] if sub is not None and sub["plan"] in RANK else "free"
    wa = whatsapp_url() if plan in WHATSAPP_TIERS else None
    return {"plan": plan, "plan_label": LABELS[plan], "has_purchase": has_paid_purchase(db, wid),
            "priority_queue": plan in PRIORITY_TIERS, "early_access": plan == EARLY_ACCESS_TIER,
            "subscription": None if sub is None else {
                "status": sub["status"], "interval": sub["interval"] or "month",
                "cancel_at_period_end": bool(sub["cancel_at_period_end"]), "current_period_end": sub["current_period_end"]},
            "support": {"whatsapp": wa, "email": support_email()}}


# =================================================================== fila prioritária do motor fal.ai
class SlotQueue:
    """Quem entra quando há vaga no motor fal.ai.

    Cada produção que acha o teto cheio (ou gente na frente) se registra aqui e volta a perguntar a cada volta do laço
    (`admit`). A ordem é (nível desc, chegada asc): pro/estudio primeiro, ordem de chegada dentro do nível. Quem parou de
    perguntar (pausou, cancelou, processo caiu) some depois de `ttl` segundos e não trava a fila.

    O teto: `admit` só diz sim se `inflight < cap` E a produção está entre as `cap - inflight` primeiras da fila. Quem
    chama segura `lock` do teste até a tentativa virar `submitted` (fal_pipeline), então duas produções nunca leem o
    mesmo número de vagas livres."""

    def __init__(self, clock=time.monotonic):
        self.lock = threading.RLock()
        self._clock = clock
        self._waiting: dict[str, tuple[int, str, float, float]] = {}   # pid -> (nível, chegada, visto_em, ttl)

    def _expire(self) -> None:
        t = self._clock()
        for pid, (_, _, seen, ttl) in list(self._waiting.items()):
            if t - seen > ttl:
                del self._waiting[pid]

    def order(self) -> list[str]:
        with self.lock:
            self._expire()
            return [p for p, _ in sorted(self._waiting.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0]))]

    def admit(self, pid: str, *, level: int, arrival: str, inflight: int, cap: int, ttl: float = 60.0) -> bool:
        with self.lock:
            self._expire()
            self._waiting[pid] = (int(level), str(arrival or ""), self._clock(), float(ttl))
            free = cap - inflight
            if free <= 0:
                return False
            if pid in self.order()[:free]:
                del self._waiting[pid]
                return True
            return False

    def forget(self, pid: str) -> None:
        with self.lock:
            self._waiting.pop(pid, None)

    def waiting(self) -> int:
        with self.lock:
            self._expire()
            return len(self._waiting)


_QUEUES: dict[str, SlotQueue] = {}
_QLOCK = threading.Lock()


def slot_queue(db_path) -> SlotQueue:
    """Uma fila por banco (um processo serve um banco; nos testes, cada teste tem o seu)."""
    key = str(db_path)
    with _QLOCK:
        q = _QUEUES.get(key)
        if q is None:
            q = _QUEUES[key] = SlotQueue()
        return q
