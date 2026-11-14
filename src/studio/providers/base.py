"""Interfaces independentes de provedor.

Geração segue o padrão submit → poll para suportar operações assíncronas e retomada:
o identificador remoto é persistido logo após o envio, e um reinício volta a consultar
a mesma operação em vez de gerar (e pagar) de novo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..models import ReviewResult, SceneSpec, Script


class TransientError(Exception):
    """Falha temporária (rede, 429, 5xx): pode ser repetida com espera progressiva."""


class PermanentError(Exception):
    """Falha definitiva (entrada inválida, bloqueio de segurança, 4xx): não repetir igual."""


class ProviderBillingError(PermanentError):
    """A conta do provedor ficou sem saldo/cobrança (ex.: HTTP 402). O pedido em si está certo:
    não gasta tentativa da cena; a produção pausa até o operador recarregar a conta e retomar."""


class OpState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class OpResult:
    state: OpState
    data: bytes | None = None
    mime_type: str | None = None
    error: str | None = None
    permanent: bool = False
    confirmed_cost_usd: float | None = None
    usage: dict = field(default_factory=dict)
    package: object | None = None   # motor fal.ai: WorkflowPackage canonico (fal_contract); o Gemini nao usa


@dataclass
class ImageRequest:
    prompt: str
    reference_images: list[Path]
    aspect_ratio: str
    image_size: str


@dataclass
class VideoRequest:
    prompt: str
    start_image: Path
    aspect_ratio: str
    resolution: str
    target_duration_s: float


@dataclass
class WorkflowRequest:
    """Um pedido ao workflow da fal.ai: a foto do produto e o estilo (dark | light). O workflow e escolhido pelo estilo."""

    style: str
    image_path: Path


class Generator(Protocol):
    provider: str
    model: str
    simulated: bool

    def submit(self, request) -> str: ...
    def poll(self, op_id: str) -> OpResult: ...


class ImageGenerator(Generator, Protocol):
    def estimate_cost(self, request: ImageRequest) -> tuple[float, str]: ...
    def params(self, request: ImageRequest) -> dict: ...


class WorkflowGenerator(Generator, Protocol):
    def estimate_cost(self, request: WorkflowRequest) -> tuple[float, str]: ...
    def params(self, request: WorkflowRequest) -> dict: ...
    def cancel(self, op_id: str) -> None: ...


class VideoGenerator(Generator, Protocol):
    def estimate_cost(self, request: VideoRequest) -> tuple[float, str]: ...
    def params(self, request: VideoRequest) -> dict: ...


@dataclass
class PlanningContext:
    draft: Script
    product_sheet_json: str
    art_direction: dict
    presenter_mode: str
    training: str = ""
    facts: str = ""   # ficha técnica visual (bloco em inglês) que o planner deve respeitar


@dataclass
class FactsRequest:
    """Pedido da ficha técnica: nome/variante (dados) e as fotos oficiais utilizáveis."""

    name: str
    variant: str
    references: list[Path]
    visual_attributes: dict = field(default_factory=dict)


class Planner(Protocol):
    """Interpretação e planejamento (roteiro). Saída sempre validada por código."""

    provider: str
    model: str
    simulated: bool

    def refine_script(self, ctx: PlanningContext) -> tuple[Script, dict]: ...

    # Opcional (o orquestrador verifica com getattr): ficha técnica visual a partir das fotos.
    # def describe_product(self, req: FactsRequest) -> tuple[dict, dict]: ...


class Reviewer(Protocol):
    provider: str
    model: str
    simulated: bool

    def review_image(self, spec: SceneSpec, image: Path, references: list[Path]) -> tuple[ReviewResult, dict]: ...

    def review_video(self, spec: SceneSpec, frames: list[tuple[float, Path]], approved_image: Path,
                     audio: dict, probe: dict) -> tuple[ReviewResult, dict]: ...


class Publisher(Protocol):
    """Ponto de extensão para publicação futura. Não implementado no MVP."""

    def publish(self, delivery_dir: Path) -> str: ...
