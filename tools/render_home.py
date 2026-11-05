"""Gera as imagens da home (página de quem ainda não entrou) a partir da sede real.

    .venv/Scripts/python tools/render_home.py

Saída em frontend/src/assets/home/ (fora do git: deriva dos tilesets e personagens LimeZu, que têm licença comercial):
  sede.webp      vista aérea da sede inteira (office.tmj + tilesets), com os 6 agentes nas cadeiras
  <agente>.png   um quadro 32x32 de frente de cada agente (retrato na seção "Equipe")
Sem esses arquivos a home continua funcionando, só sem as imagens (ver landing/art.js).
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "assets" / "maps" / "office.tmj"
CHARS = ROOT / "assets" / "characters"
OUT = ROOT / "frontend" / "src" / "assets" / "home"
AGENTS = ["nina", "theo", "iris", "lia", "rui", "beto"]
FLIP_H, FLIP_V, FLIP_D = 0x80000000, 0x40000000, 0x20000000
SCALE, FOOT = 2, 29  # igual ao Phaser (sprites.js: KIROO_SCALE, KIROO_FOOT)


def main() -> None:
    tmj = json.loads(MAP.read_text(encoding="utf-8"))
    T = tmj["tilewidth"]
    W, H = tmj["width"], tmj["height"]
    sets = []
    for ts in tmj["tilesets"]:
        img = Image.open((MAP.parent / ts["image"]).resolve()).convert("RGBA")
        sets.append((ts["firstgid"], ts["columns"], img))
    sets.sort(key=lambda s: s[0])

    def tile(gid: int):
        raw = gid & ~(FLIP_H | FLIP_V | FLIP_D)
        if not raw:
            return None
        first, cols, img = [s for s in sets if s[0] <= raw][-1]
        k = raw - first
        t = img.crop(((k % cols) * T, (k // cols) * T, (k % cols + 1) * T, (k // cols + 1) * T))
        if gid & FLIP_H:
            t = t.transpose(Image.FLIP_LEFT_RIGHT)
        if gid & FLIP_V:
            t = t.transpose(Image.FLIP_TOP_BOTTOM)
        return t

    canvas = Image.new("RGBA", (W * T, H * T), (0, 0, 0, 0))

    def layer(name: str) -> None:
        lay = next(l for l in tmj["layers"] if l["name"] == name)
        for n, gid in enumerate(lay["data"]):
            t = tile(gid)
            if t is not None:
                canvas.alpha_composite(t, ((n % W) * T, (n // W) * T))

    for name in ("floor", "walls", "furniture_below"):
        layer(name)

    # móveis ordenados pelo pé + agentes sentados, como no Phaser (depth = y do pé)
    draw = []
    for o in next(l for l in tmj["layers"] if l["name"] == "furniture_sorted")["objects"]:
        t = tile(o["gid"])
        if t is not None:
            draw.append((o["y"], 0, t, (int(o["x"]), int(o["y"]) - T)))
    seats = [o for o in next(l for l in tmj["layers"] if l["name"] == "objects")["objects"] if o.get("type") == "seat"]
    for o in seats:
        p = {x["name"]: x["value"] for x in o.get("properties", [])}
        a = p.get("agent")
        if p.get("kind") != "agent" or a not in AGENTS or not (CHARS / f"{a}.png").exists():
            continue
        fr = Image.open(CHARS / f"{a}.png").convert("RGBA").crop((0, 0, 32, 32)).resize((64, 64), Image.NEAREST)
        i, j = int(o["x"] // T), int(o["y"] // T)
        tx, ty = (i + 0.5) * T, (j + 1) * T - 4
        draw.append(((j + 1) * T + 1, 1, fr, (int(tx - 32), int(ty - FOOT * SCALE))))
    for _, _, img, pos in sorted(draw, key=lambda d: (d[0], d[1])):
        canvas.alpha_composite(img, pos)
    layer("furniture_above")

    OUT.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT / "sede.webp", lossless=True, method=6)
    for a in AGENTS:
        if (CHARS / f"{a}.png").exists():
            Image.open(CHARS / f"{a}.png").convert("RGBA").crop((0, 0, 32, 32)).save(OUT / f"{a}.png", optimize=True)
    print("ok:", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
