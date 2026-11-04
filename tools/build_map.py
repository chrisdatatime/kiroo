"""Gera assets/maps/office.tmj e office.tmx a partir de tools/tiles.yaml + tools/rooms/*.yaml.

Idempotente: a mesma entrada produz exatamente os mesmos arquivos. Nada é desenhado por código;
só são posicionados GIDs do tileset (SPEC-VIS-001).

  python tools/build_map.py [--room edicao]
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from ruamel.yaml import YAML

from tileset_common import ROOT, TILE, gid_of, sheet, where

TOOLS = ROOT / "tools"
MAPS = ROOT / "assets" / "maps"
LAYERS = ["floor", "walls", "furniture_below", "furniture_above"]
yaml = YAML(typ="safe")


class BuildError(Exception):
    pass


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.load(f)


class Grid:
    """Camadas de tiles do mapa inteiro, indexadas por nome."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.data = {name: [0] * (w * h) for name in LAYERS}

    def put(self, layer: str, x: int, y: int, gid: int) -> None:
        if not (0 <= x < self.w and 0 <= y < self.h):
            raise BuildError(f"tile fora do mapa em ({x}, {y})")
        where(gid)  # valida o GID cedo, com erro claro
        self.data[layer][y * self.w + x] = gid


def rect_cells(spec: dict) -> list:
    """Objeto por retângulo do tileset: rect [coluna, linha, w, h]. Tiles totalmente transparentes ficam de fora."""
    key = spec["set"]
    c0, r0, w, h = spec["rect"]
    out = []
    for dy in range(h):
        for dx in range(w):
            x, y = (c0 + dx) * TILE, (r0 + dy) * TILE
            if sheet(key).crop((x, y, x + TILE, y + TILE)).getbbox() is not None:
                out.append([dx, dy, gid_of(key, c0 + dx, r0 + dy)])
    return out


def place(grid: Grid, spec: dict, name: str, ox: int, oy: int, blocked: set, sorted_out: list | None = None) -> None:
    layer = {"below": "furniture_below", "above": "furniture_above"}[spec.get("layer", "below")]
    cells = rect_cells(spec) if "rect" in spec else spec["cells"]
    if spec.get("sort") and sorted_out is not None:
        # móvel em pé: cada célula vira um tile-object; todas compartilham o pé (base do móvel) para o y-sorting
        foot = (oy + max(dy for _, dy, _ in cells) + 1) * TILE
        for dx, dy, gid in cells:
            if not (0 <= ox + dx < grid.w and 0 <= oy + dy < grid.h):
                raise BuildError(f"tile fora do mapa em ({ox + dx}, {oy + dy})")
            where(gid)
            sorted_out.append({"x": ox + dx, "y": oy + dy, "gid": gid, "foot": foot, "name": name})
    else:
        for dx, dy, gid in cells:
            grid.put(layer, ox + dx, oy + dy, gid)
    for dx, dy in spec.get("collision", []):
        blocked.add((ox + dx, oy + dy))


