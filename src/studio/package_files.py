"""Validacao dos arquivos do pacote pelos BYTES reais (nunca pelo nome ou pela extensao devolvida pelo provedor).

Mesmo espirito do `storage.sniff`: tipo, tamanho minimo e, nas imagens, JPG estruturalmente decodificavel
(marcadores SOI/SOF/EOI) com resolucao minima. Sem dependencias externas.
"""

from __future__ import annotations

import struct

from .storage import sniff

MIN_IMAGE_SIDE_PX = 512
MIN_BYTES = {"video": 20_000, "image": 5_000}
MAX_IMAGE_BYTES = 40 * 1024 * 1024
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


class PackageFileError(ValueError):
    pass


def jpeg_info(data: bytes) -> tuple[int, int]:
    """(largura, altura) de um JPG estruturalmente valido. Levanta PackageFileError se truncado ou corrompido."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise PackageFileError("imagem nao e JPG (sem SOI)")
    i, n, size = 2, len(data), None
    saw_sos = False
    while i + 4 <= n:
        if data[i] != 0xFF:
            raise PackageFileError("JPG corrompido (marcador invalido)")
        while i < n and data[i] == 0xFF:        # preenchimento 0xFF
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            break
        if i + 2 > n:
            raise PackageFileError("JPG truncado")
        (seg,) = struct.unpack(">H", data[i:i + 2])
        if seg < 2 or i + seg > n:
            raise PackageFileError("JPG truncado")
        if marker in _SOF and size is None:
            if seg < 8:
                raise PackageFileError("JPG corrompido (SOF)")
            h, w = struct.unpack(">HH", data[i + 3:i + 7])
            size = (w, h)
        if marker == 0xDA:                      # dados da imagem: procura o EOI no fim
            saw_sos = True
            break
        i += seg
    if size is None or not saw_sos:
        raise PackageFileError("JPG sem quadro ou sem dados")
    tail = data.rstrip(b"\x00")
    if tail[-2:] != b"\xff\xd9":
        raise PackageFileError("JPG truncado (sem EOI)")
    return size


def validate(kind: str, data: bytes | None) -> dict:
    """Valida um arquivo de `kind` (video | image). Devolve metadados; levanta PackageFileError."""
    if not data:
        raise PackageFileError(f"{kind}: arquivo vazio")
    if len(data) < MIN_BYTES[kind]:
        raise PackageFileError(f"{kind}: arquivo pequeno demais ({len(data)} bytes)")
    if kind == "image":
        if len(data) > MAX_IMAGE_BYTES:
            raise PackageFileError("image: arquivo grande demais")
        w, h = jpeg_info(data)
        if min(w, h) < MIN_IMAGE_SIDE_PX:
            raise PackageFileError(f"image: resolucao {w}x{h} abaixo do minimo ({MIN_IMAGE_SIDE_PX}px no lado menor)")
        return {"width": w, "height": h}
    if kind == "video":
        if not (sniff(data[:12], ".mp4") or sniff(data[:12], ".webm")):
            raise PackageFileError("video: o conteudo nao e MP4/WEBM")
        return {}
    raise PackageFileError(f"tipo de arquivo desconhecido: {kind}")
