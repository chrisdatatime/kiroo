"""Arquivos organizados por produção, com validação de caminhos e hashes.

Originais do operador nunca são movidos ou apagados: são copiados para a produção.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024

_MAGIC = {
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".webp": [b"RIFF"],
}
# Contêiner ISO (MP4/MOV/M4V): a 1ª caixa fica nos bytes 4..8. WebM: cabeçalho EBML.
_ISO_BOXES = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}


def sniff(head: bytes, ext: str) -> bool:
    """O conteúdo bate com a extensão? (tipo real pelos primeiros 12 bytes, não pelo nome)"""
    ext = ext.lower()
    if ext in _MAGIC:
        if not any(head.startswith(m) for m in _MAGIC[ext]):
            return False
        return ext != ".webp" or head[8:12] == b"WEBP"
    if ext in {".mp4", ".mov", ".m4v"}:
        return head[4:8] in _ISO_BOXES
    if ext == ".webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    return False


class StorageError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_media_file(path: Path) -> str:
    """Retorna 'image' ou 'video'; levanta StorageError se o arquivo for inválido."""
    if not path.is_file():
        raise StorageError(f"arquivo não encontrado: {path}")
    ext = path.suffix.lower()
    size = path.stat().st_size
    if ext in IMAGE_EXTS:
        if size > MAX_IMAGE_BYTES:
            raise StorageError(f"imagem grande demais ({size} bytes): {path.name}")
        with open(path, "rb") as f:
            head = f.read(12)
        if not sniff(head, ext):
            raise StorageError(f"conteúdo não corresponde à extensão {ext}: {path.name}")
        return "image"
    if ext in VIDEO_EXTS:
        if size > MAX_VIDEO_BYTES:
            raise StorageError(f"vídeo grande demais ({size} bytes): {path.name}")
        with open(path, "rb") as f:
            head = f.read(12)
        if not sniff(head, ext):
            raise StorageError(f"conteúdo não corresponde à extensão {ext}: {path.name}")
        return "video"
    raise StorageError(f"extensão não suportada: {path.name}")


class ProductionStorage:
    def __init__(self, data_dir: Path, production_id: str):
        if not production_id.replace("_", "").isalnum():
            raise StorageError("id de produção inválido")
        self.root = (data_dir / "productions" / production_id).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, *parts: str) -> Path:
        """Junta partes garantindo que o resultado fique dentro da produção."""
        candidate = self.root.joinpath(*parts).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise StorageError(f"caminho fora da produção: {'/'.join(parts)}")
        return candidate

    def dir(self, *parts: str) -> Path:
        d = self.path(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def import_file(self, src: Path, subdir: str, prefix: str = "") -> tuple[Path, str]:
        """Copia um arquivo externo validado para a produção. Nome = prefixo + hash curto."""
        validate_media_file(src)
        digest = sha256_file(src)
        dest = self.dir(subdir) / f"{prefix}{digest[:12]}{src.suffix.lower()}"
        if not dest.exists():
            shutil.copy2(src, dest)
        return dest, digest

    def write_json(self, rel: str, data) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def write_text(self, rel: str, text: str) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def write_bytes(self, rel: str, data: bytes) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