def build_room(grid: Grid, tiles: dict, room: dict, blocked: set, sorted_out: list) -> dict:
    w, h = room["size"]
    ox, oy = room["origin"]
    rows = [r for r in str(room["grid"]).splitlines() if r.strip()]
    if len(rows) != h or any(len(r) != w for r in rows):
        raise BuildError(f"{room['id']}: grid é {len(rows)} linhas x {max(map(len, rows))}, esperado {h}x{w}")

    catalog = {**tiles.get("objects", {}), **tiles.get("office", {})}
    floors = tiles["floors"][room["floor"]]
    walls = tiles["walls"]

    def run_gid(part: str, x: int, y: int) -> int:
        """Fileira horizontal de parede: ponta esquerda, meio ou ponta direita."""
        row = rows[y]
        esq = x > 0 and row[x - 1] in "FB"
        dir_ = x < w - 1 and row[x + 1] in "FB"
        t = walls[part]
        return t["meio"] if esq and dir_ else t["esq"] if dir_ else t["dir"] if esq else t["unico"]

    explicit = walls["explicit"]  # char -> gid (lateral, barra sul, batentes da porta): tabela, sem adivinhar
    wall_chars = "FB" + "".join(explicit)

    def wall_gid(ch: str, x: int, y: int) -> int:
        if ch in explicit:
            return explicit[ch]
        return run_gid("face" if ch == "F" else "base", x, y)

    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            gx, gy = ox + x, oy + y
            if ch not in ".+" + wall_chars:
                raise BuildError(f"{room['id']}: caractere '{ch}' desconhecido no grid")
            grid.put("floor", gx, gy, floors[(gx * 7 + gy * 3) % len(floors)])
            if ch in wall_chars:
                grid.put("walls", gx, gy, wall_gid(ch, x, y))
                blocked.add((gx, gy))

    rug = room.get("rug")
    if rug:
        place(grid, catalog[rug["use"]], rug["use"], ox + rug["at"][0], oy + rug["at"][1], set())

    for item in room.get("objects", []):
        name = item["use"]
        if name not in catalog:
            raise BuildError(f"{room['id']}: objeto '{name}' não existe em tiles.yaml — "
                             f"pare e escolha um tile real, não improvise")
        place(grid, catalog[name], name, ox + item["at"][0], oy + item["at"][1], blocked, sorted_out)

    return {"x": ox, "y": oy, "w": w, "h": h}


def game_objects(room: dict, box: dict) -> list[dict]:
    """Objetos de jogo da sala (Fase 2): room, seat, interact, entry, spawn e spot, em coordenadas do mapa."""
    ox, oy = room["origin"]
    rid = room["id"]

    def cell(at):
        return (ox + at[0], oy + at[1], 1, 1)

    out = [{"type": "room", "name": room["nome"], "rect": (box["x"], box["y"], box["w"], box["h"]),
            "props": [("id", "string", rid), ("nome", "string", room["nome"]),
                      ("agent", "string", room.get("agent") or ""), ("tab", "string", room.get("tab") or "")]}]
    for s in room.get("seats", []):
        kind = s.get("kind", "free")
        if kind not in ("agent", "visitor", "free"):
            raise BuildError(f"{rid}: assento com kind '{kind}' inválido")
        props = [("room", "string", rid), ("face", "string", s.get("face", "down")), ("kind", "string", kind)]
        if kind == "agent":
            props.append(("agent", "string", room.get("agent") or ""))
        props.append(("monitor", "bool", bool(s.get("monitor", False))))
        out.append({"type": "seat", "name": "", "rect": cell(s["at"]), "props": props})
    if "monitor" in room:
        x, y, w, h = room["monitor"]
        out.append({"type": "interact", "name": "monitor", "rect": (ox + x, oy + y, w, h),
                    "props": [("action", "string", "monitor"), ("room", "string", rid)]})
    for key in ("entry", "spawn"):
        if key in room:
            out.append({"type": key, "name": "", "rect": cell(room[key]), "props": [("room", "string", rid)]})
    for sp in room.get("spots", []):
        out.append({"type": "spot", "name": "", "rect": cell(sp), "props": [("room", "string", rid)]})
    return out


def rects(blocked: set) -> list[tuple[int, int, int, int]]:
    """Agrupa tiles bloqueados em retângulos: primeiro faixas horizontais, depois junta linhas iguais."""
    out: list[tuple[int, int, int, int]] = []
    for y in sorted({b[1] for b in blocked}):
        xs = sorted(x for x, yy in blocked if yy == y)
        start = prev = None
        for x in xs + [None]:
            if start is None:
                start = prev = x
                continue
            if x is not None and x == prev + 1:
                prev = x
                continue
            out.append((start, y, prev - start + 1, 1))
            start = prev = x
    merged: list[tuple[int, int, int, int]] = []
    for r in sorted(out):
        for i, m in enumerate(merged):
            if m[0] == r[0] and m[2] == r[2] and m[1] + m[3] == r[1]:
                merged[i] = (m[0], m[1], m[2], m[3] + 1)
                break
        else:
            merged.append(r)
    return merged


def _tiled_props(props: list) -> list:
    return [{"name": n, "type": t, "value": v} for n, t, v in props]


