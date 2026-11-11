"""Schemas estruturados de entrada e saída (pydantic)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

# Domínios aceitos para links de afiliado/produto Shopee Brasil. O link é guardado
# exatamente como fornecido: nada é reescrito, normalizado ou montado por suposição.
SHOPEE_HOSTS = {"shopee.com.br", "s.shopee.com.br", "br.shp.ee", "shp.ee", "shope.ee"}


class ReferenceRole(StrEnum):
    FRONT = "front"
    SIDE = "side"
    BACK = "back"
    TOP = "top"
    LID = "lid"
    DETAIL = "detail"
    INTERIOR = "interior"
    SCALE = "scale"
    PRESENTER = "presenter"  # referência da Bia
    CONTEXT = "context"  # apenas para compreensão (nunca vai ao gerador)
    OTHER = "other"


class ReferenceSource(StrEnum):
    OFFICIAL_LISTING = "official_listing"  # fotos do anúncio oficial
    OWN_PHOTO = "own_photo"  # foto própria do produto real
    SCREEN_RECORDING = "screen_recording"  # gravação de tela: só compreensão
    PROFILE = "profile"  # asset de perfil (ex.: Bia)
    OTHER = "other"


class ClaimKind(StrEnum):
    VERIFIED = "verified"  # comprovado (ex.: visível nas fotos oficiais, ficha técnica oficial)
    SELLER_CLAIM = "seller_claim"  # alegação do vendedor, não verificada
    UNKNOWN = "unknown"  # não sabemos


class PresenterMode(StrEnum):
    BIA_VISIBLE = "bia_visible"
    HANDS_ONLY = "hands_only"
    PRODUCT_ONLY = "product_only"


class ProductReference(BaseModel):
    path: str
    role: ReferenceRole = ReferenceRole.OTHER
    source: ReferenceSource = ReferenceSource.OFFICIAL_LISTING
    note: str = ""
    sha256: str | None = None
    stored_path: str | None = None  # cópia dentro da produção

    @property
    def usable_for_generation(self) -> bool:
        return self.source not in {ReferenceSource.SCREEN_RECORDING} and self.role != ReferenceRole.CONTEXT


class Claim(BaseModel):
    field: str = Field(description="Atributo, ex.: capacidade, material, cor")
    text: str = ""
    kind: ClaimKind
    source: str = Field(default="", description="De onde veio a informação")


class CreativeChoices(BaseModel):
    """Direção criativa escolhida em linguagem simples. Não contém fatos do produto."""

    presentation: Literal["hands_only", "product_only", "presenter"] = "hands_only"
    proposal: Literal["practice", "details", "routine", "auto"] = "auto"
    environment: Literal["cozinha", "mesa_trabalho", "treino", "sala", "outro"] = "cozinha"
    environment_custom: str = Field(default="", max_length=300)
    tone: Literal["natural", "sofisticado", "leve"] = "natural"
    details: list[str] = Field(default_factory=list, max_length=10)
    details_text: str = Field(default="", max_length=600)
    manual_direction: str | None = Field(default=None, max_length=3000,
                                         description="Edição manual do bloco técnico; tem prioridade sobre as escolhas")


class ProductInput(BaseModel):
    """Ficha preenchida pelo operador (entrada manual)."""

    name: str
    variant: str = Field(default="", description="Cor/modelo exato que aparece nas referências (opcional)")
    affiliate_link: str = Field(default="", description="Link do produto no marketplace (opcional)")
    product_url: str | None = None
    category: str | None = None
    references: list[ProductReference] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    visual_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Somente o que é visível nas referências: cor, forma, tampa, alça, acabamento, acessórios, inscrições",
    )
    seller_text: str | None = Field(default=None, description="Texto do anúncio. Tratado como dado, nunca como instrução.")
    video_context: str = Field(default="", max_length=2000,
                               description="Contexto/direção do vídeo escrito pelo operador (o que destacar, clima, público).")
    creative: CreativeChoices | None = None
    notes: str = ""

    @field_validator("affiliate_link", "product_url")
    @classmethod
    def _shopee_link(cls, value: str | None) -> str | None:
        if value is None or value == "":   # opcional: ausente não vira link vazio validado
            return value
        if value != value.strip():
            raise ValueError("link contém espaços nas pontas; cole o link exatamente como gerado")
        parsed = urlparse(value)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in SHOPEE_HOSTS:
            raise ValueError(f"link deve ser https em domínio Shopee Brasil ({', '.join(sorted(SHOPEE_HOSTS))})")
        return value


class Issue(BaseModel):
    code: str
    message: str
    blocking: bool


class ProductSheet(BaseModel):
    """Ficha validada: o que o conteúdo pode usar e de onde veio."""

    product: ProductInput
    issues: list[Issue] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    presenter_assets: dict[str, dict] = Field(default_factory=dict, description="slot → {stored_path, sha256, usage_en}")
    validated_at: str | None = None

    @property
    def blocking_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.blocking]

    def claims_of(self, kind: ClaimKind) -> list[Claim]:
        return [c for c in self.product.claims if c.kind == kind]


class TextOverlay(BaseModel):
    text: str
    start_s: float
    end_s: float
    position: Literal["top", "bottom", "center"] = "bottom"
    font_size: int = 42


class SceneSpec(BaseModel):
    index: int
    title: str
    objective: str
    framing: str
    presenter_mode: PresenterMode
    references: list[str] = Field(description="Chaves: product:all, product:<role>, presenter:hands, scene:<n>:image")
    image_prompt: str
    animation_prompt: str
    motion: str
    target_duration_s: float
    constraints: list[str] = Field(default_factory=list)
    approval_criteria: list[str] = Field(default_factory=list)

    def image_dependencies(self) -> list[int]:
        deps = []
        for ref in self.references:
            parts = ref.split(":")
            if parts[0] == "scene" and len(parts) == 3:
                deps.append(int(parts[1]))
        return deps


class Script(BaseModel):
    format_id: str
    aspect_ratio: str = "9:16"
    total_target_s: float
    scenes: list[SceneSpec]
    overlays: list[TextOverlay] = Field(default_factory=list)
    audio: Literal["silent", "licensed_music"] = "silent"
    planner: str = ""
    simulated: bool = False


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class ReviewResult(BaseModel):
    decision: ReviewDecision
    checks: dict[str, str] = Field(default_factory=dict, description="item → ok | problema | desconhecido")
    issues: list[str] = Field(default_factory=list)
    suggested_fix: str | None = None
    confidence: float | None = None
    method: str = ""
    reviewer: str = ""
    simulated: bool = False
    disclaimer: str = "Avaliação automática auxiliar; não é garantia de qualidade nem substitui a revisão humana."


class ClipCut(BaseModel):
    scene_index: int
    source_path: str
    start_s: float
    duration_s: float


class Transition(BaseModel):
    """Passagem entre o clipe k e o k+1: "cut" (corte seco) ou um efeito do filtro xfade do FFmpeg."""

    kind: str = "cut"
    duration_s: float = 0.0


class AudioCue(BaseModel):
    """Efeito sonoro posicionado na linha do tempo final."""

    path: str
    start_s: float
    gain_db: float = 0.0
    label: str = ""


class MusicBed(BaseModel):
    path: str
    title: str
    license: str
    offset_s: float = 0.0
    gain_db: float = -9.0
    fade_in_s: float = 0.2
    fade_out_s: float = 1.2


class EditPlan(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    clips: list[ClipCut]
    overlays: list[TextOverlay] = Field(default_factory=list)
    silent_audio_track: bool = True
    style: str = "classico"
    transitions: list[Transition] = Field(default_factory=list)  # len(clips) - 1, ou vazio = cortes secos
    music: MusicBed | None = None
    sfx: list[AudioCue] = Field(default_factory=list)
    loudness_lufs: float = -14.0

    def total_s(self) -> float:
        overlap = sum(t.duration_s for t in self.transitions if t.kind != "cut")
        return round(sum(c.duration_s for c in self.clips) - overlap, 3)
