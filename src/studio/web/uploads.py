"""Recebe fotos enviadas pela interface (base64 em JSON) e monta a ficha do produto.

Arquivos são validados (extensão, tamanho, assinatura) e gravados em data/uploads/.
O nome original nunca é usado como caminho. Textos do formulário são dados.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime
from pathlib import Path

from ..models import (Claim, ClaimKind, CreativeChoices, ProductInput, ProductReference, ReferenceRole,
                      ReferenceSource)
from ..storage import IMAGE_EXTS, VIDEO_EXTS, StorageError, validate_media_file

MAX_FILES = 12


class UploadError(ValueError):
    pass


def save_uploads(data_dir: Path, files: list[dict]) -> list[ProductReference]:
    if len(files) > MAX_FILES:
        raise UploadError(f"envie no máximo {MAX_FILES} arquivos por vez")
    if not files:
        return []
    folder = data_dir / "uploads" / f"{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:6]}"
    folder.mkdir(parents=True, exist_ok=True)
    refs = []
    for i, f in enumerate(files, 1):
        ext = Path(str(f.get("name", ""))).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        if ext not in IMAGE_EXTS | VIDEO_EXTS:
            raise UploadError(f"tipo de arquivo não aceito: {f.get('name')!r} (use JPG, PNG, WEBP ou MP4)")
        try:
            role = ReferenceRole(f.get("role") or "other")
            source = ReferenceSource(f.get("source") or "official_listing")
        except ValueError as exc:
            raise UploadError(f"papel/origem inválido: {exc}") from None
        if ext in VIDEO_EXTS:  # vídeos de terceiros/gravações só como contexto
            role, source = ReferenceRole.CONTEXT, ReferenceSource.SCREEN_RECORDING
        try:
            data = base64.b64decode(str(f.get("data", "")).split(",")[-1], validate=True)
        except (binascii.Error, ValueError):
            raise UploadError(f"arquivo corrompido no envio: {f.get('name')!r}") from None
        dest = folder / f"{i:02d}_{role.value}{ext}"
        dest.write_bytes(data)
        try:
            validate_media_file(dest)
        except StorageError as exc:
            dest.unlink(missing_ok=True)  # cópia recém-recebida e inválida, não um original
            raise UploadError(f"{f.get('name')!r}: {exc}") from None
        refs.append(ProductReference(path=str(dest), role=role, source=source,
                                     note=f"enviado pela interface: {str(f.get('name'))[:80]}"))
    return refs


def _lines(text: str | None) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _split(line: str) -> tuple[str, str]:
    if ":" in line:
        k, v = line.split(":", 1)
        return k.strip().lower(), v.strip()
    return "informação", line


def parse_creative(data) -> CreativeChoices:
    if not data:
        return CreativeChoices()
    if not isinstance(data, dict):
        raise UploadError("escolhas criativas inválidas")
    try:
        return CreativeChoices.model_validate(data)
    except ValueError as exc:
        raise UploadError(f"escolha criativa inválida: {exc}") from None


def build_product(payload: dict, refs: list[ProductReference], strict: bool = True) -> ProductInput:
    attrs = dict(_split(ln) for ln in _lines(payload.get("visual_attributes")))
    claims = []
    for ln in _lines(payload.get("verified")):
        field, _ = _split(ln)
        claims.append(Claim(field=field, text=ln, kind=ClaimKind.VERIFIED,
                            source="informado pelo operador como comprovado (interface)"))
    for ln in _lines(payload.get("seller_claims")):
        field, _ = _split(ln)
        claims.append(Claim(field=field, text=ln, kind=ClaimKind.SELLER_CLAIM, source="anúncio do vendedor, não verificado"))
    creative = parse_creative(payload["creative"]) if payload.get("creative") else None
    fields = dict(
        name=str(payload.get("name", "")).strip(),
        variant=str(payload.get("variant", "")).strip(),
        affiliate_link=str(payload.get("affiliate_link", "")).strip(),
        product_url=(str(payload["product_url"]).strip() or None) if payload.get("product_url") else None,
        category=(payload.get("category") or None),
        references=refs,
        claims=claims,
        visual_attributes=attrs,
        seller_text=(payload.get("seller_text") or None),
        video_context=(creative.details_text if creative else str(payload.get("video_context") or ""))[:2000],
        creative=creative,
    )
    if not strict:  # prévia: aceita ficha incompleta, sem validar link
        return ProductInput.model_construct(**{**fields, "seller_text": fields["seller_text"], "notes": ""})
    return ProductInput(**fields)
