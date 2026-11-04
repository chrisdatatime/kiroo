"""Gera assets/maps/office.tmj e office.tmx a partir de tools/layout.yaml + tools/tiles.yaml + tools/rooms/*.yaml.

Idempotente: a mesma entrada produz exatamente os mesmos arquivos. Nada é desenhado por código;
só são posicionados GIDs do tileset (SPEC-VIS-001).

  python tools/build_map.py [--room edicao]   # --room filtra células (só depuração)
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from ruamel.yaml import YAML

from PIL import Image

from tileset_common import ATLAS, ATLAS_FIRSTGID, ROOT, TILE, TILESETS, gid_of, info, register_atlas, sheet, where

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


def game_objects(room: dict, box: dict, catalog: dict) -> list[dict]:
    """Objetos de jogo da sala (Fase 2): room, seat, interact, entry, spawn e spot, em coordenadas do mapa."""
    ox, oy = room["origin"]
    rid = room["id"]

    def cell(at):
        return (ox + at[0], oy + at[1], 1, 1)

    out = [{"type": "room", "name": room["nome"], "rect": (box["x"], box["y"], box["w"], box["h"]),
            "props": [("id", "string", rid), ("nome", "string", room["nome"]),
                      ("agent", "string", room.get("agent") or ""), ("tab", "string", room.get("tab") or "")]}]
    def seat_obj(s, at):
        kind = s.get("kind", "free")
        if kind not in ("agent", "visitor", "free", "mine"):
            raise BuildError(f"{rid}: assento com kind '{kind}' inválido")
        srid = s.get("room", rid)  # a cabine "meu" fica dentro do pátio, mas o assento é dela
        props = [("room", "string", srid), ("face", "string", s.get("face", "down")), ("kind", "string", kind)]
        if kind == "agent":
            props.append(("agent", "string", room.get("agent") or ""))
        props.append(("monitor", "bool", bool(s.get("monitor", False))))
        props.append(("back", "int", int(s.get("back", 1))))  # linhas do encosto acima do assento que também são o assento (clique)
        return {"type": "seat", "name": "", "rect": cell(at), "props": props}

    for s in room.get("seats", []):
        out.append(seat_obj(s, s["at"]))
    # assentos dos móveis de sentar (tiles.yaml `seat:`): sofás, namoradeiras, poltronas, puffs.
    # O objeto da sala pode escolher quais lugares usa com `seats: [índices]` (ex.: um lugar fica atrás de outro móvel).
    for item in room.get("objects", []):
        spec = catalog.get(item["use"], {})
        if "seat" not in spec:
            continue
        keep = item.get("seats")
        for n, (dx, dy) in enumerate(spec["seat"]["at"]):
            if keep is not None and n not in keep:
                continue
            out.append(seat_obj(spec["seat"], (item["at"][0] + dx, item["at"][1] + dy)))
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


def gen_grid(w: int, h: int, door: dict | None) -> str:
    """Grade padrão de uma sala nova: parede norte F/B, laterais L/R, barra sul; vão de 2 tiles na parede `side`.
    Sala aberta (sem door) = só chão."""
    if door is None:
        return "\n".join("." * w for _ in range(h))
    # 2b-2: paredes horizontais com face de 2 tiles (F topo+face, B face baixa) no norte E no sul; laterais L/R
    rows = ["F" * w, "B" * w] + ["L" + "." * (w - 2) + "R"] * (h - 4) + ["F" * w, "B" * w]
    side = door["side"]
    at = door.get("at", ((w if side in ("south", "north") else h) - 2) // 2)
    if side in ("south", "north"):
        if at < 1 or at + 2 > w - 1:
            raise BuildError(f"porta {side} fora da parede (at={at}, w={w})")
        for y in ((0, 1) if side == "north" else (h - 2, h - 1)):   # o vão abre as duas fileiras; as pontas viram batentes
            r = list(rows[y])
            r[at] = r[at + 1] = "."
            rows[y] = "".join(r)
    elif side in ("east", "west"):
        col = -1 if side == "east" else 0
        for y in (at, at + 1):
            r = list(rows[y])
            r[col] = "."
            rows[y] = "".join(r)
    else:
        raise BuildError(f"porta com side '{side}' inválido")
    return "\n".join(rows)


def door_entry(w: int, h: int, door: dict) -> list:
    """Casa logo dentro da porta (relativa à sala), onde "Ir à sala" deixa o jogador."""
    side = door["side"]
    at = door.get("at", ((w if side in ("south", "north") else h) - 2) // 2)
    return {"south": [at, h - 3], "north": [at, 2], "east": [w - 2, at], "west": [1, at]}[side]


def cell_room(cell: dict, root: Path) -> dict:
    """Sala de uma célula do layout: do YAML da própria sala (room_file) ou gerada (paredes, porta, chão)."""
    x, y, cw, ch = cell["rect"]
    if "room_file" in cell:
        room = load(root / "rooms" / f"{cell['room_file']}.yaml")
        if room["id"] != cell["id"]:
            raise BuildError(f"{cell['room_file']}.yaml tem id '{room['id']}', esperado '{cell['id']}'")
        w, h = room["size"]
        if w > cw or h > ch:
            raise BuildError(f"{cell['id']}: sala {w}x{h} não cabe na célula {cw}x{ch}")
        room["origin"] = [x, y]
        return room
    door = None if cell.get("open") else cell.get("door")
    if not cell.get("open") and door is None:
        raise BuildError(f"{cell['id']}: célula sem door (ou open: true)")
    room = {"id": cell["id"], "nome": cell["nome"], "agent": cell.get("agent"), "tab": cell.get("tab"),
            "size": [cw, ch], "origin": [x, y], "floor": cell.get("floor", "piso_escritorio"),
            "grid": gen_grid(cw, ch, door), "objects": cell.get("objects", [])}
    if "entry" in cell:
        room["entry"] = cell["entry"]
    elif door:
        room["entry"] = door_entry(cw, ch, door)
    if "spawn" in cell:
        room["spawn"] = cell["spawn"]
    return room


def build_atlas(grid: Grid, sorted_tiles: list[dict], tiles: dict) -> int:
    """Atlas só com os tiles do Interiors usados no mapa (o arquivo inteiro passa do limite de textura do WebGL).

    Os GIDs do Interiors (8589..25612) viram GIDs do atlas (a partir de ATLAS_FIRSTGID), em ordem crescente do GID
    de origem: a mesma entrada gera o mesmo PNG e o mesmo mapa. O tileset `interiors` sai do .tmj/.tmx.
    """
    lo, hi = TILESETS["interiors"]["firstgid"], info("interiors")["lastgid"]
    used = sorted({g for n in LAYERS for g in grid.data[n] if lo <= g <= hi} | {t["gid"] for t in sorted_tiles if lo <= t["gid"] <= hi})
    tiles["tilesets"].pop("interiors", None)
    atlas_path = ATLAS["path"]
    if not used:
        atlas_path.unlink(missing_ok=True)
        register_atlas()
        return 0
    cols = ATLAS["columns"]
    rows = -(-len(used) // cols)
    img = Image.new("RGBA", (cols * TILE, rows * TILE), (0, 0, 0, 0))
    mapping = {}
    src = sheet("interiors")
    for i, g in enumerate(used):
        n = g - lo
        c, r = n % cols, n // cols
        img.paste(src.crop((c * TILE, r * TILE, c * TILE + TILE, r * TILE + TILE)), ((i % cols) * TILE, (i // cols) * TILE))
        mapping[g] = ATLAS_FIRSTGID + i
    atlas_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(atlas_path, optimize=False)
    for n in LAYERS:
        grid.data[n] = [mapping.get(g, g) for g in grid.data[n]]
    for t in sorted_tiles:
        t["gid"] = mapping.get(t["gid"], t["gid"])
    tiles["tilesets"]["interiors_atlas"] = {
        "firstgid": ATLAS_FIRSTGID, "columns": cols, "source": ATLAS["source"], "name": ATLAS["name"],
        "image_width": cols * TILE, "image_height": rows * TILE, "tilecount": cols * rows}
    register_atlas()
    return len(used)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--room", action="append", help="só estas células (padrão: todas de tools/layout.yaml)")
    a = p.parse_args()

    tiles = load(TOOLS / "tiles.yaml")
    layout = load(TOOLS / "layout.yaml")
    cells = [c for c in layout["cells"] if not a.room or c["id"] in a.room]
    if not cells:
        raise BuildError("nenhuma célula em tools/layout.yaml")

    m = layout["map"]
    grid = Grid(m["width"], m["height"])
    blocked: set = set()
    objects: list[dict] = []
    sorted_tiles: list[dict] = []

    # chão contínuo dos corredores
    floor = tiles["floors"][layout.get("corridor_floor", "piso_escritorio")]
    for x, y, w, h in layout["corridors"]:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                grid.put("floor", xx, yy, floor[0])

    for cell in cells:
        room = cell_room(cell, TOOLS)
        box = build_room(grid, tiles, room, blocked, sorted_tiles)
        objects += game_objects(room, box, {**tiles.get("objects", {}), **tiles.get("office", {})})

    for r in layout.get("extra_rooms", []):
        x, y, w, h = r["rect"]
        objects.append({"type": "room", "name": r["nome"], "rect": (x, y, w, h),
                        "props": [("id", "string", r["id"]), ("nome", "string", r["nome"]),
                                  ("agent", "string", ""), ("tab", "string", "")]})
        ex, ey = r["entry"]
        objects.append({"type": "entry", "name": "", "rect": (ex, ey, 1, 1), "props": [("room", "string", r["id"])]})
    for sx, sy in layout.get("spots", []):
        objects.append({"type": "spot", "name": "", "rect": (sx, sy, 1, 1), "props": [("room", "string", "")]})

    # trilha: anel de piso claro nos corredores ao redor do pátio
    t = layout["trail"]
    tx, ty, tw, th = t["rect"]
    hx, hy, hw, hh = t["hole"]
    trail = tiles["floors"][t["tile"]][0]
    n_trail = 0
    for yy in range(ty, ty + th):
        for xx in range(tx, tx + tw):
            if hx <= xx < hx + hw and hy <= yy < hy + hh:
                continue
            if not grid.data["floor"][yy * grid.w + xx]:
                raise BuildError(f"trilha em ({xx}, {yy}) fora do chão")
            grid.put("floor", xx, yy, trail)
            n_trail += 1

    if sum(1 for o in objects if o["type"] == "spawn") != 1:
        raise BuildError("o layout precisa de exatamente um spawn")

    n_atlas = build_atlas(grid, sorted_tiles, tiles)

    collision = rects(blocked)
    MAPS.mkdir(parents=True, exist_ok=True)
    (MAPS / "office.tmj").write_text(tmj(grid, tiles, collision, objects, sorted_tiles), encoding="utf-8")
    (MAPS / "office.tmx").write_text(tmx(grid, tiles, collision, objects, sorted_tiles), encoding="utf-8")
    used = sum(1 for n in LAYERS for v in grid.data[n] if v) + len(sorted_tiles)
    nrooms = sum(1 for o in objects if o["type"] == "room")
    print(f"mapa {grid.w}x{grid.h}: {nrooms} salas, {used} tiles ({len(sorted_tiles)} em pé, {n_trail} de trilha), "
          f"{len(collision)} retângulos de colisão, {len(objects)} objetos de jogo, "
          f"atlas do Interiors com {n_atlas} tiles")
    print(f"  {MAPS / 'office.tmj'}\n  {MAPS / 'office.tmx'}")


if __name__ == "__main__":
    try:
        main()
    except BuildError as exc:
        raise SystemExit(f"erro: {exc}")
