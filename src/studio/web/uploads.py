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
from ..storage import IMAGE_EXTS, VIDEO_EXTS, StorageError, sniff, validate_media_file

MAX_FILES = 12
MB = 1024 * 1024
UPLOAD_MAX_IMAGE_BYTES = 20 * MB    # por arquivo enviado pela interface (abaixo do teto interno de storage.py)
UPLOAD_MAX_VIDEO_BYTES = 100 * MB
MAX_NAME = 200
_BAD_NAME_CHARS = set("/:*?<>|" + chr(92))   # chr(92) = barra invertida


def clean_name(raw) -> str:
    """Nome original só serve para a extensão e para a nota; mesmo assim, nada de caminho nem caractere de controle."""
    if not isinstance(raw, str) or not raw.strip():
        raise UploadError("arquivo sem nome")
    name = raw.strip()
    if len(name) > MAX_NAME:
        raise UploadError("nome de arquivo longo demais")
    if any(ord(c) < 32 or ord(c) == 127 for c in name) or _BAD_NAME_CHARS & set(name) or name.startswith("."):
        raise UploadError(f"nome de arquivo inválido: {name[:60]!r}")
    return name


class UploadError(ValueError):
    pass


def save_uploads(data_dir: Path, files: list[dict]) -> list[ProductReference]:
    if not isinstance(files, list) or not all(isinstance(f, dict) for f in files):
        raise UploadError("lista de arquivos inválida")
    if len(files) > MAX_FILES:
        raise UploadError(f"envie no máximo {MAX_FILES} arquivos por vez")
    if not files:
        return []
    # 1) valida tudo em memória (nome, tamanho, tipo real); 2) só então grava. Nada fica pela metade no disco.
    ready = []
    for i, f in enumerate(files, 1):
        name = clean_name(f.get("name"))
        ext = Path(name).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        if ext not in IMAGE_EXTS | VIDEO_EXTS:
            raise UploadError(f"tipo de arquivo não aceito: {name[:80]!r} (use JPG, PNG, WEBP ou MP4)")
        try:
            role = ReferenceRole(f.get("role") or "other")
            source = ReferenceSource(f.get("source") or "official_listing")
        except ValueError as exc:
            raise UploadError(f"papel/origem inválido: {exc}") from None
        if ext in VIDEO_EXTS:  # vídeos de terceiros/gravações só como contexto
            role, source = ReferenceRole.CONTEXT, ReferenceSource.SCREEN_RECORDING
        encoded = str(f.get("data", "")).split(",")[-1]
        limit = UPLOAD_MAX_VIDEO_BYTES if ext in VIDEO_EXTS else UPLOAD_MAX_IMAGE_BYTES
        if len(encoded) * 3 // 4 > limit + 3:   # antes de decodificar: não aloca o arquivo inteiro à toa
            raise UploadError(f"{name[:80]!r}: arquivo acima de {limit // MB} MB")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise UploadError(f"arquivo corrompido no envio: {name[:80]!r}") from None
        if not data:
            raise UploadError(f"{name[:80]!r}: arquivo vazio")
        if len(data) > limit:
            raise UploadError(f"{name[:80]!r}: arquivo acima de {limit // MB} MB")
        if not sniff(data[:12], ext):   # tipo real pelos bytes, não pelo nome
            raise UploadError(f"{name[:80]!r}: o conteúdo não é um arquivo {ext[1:].upper()} de verdade")
        ready.append((i, name, ext, role, source, data))
    folder = data_dir / "uploads" / f"{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:6]}"
    folder.mkdir(parents=True, exist_ok=True)
    refs = []
    for i, name, ext, role, source, data in ready:
        dest = folder / f"{i:02d}_{role.value}{ext}"   # nome gerado aqui; o original nunca vira caminho
        dest.write_bytes(data)
        try:
            validate_media_file(dest)
        except StorageError as exc:
            for p in folder.iterdir():  # cópias recém-recebidas, nunca originais
                p.unlink(missing_ok=True)
            folder.rmdir()
            raise UploadError(f"{name[:80]!r}: {exc}") from None
        refs.append(ProductReference(path=str(dest), role=role, source=source,
                                     note=f"enviado pela interface: {name[:80]}"))
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