def _tile_layer(grid: Grid, lid: int, name: str) -> dict:
    return {"data": grid.data[name], "height": grid.h, "id": lid, "name": name, "opacity": 1,
            "type": "tilelayer", "visible": True, "width": grid.w, "x": 0, "y": 0}


def _group(lid: int, name: str, objs: list, order: str = "topdown") -> dict:
    return {"draworder": order, "id": lid, "name": name, "objects": objs, "opacity": 1,
            "type": "objectgroup", "visible": True, "x": 0, "y": 0}


def tmj(grid: Grid, tiles: dict, collision: list, objects: list[dict], sorted_tiles: list[dict]) -> str:
    ts = tiles["tilesets"]
    nid = iter(range(1, 10 ** 6))
    col = [{"height": r[3] * 32, "id": next(nid), "name": "", "rotation": 0, "type": "collision",
            "visible": True, "width": r[2] * 32, "x": r[0] * 32, "y": r[1] * 32} for r in collision]
    # tile-objects: no Tiled, (x, y) é o canto INFERIOR esquerdo do tile
    srt = [{"gid": t["gid"], "height": 32, "id": next(nid), "name": t["name"], "rotation": 0, "type": "furniture",
            "visible": True, "width": 32, "x": t["x"] * 32, "y": (t["y"] + 1) * 32,
            "properties": [{"name": "foot", "type": "int", "value": t["foot"]}]} for t in sorted_tiles]
    obj = [{"height": o["rect"][3] * 32, "id": next(nid), "name": o["name"], "rotation": 0, "type": o["type"],
            "visible": True, "width": o["rect"][2] * 32, "x": o["rect"][0] * 32, "y": o["rect"][1] * 32,
            "properties": _tiled_props(o["props"])} for o in objects]
    doc = {
        "compressionlevel": -1, "height": grid.h, "infinite": False,
        # ordem de desenho: chão, parede, móveis atrás, móveis em pé (y-sorting com os personagens), móveis na frente
        "layers": [
            _tile_layer(grid, 1, "floor"), _tile_layer(grid, 2, "walls"), _tile_layer(grid, 3, "furniture_below"),
            _group(7, "furniture_sorted", srt, "index"),
            _tile_layer(grid, 4, "furniture_above"),
            _group(5, "collision", col),
            _group(6, "objects", obj),
        ],
        "nextlayerid": 8, "nextobjectid": next(nid),
        "orientation": "orthogonal", "renderorder": "right-down", "tiledversion": "1.10.2",
        "tileheight": 32, "tilesets": [
            {"columns": t["columns"], "firstgid": t["firstgid"],
             "image": t["source"], "imageheight": t["image_height"], "imagewidth": t["image_width"],
             "margin": 0, "name": t["name"], "spacing": 0, "tilecount": t["tilecount"],
             "tileheight": 32, "tilewidth": 32}
            for t in sorted(ts.values(), key=lambda t: t["firstgid"])],
        "tilewidth": 32, "type": "map", "version": "1.10", "width": grid.w,
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def _xml(v) -> str:
    return str(v).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _tmx_props(o, props: list) -> None:
    o.write('   <properties>\n')
    for n, t, v in props:
        val = str(v).lower() if t == "bool" else _xml(v)
        typ = "" if t == "string" else f' type="{t}"'
        o.write(f'    <property name="{n}"{typ} value="{val}"/>\n')
    o.write('   </properties>\n')


def tmx(grid: Grid, tiles: dict, collision: list, objects: list[dict], sorted_tiles: list[dict]) -> str:
    ts = tiles["tilesets"]
    total = len(collision) + len(sorted_tiles) + len(objects)
    o = io.StringIO()
    o.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    o.write(f'<map version="1.10" tiledversion="1.10.2" orientation="orthogonal" renderorder="right-down" '
            f'width="{grid.w}" height="{grid.h}" tilewidth="32" tileheight="32" infinite="0" '
            f'nextlayerid="8" nextobjectid="{total + 1}">\n')
    for t in sorted(ts.values(), key=lambda t: t["firstgid"]):
        o.write(f' <tileset firstgid="{t["firstgid"]}" name="{t["name"]}" tilewidth="32" tileheight="32" '
                f'tilecount="{t["tilecount"]}" columns="{t["columns"]}">\n')
        o.write(f'  <image source="{t["source"]}" width="{t["image_width"]}" height="{t["image_height"]}"/>\n')
        o.write(' </tileset>\n')

    def layer(lid: int, name: str) -> None:
        o.write(f' <layer id="{lid}" name="{name}" width="{grid.w}" height="{grid.h}">\n  <data encoding="csv">\n')
        d = grid.data[name]
        for y in range(grid.h):
            o.write(",".join(str(v) for v in d[y * grid.w:(y + 1) * grid.w]))
            o.write(",\n" if y < grid.h - 1 else "\n")
        o.write('  </data>\n </layer>\n')

    ids = iter(range(1, total + 1))
    col_ids = [next(ids) for _ in collision]
    srt_ids = [next(ids) for _ in sorted_tiles]
    obj_ids = [next(ids) for _ in objects]
    layer(1, "floor")
    layer(2, "walls")
    layer(3, "furniture_below")
    o.write(' <objectgroup id="7" name="furniture_sorted" draworder="index">\n')
    for i, t in zip(srt_ids, sorted_tiles):
        o.write(f'  <object id="{i}" name="{_xml(t["name"])}" type="furniture" gid="{t["gid"]}" '
                f'x="{t["x"] * 32}" y="{(t["y"] + 1) * 32}" width="32" height="32">\n')
        _tmx_props(o, [("foot", "int", t["foot"])])
        o.write('  </object>\n')
    o.write(' </objectgroup>\n')
    layer(4, "furniture_above")
    o.write(' <objectgroup id="5" name="collision">\n')
    for i, r in zip(col_ids, collision):
        o.write(f'  <object id="{i}" type="collision" x="{r[0] * 32}" y="{r[1] * 32}" '
                f'width="{r[2] * 32}" height="{r[3] * 32}"/>\n')
    o.write(' </objectgroup>\n <objectgroup id="6" name="objects">\n')
    for i, ob in zip(obj_ids, objects):
        x, y, w, h = ob["rect"]
        o.write(f'  <object id="{i}" name="{_xml(ob["name"])}" type="{ob["type"]}" '
                f'x="{x * 32}" y="{y * 32}" width="{w * 32}" height="{h * 32}">\n')
        _tmx_props(o, ob["props"])
        o.write('  </object>\n')
    o.write(' </objectgroup>\n</map>\n')
    return o.getvalue()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--room", action="append", help="só estas salas (padrão: todas de tools/rooms/)")
    a = p.parse_args()

    tiles = load(TOOLS / "tiles.yaml")
    files = sorted((TOOLS / "rooms").glob("*.yaml"))
    if a.room:
        files = [f for f in files if f.stem in a.room]
    if not files:
        raise BuildError("nenhuma sala em tools/rooms/")

    m = tiles["map"]
    grid = Grid(m["width"], m["height"])
    blocked: set = set()
    objects: list[dict] = []
    sorted_tiles: list[dict] = []
    rooms = 0
    for f in files:
        room = load(f)
        box = build_room(grid, tiles, room, blocked, sorted_tiles)
        objects += game_objects(room, box)
        rooms += 1
    if sum(1 for o in objects if o["type"] == "spawn") > 1:
        raise BuildError("mais de uma sala define spawn")

    collision = rects(blocked)
    MAPS.mkdir(parents=True, exist_ok=True)
    (MAPS / "office.tmj").write_text(tmj(grid, tiles, collision, objects, sorted_tiles), encoding="utf-8")
    (MAPS / "office.tmx").write_text(tmx(grid, tiles, collision, objects, sorted_tiles), encoding="utf-8")
    used = sum(1 for n in LAYERS for v in grid.data[n] if v) + len(sorted_tiles)
    print(f"{rooms} sala(s), {used} tiles ({len(sorted_tiles)} em pé), {len(collision)} retângulos de colisão, "
          f"{len(objects)} objetos de jogo")
    print(f"  {MAPS / 'office.tmj'}\n  {MAPS / 'office.tmx'}")


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        raise SystemExit(f"erro: {exc}")
