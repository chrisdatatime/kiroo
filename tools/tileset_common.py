"""Base das ferramentas de mapa (SPEC-VIS-001): tilesets, GIDs e recorte de tiles.

Tileset: Modern Interiors by LimeZu — https://limezu.itch.io/moderninteriors (licença comercial; crédito obrigatório).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "out"
TILE = 32

# firstgid tem de bater com assets/maps/office.tmx (tilesets embutidos).
TILESETS = {
    "room_builder": {"path": ROOT / "assets/tilesets/Room_Builder_32x32.png", "columns": 76, "firstgid": 1,
                     "source": "../tilesets/Room_Builder_32x32.png", "name": "Room_Builder_32x32"},
    "interiors": {"path": ROOT / "assets/tilesets/Interiors_32x32.png", "columns": 16, "firstgid": 8589,
                  "source": "../tilesets/Interiors_32x32.png", "name": "Interiors_32x32"},
    # interiors termina no GID 25612; os dois seguintes são contíguos.
    "modern_office": {"path": ROOT / "assets/tilesets/Modern_Office_32x32.png", "columns": 16, "firstgid": 25613,
                      "source": "../tilesets/Modern_Office_32x32.png", "name": "Modern_Office_32x32"},
    "room_builder_office": {"path": ROOT / "assets/tilesets/Room_Builder_Office_32x32.png", "columns": 16,
                            "firstgid": 26461, "source": "../tilesets/Room_Builder_Office_32x32.png",
                            "name": "Room_Builder_Office_32x32"},
}
ATLAS_FIRSTGID = 26685

ATLAS = {"path": ROOT / "assets/tilesets/interiors_atlas.png", "columns": 16, "firstgid": ATLAS_FIRSTGID,
         "source": "../tilesets/interiors_atlas.png", "name": "interiors_atlas"}
# Atlas só com os tiles do Interiors usados no mapa (gerado por build_map.py; fora do git, como os demais).
# Entra em TILESETS só quando o arquivo existe (register_atlas), depois do room_builder_office (termina em 26684).

_cache: dict[str, Image.Image] = {}


def register_atlas() -> None:
    _cache.pop("interiors_atlas", None)
    if ATLAS["path"].is_file():
        TILESETS["interiors_atlas"] = ATLAS
    else:
        TILESETS.pop("interiors_atlas", None)


register_atlas()


def sheet(key: str) -> Image.Image:
    if key not in _cache:
        _cache[key] = Image.open(TILESETS[key]["path"]).convert("RGBA")
    return _cache[key]


def rows_of(key: str) -> int:
    return sheet(key).height // TILE


def info(key: str) -> dict:
    ts = TILESETS[key]
    img = sheet(key)
    cols, rows = img.width // TILE, img.height // TILE
    return {**ts, "key": key, "cols": cols, "rows": rows, "count": cols * rows,
            "lastgid": ts["firstgid"] + cols * rows - 1}


def gid_of(key: str, col: int, row: int) -> int:
    ts = TILESETS[key]
    return ts["firstgid"] + row * ts["columns"] + col


def where(gid: int) -> tuple[str, int, int]:
    """GID -> (tileset, coluna, linha). Erro claro quando o GID não existe."""
    for key in TILESETS:
        i = info(key)
        if i["firstgid"] <= gid <= i["lastgid"]:
            n = gid - i["firstgid"]
            return key, n % i["columns"], n // i["columns"]
    raise ValueError(f"GID {gid} fora dos tilesets conhecidos")


def tile_image(gid: int) -> Image.Image:
    key, col, row = where(gid)
    return sheet(key).crop((col * TILE, row * TILE, col * TILE + TILE, row * TILE + TILE))


def checker(w: int, h: int, a=(228, 228, 232), b=(244, 244, 248), size=8) -> Image.Image:
    """Fundo xadrez: deixa visível o que é transparente no tile."""
    img = Image.new("RGBA", (w, h), a)
    px = img.load()
    for y in range(h):
        for x in range(w):
            if ((x // size) + (y // size)) % 2:
                px[x, y] = (*b, 255)
    return img


def font(size: int):
    from PIL import ImageFont
    for name in ("consola.ttf", "arial.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()
