"""Renderiza assets/maps/office.tmj em tools/out/preview.png, compondo as camadas na ordem certa.

  python tools/preview.py [--grid] [--zoom 2] [--crop x,y,w,h]
"""

from __future__ import annotations

import argparse
import json

from PIL import Image, ImageDraw

from tileset_common import OUT, ROOT, TILE, font, tile_image

MAP = ROOT / "assets" / "maps" / "office.tmj"
ORDER = ["floor", "walls", "furniture_below", "furniture_above"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--grid", action="store_true", help="desenha a grade e os retângulos de colisão")
    p.add_argument("--zoom", type=float, default=2, help="aceita fração (0.5 = metade)")
    p.add_argument("--crop", help="recorte em tiles: x,y,w,h")
    a = p.parse_args()

    doc = json.loads(MAP.read_text(encoding="utf-8"))
    W, H = doc["width"], doc["height"]
    cx, cy, cw, ch = (0, 0, W, H)
    if a.crop:
        cx, cy, cw, ch = (int(v) for v in a.crop.split(","))

    img = Image.new("RGBA", (cw * TILE, ch * TILE), (40, 44, 60, 255))
    # ordem do próprio mapa; furniture_sorted (tile-objects, (x, y) = canto inferior esquerdo) vai ordenado pelo pé
    for layer in doc["layers"]:
        if layer["type"] == "tilelayer" and layer["name"] in ORDER:
            data = layer["data"]
            for y in range(cy, min(cy + ch, H)):
                for x in range(cx, min(cx + cw, W)):
                    gid = data[y * W + x]
                    if gid:
                        img.alpha_composite(tile_image(gid), ((x - cx) * TILE, (y - cy) * TILE))
        elif layer["name"] == "furniture_sorted":
            foot = lambda o: next(p["value"] for p in o["properties"] if p["name"] == "foot")  # noqa: E731
            for o in sorted(layer["objects"], key=lambda o: (foot(o), o["y"])):
                x, y = o["x"] // TILE - cx, o["y"] // TILE - 1 - cy
                if 0 <= x < cw and 0 <= y < ch:
                    img.alpha_composite(tile_image(o["gid"]), (x * TILE, y * TILE))

    if a.zoom != 1:
        mode = Image.Resampling.NEAREST if a.zoom > 1 else Image.Resampling.LANCZOS
        img = img.resize((round(img.width * a.zoom), round(img.height * a.zoom)), mode)

    if a.grid:
        d = ImageDraw.Draw(img)
        step = TILE * a.zoom
        for x in range(0, img.width, step):
            d.line([(x, 0), (x, img.height)], fill=(255, 255, 255, 40))
        for y in range(0, img.height, step):
            d.line([(0, y), (img.width, y)], fill=(255, 255, 255, 40))
        f = font(10)
        for g in (l for l in doc["layers"] if l["type"] == "objectgroup" and l["name"] != "furniture_sorted"):
            color = (255, 90, 90, 255) if g["name"] == "collision" else (120, 255, 140, 255)
            for o in g["objects"]:
                x0 = (o["x"] // TILE - cx) * step
                y0 = (o["y"] // TILE - cy) * step
                d.rectangle([x0, y0, x0 + o["width"] // TILE * step - 1, y0 + o["height"] // TILE * step - 1],
                            outline=color)
                if o.get("name"):
                    d.text((x0 + 3, y0 + 2), o["name"], font=f, fill=color)

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "preview.png"
    img.convert("RGB").save(out)
    print(f"{out}  ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
