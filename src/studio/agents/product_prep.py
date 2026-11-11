"""Agente de preparação do produto (determinístico).

Organiza referências, valida a ficha, separa fatos/alegações/desconhecidos e sinaliza
material insuficiente. Não preenche campos por suposição.
"""

from __future__ import annotations

from pathlib import Path

from ..db import now
from ..models import ClaimKind, Issue, ProductInput, ProductSheet, ReferenceRole, ReferenceSource
from ..storage import ProductionStorage, StorageError

# Atributos comerciais que, se não informados, ficam explicitamente como "desconhecidos".
COMMON_ATTRIBUTES = ["capacidade", "material", "dimensões", "vedação", "conservação térmica", "resistência",
                     "certificações", "marca"]


def _resolve(path: str, base_dir: Path) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else (base_dir / p)


def prepare_product(product: ProductInput, storage: ProductionStorage, presenter_profile: dict,
                    presenter_mode: str, assets_dir: Path, base_dir: Path) -> ProductSheet:
    issues: list[Issue] = []
    refs = []
    for ref in product.references:
        src = _resolve(ref.path, base_dir)
        try:
            stored, digest = storage.import_file(src, "inputs/references", prefix=f"{ref.role}_")
        except StorageError as exc:
            issues.append(Issue(code="reference_invalid", message=f"{ref.path}: {exc}", blocking=True))
            continue
        refs.append(ref.model_copy(update={"sha256": digest, "stored_path": storage.relative(stored)}))

    usable = [r for r in refs if r.usable_for_generation and Path(r.stored_path).suffix.lower() in
              {".jpg", ".jpeg", ".png", ".webp"}]
    if not usable:
        issues.append(Issue(code="no_official_images", blocking=True,
                            message="Nenhuma foto oficial/própria utilizável. Gravações de tela servem só para "
                                    "compreensão e não são enviadas ao gerador."))
    else:
        if not any(r.role == ReferenceRole.FRONT for r in usable):
            issues.append(Issue(code="no_front_reference", blocking=False,
                                message="Sem foto marcada como 'front'. Recomendado: frente, lateral e tampa/detalhe."))
        if len(usable) < 2:
            issues.append(Issue(code="few_references", blocking=False,
                                message="Apenas 1 foto utilizável; a fidelidade de forma e proporção tende a cair."))
    if any(r.source == ReferenceSource.SCREEN_RECORDING for r in refs):
        issues.append(Issue(code="screen_recording_context_only", blocking=False,
                            message="Gravação de tela registrada apenas como contexto; interface, notificações e "
                                    "nomes de terceiros não entram nas cenas."))
    if not product.visual_attributes:
        issues.append(Issue(code="visual_attributes_missing", blocking=False,
                            message="Sem atributos visuais descritos; o prompt dependerá apenas das fotos."))

    covered = {c.field.lower() for c in product.claims if c.kind != ClaimKind.UNKNOWN}
    unknown = sorted({c.field for c in product.claims if c.kind == ClaimKind.UNKNOWN}
                     | {a for a in COMMON_ATTRIBUTES if a not in covered})

    presenter_assets: dict[str, dict] = {}
    for asset in presenter_profile.get("assets", []):
        required = presenter_mode in asset.get("required_for", [])
        recommended = presenter_mode in asset.get("recommended_for", [])
        if not (required or recommended):
            continue
        src = assets_dir / asset["file"]
        try:
            stored, digest = storage.import_file(src, "inputs/profile_assets", prefix=f"{asset['slot']}_")
        except StorageError as exc:
            issues.append(Issue(code="presenter_asset_missing", blocking=required,
                                message=f"Referência '{asset['slot']}' da apresentadora indisponível ({exc}). "
                                        f"Coloque o arquivo em {src}."))
            continue
        presenter_assets[asset["slot"]] = {"stored_path": storage.relative(stored), "sha256": digest,
                                           "usage_en": asset.get("usage_en_by_mode", {}).get(
                                               presenter_mode, asset.get("usage_en", ""))}

    validated = product.model_copy(update={"references": refs})
    return ProductSheet(product=validated, issues=issues, unknown_fields=unknown,
                        presenter_assets=presenter_assets, validated_at=now())
