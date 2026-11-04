"""Estados explícitos de produção e de cena, com tabela de transições."""

from __future__ import annotations

from enum import StrEnum


class ProductionStatus(StrEnum):
    RECEIVED = "received"
    AWAITING_REFERENCES = "awaiting_references"
    VALIDATED = "validated"
    SCRIPTED = "scripted"
    PRODUCING = "producing"
    EDITING = "editing"
    AWAITING_FINAL_REVIEW = "awaiting_final_review"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SceneStatus(StrEnum):
    PENDING = "pending"
    GENERATING_IMAGE = "generating_image"
    AWAITING_IMAGE_APPROVAL = "awaiting_image_approval"
    IMAGE_APPROVED = "image_approved"
    GENERATING_VIDEO = "generating_video"
    AWAITING_VIDEO_APPROVAL = "awaiting_video_approval"
    VIDEO_APPROVED = "video_approved"
    BLOCKED = "blocked"  # tentativas esgotadas ou falha permanente: precisa de decisão humana


PRODUCTION_LABELS = {
    ProductionStatus.RECEIVED: "Recebido",
    ProductionStatus.AWAITING_REFERENCES: "Aguardando referências",
    ProductionStatus.VALIDATED: "Validado",
    ProductionStatus.SCRIPTED: "Roteirizado",
    ProductionStatus.PRODUCING: "Produzindo cenas",
    ProductionStatus.EDITING: "Editando",
    ProductionStatus.AWAITING_FINAL_REVIEW: "Aguardando revisão final",
    ProductionStatus.COMPLETED: "Concluído",
    ProductionStatus.PAUSED: "Pausado",
    ProductionStatus.FAILED: "Falhou",
    ProductionStatus.CANCELLED: "Cancelado",
}

SCENE_LABELS = {
    SceneStatus.PENDING: "Pendente",
    SceneStatus.GENERATING_IMAGE: "Gerando imagem",
    SceneStatus.AWAITING_IMAGE_APPROVAL: "Aguardando aprovação de imagem",
    SceneStatus.IMAGE_APPROVED: "Imagem aprovada",
    SceneStatus.GENERATING_VIDEO: "Gerando vídeo",
    SceneStatus.AWAITING_VIDEO_APPROVAL: "Aguardando aprovação de vídeo",
    SceneStatus.VIDEO_APPROVED: "Vídeo aprovado",
    SceneStatus.BLOCKED: "Bloqueada (precisa de decisão)",
}

TERMINAL = {ProductionStatus.COMPLETED, ProductionStatus.CANCELLED, ProductionStatus.FAILED}

P = ProductionStatus
_PRODUCTION_TRANSITIONS: dict[ProductionStatus, set[ProductionStatus]] = {
    P.RECEIVED: {P.AWAITING_REFERENCES, P.VALIDATED},
    P.AWAITING_REFERENCES: {P.VALIDATED, P.AWAITING_REFERENCES},
    P.VALIDATED: {P.SCRIPTED, P.AWAITING_REFERENCES},
    P.SCRIPTED: {P.PRODUCING},
    P.PRODUCING: {P.EDITING},
    P.EDITING: {P.AWAITING_FINAL_REVIEW, P.PRODUCING},
    P.AWAITING_FINAL_REVIEW: {P.COMPLETED, P.PRODUCING, P.EDITING},
    P.COMPLETED: {P.EDITING},  # só pela remontagem (trocar estilo/trilha): não gera imagem nem vídeo de novo
    P.PAUSED: set(),  # retomada volta ao estado anterior (resume_status)
    P.FAILED: set(),
    P.CANCELLED: set(),
}
for _status in list(_PRODUCTION_TRANSITIONS):
    if _status not in TERMINAL and _status is not P.PAUSED:
        _PRODUCTION_TRANSITIONS[_status] |= {P.PAUSED, P.FAILED, P.CANCELLED}
        # Atualizar a ficha/referências revalida e reescreve o roteiro a partir de qualquer etapa ativa.
        if _status is not P.RECEIVED:
            _PRODUCTION_TRANSITIONS[_status] |= {P.AWAITING_REFERENCES, P.VALIDATED}
_PRODUCTION_TRANSITIONS[P.PAUSED] = {P.CANCELLED}

S = SceneStatus
_SCENE_TRANSITIONS: dict[SceneStatus, set[SceneStatus]] = {
    S.PENDING: {S.GENERATING_IMAGE},
    S.GENERATING_IMAGE: {S.AWAITING_IMAGE_APPROVAL, S.GENERATING_IMAGE, S.BLOCKED},
    S.AWAITING_IMAGE_APPROVAL: {S.IMAGE_APPROVED, S.GENERATING_IMAGE},
    S.IMAGE_APPROVED: {S.GENERATING_VIDEO},
    S.GENERATING_VIDEO: {S.AWAITING_VIDEO_APPROVAL, S.GENERATING_VIDEO, S.BLOCKED},
    S.AWAITING_VIDEO_APPROVAL: {S.VIDEO_APPROVED, S.GENERATING_VIDEO, S.GENERATING_IMAGE},
    S.VIDEO_APPROVED: {S.GENERATING_VIDEO, S.GENERATING_IMAGE},
    S.BLOCKED: {S.GENERATING_IMAGE, S.GENERATING_VIDEO, S.IMAGE_APPROVED, S.VIDEO_APPROVED},
}
# Invalidação por mudança de dependência pode devolver qualquer cena a PENDING.
for _status in _SCENE_TRANSITIONS:
    _SCENE_TRANSITIONS[_status].add(S.PENDING)


class InvalidTransition(Exception):
    pass


def check_production_transition(current: ProductionStatus, new: ProductionStatus) -> None:
    if new not in _PRODUCTION_TRANSITIONS[current]:
        raise InvalidTransition(f"Produção: transição inválida {current} → {new}")


def check_scene_transition(current: SceneStatus, new: SceneStatus) -> None:
    if new not in _SCENE_TRANSITIONS[current]:
        raise InvalidTransition(f"Cena: transição inválida {current} → {new}")
