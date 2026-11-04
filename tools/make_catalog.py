"""Catálogo visual dos tilesets (SPEC-VIS-001, Fase 1).

Dois modos:
  --contact                  visão geral: o tileset inteiro reduzido, em fatias lado a lado, para achar as faixas úteis.
  (padrão) [--rows A:B]      blocos ampliados 2x com o GID escrito em cada tile, para escolher tile por tile.

Exemplos:
  python tools/make_catalog.py --contact
  python tools/make_catalog.py --tileset interiors --rows 240:300
"""

from __future__ import annotations

import argparse
import json

from PIL import Image, ImageDraw

from tileset_common import OUT, TILE, TILESETS, checker, font, gid_of, info, sheet

INDEX = OUT / "_index.json"


def contact(key: str, cell: int, strip_rows: int, max_w: int, r0: int = 0, r1: int | None = None) -> list[str]:
    """Fatias verticais do tileset, reduzidas e lado a lado. Cada fatia leva a linha em que começa."""
    i = info(key)
    img = sheet(key)
    r1 = min(r1 or i["rows"], i["rows"])
    head, gap = 16, 10
    sw, sh = i["cols"] * cell, strip_rows * cell
    per_page = max(1, (max_w + gap) // (sw + gap))
    strips = [r for r in range(r0, r1, strip_rows)]
    f = font(12)
    files = []
    for page, start in enumerate([strips[k:k + per_page] for k in range(0, len(strips), per_page)]):
        W = len(start) * sw + (len(start) - 1) * gap
        out = Image.new("RGBA", (W, sh + head), (255, 255, 255, 255))
        d = ImageDraw.Draw(out)
        for n, r0_ in enumerate(start):
            x = n * (sw + gap)
            rows = min(strip_rows, r1 - r0_)
            crop = img.crop((0, r0_ * TILE, i["cols"] * TILE, (r0_ + rows) * TILE))
            small = crop.resize((sw, rows * cell), Image.Resampling.NEAREST)
            bg = checker(sw, rows * cell, size=cell)
            bg.alpha_composite(small)
            out.paste(bg, (x, head))
            d.rectangle([x, 0, x + sw - 1, head - 1], fill=(23, 35, 75))
            d.text((x + 3, 2), f"lin {r0_}-{r0_ + rows - 1}", font=f, fill=(255, 255, 255))
        path = OUT / f"contact_{key}_{start[0]:04d}.png"
        out.convert("RGB").save(path)
        files.append(path.name)
    return files


def catalog(key: str, r0: int, r1: int, zoom: int, block_rows: int, half: bool, cols: tuple | None = None) -> list[dict]:
    """Blocos ampliados com o GID escrito em cada tile."""
    i = info(key)
    r1 = min(r1, i["rows"])
    cell = TILE * zoom
    f = font(max(9, 5 * zoom))
    halves = [cols] if cols else ([(0, i["cols"])] if not half else [(0, i["cols"] // 2), (i["cols"] // 2, i["cols"])])
    blocks = []
    for start in range(r0, r1, block_rows):
        rows = min(block_rows, r1 - start)
        for hn, (c0, c1) in enumerate(halves):
            cols = c1 - c0
            out = Image.new("RGBA", (cols * cell, rows * cell + 18), (255, 255, 255, 255))
            bg = checker(cols * cell, rows * cell, size=zoom * 4)
            out.paste(bg, (0, 18))
            d = ImageDraw.Draw(out)
            d.rectangle([0, 0, out.width - 1, 17], fill=(23, 35, 75))
            label = f"{key}  linhas {start}-{start + rows - 1}  colunas {c0}-{c1 - 1}"
            d.text((4, 3), label, font=font(12), fill=(255, 255, 255))
            for ry in range(rows):
                for cx in range(c0, c1):
                    src = sheet(key).crop(((cx) * TILE, (start + ry) * TILE, (cx + 1) * TILE, (start + ry + 1) * TILE))
                    if src.getbbox() is None:
                        continue  # tile vazio: deixa o xadrez aparecer
                    big = src.resize((cell, cell), Image.Resampling.NEAREST)
                    px, py = (cx - c0) * cell, ry * cell + 18
                    out.alpha_composite(big, (px, py))
                    gid = str(gid_of(key, cx, start + ry))
                    tw = d.textlength(gid, font=f)
                    d.rectangle([px, py, px + tw + 3, py + 11], fill=(0, 0, 0, 190))
                    d.text((px + 2, py + 1), gid, font=f, fill=(255, 255, 90))
            suffix = f"_c{c0}" if cols else ("" if not half else f"_{'esq' if hn == 0 else 'dir'}")
            name = f"catalog_{key}_{start:04d}{suffix}.png"
            out.convert("RGB").save(OUT / name)
            blocks.append({"tileset": key, "linhas": [start, start + rows - 1], "colunas": [c0, c1 - 1],
                           "gids": [gid_of(key, c0, start), gid_of(key, c1 - 1, start + rows - 1)], "arquivo": name})
    return blocks


def write_md(new: list[dict]) -> None:
    old = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.is_file() else []
    seen = {b["arquivo"]: b for b in old}
    for b in new:
        seen[b["arquivo"]] = b
    allb = sorted(seen.values(), key=lambda b: (b["tileset"], b["linhas"][0], b["colunas"][0]))
    INDEX.write_text(json.dumps(allb, indent=1, ensure_ascii=False), encoding="utf-8")
    md = ["# Catálogo dos tilesets", "",
          "Gerado por `tools/make_catalog.py`. Tileset: Modern Interiors by LimeZu.", ""]
    for key in TILESETS:
        i = info(key)
        md += [f"## {key}", "",
               f"`{i['source']}` — {i['cols']} colunas x {i['rows']} linhas = {i['count']} tiles · "
               f"GID {i['firstgid']}..{i['lastgid']} · `gid = {i['firstgid']} + linha*{i['columns']} + coluna`", "",
               "| arquivo | linhas | colunas | GIDs |", "|---|---|---|---|"]
        md += [f"| `{b['arquivo']}` | {b['linhas'][0]}–{b['linhas'][1]} | {b['colunas'][0]}–{b['colunas'][1]} | "
               f"{b['gids'][0]}–{b['gids'][1]} |" for b in allb if b["tileset"] == key] or ["| _(nenhum)_ | | | |"]
        md += [""]
    (OUT / "catalog.md").write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tileset", choices=[*TILESETS, "all"], default="all")
    p.add_argument("--contact", action="store_true", help="visão geral para achar as faixas")
    p.add_argument("--rows", help="faixa de linhas A:B (padrão: todas)")
    p.add_argument("--cols", help="faixa de colunas A:B (padrão: todas)")
    p.add_argument("--zoom", type=int, default=2)
    p.add_argument("--block-rows", type=int, default=20)
    p.add_argument("--cell", type=int, default=12, help="px por tile na visão geral")
    p.add_argument("--strip-rows", type=int, default=64, help="linhas por fatia na visão geral")
    p.add_argument("--max-width", type=int, default=2200)
    a = p.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    keys = list(TILESETS) if a.tileset == "all" else [a.tileset]

    if a.contact:
        lo, hi = 0, None
        if a.rows:
            s, _, e = a.rows.partition(":")
            lo, hi = int(s), int(e) if e else None
        for key in keys:
            files = contact(key, a.cell, a.strip_rows, a.max_width, lo, hi)
            print(f"{key}: {', '.join(files)}")
        return

    blocks = []
    for key in keys:
        r0, r1 = (0, info(key)["rows"])
        if a.rows:
            lo, _, hi = a.rows.partition(":")
            r0, r1 = int(lo), int(hi or info(key)["rows"])
        half = info(key)["cols"] > 40
        cols = None
        if a.cols:
            lo, _, hi = a.cols.partition(":")
            cols = (int(lo), int(hi or info(key)["cols"]))
        blocks += catalog(key, r0, r1, a.zoom, a.block_rows, half, cols)
    write_md(blocks)
    print(f"{len(blocks)} bloco(s) em {OUT}")
    for b in blocks:
        print(f"  {b['arquivo']}  linhas {b['linhas'][0]}-{b['linhas'][1]}  GID {b['gids'][0]}-{b['gids'][1]}")


if __name__ == "__main__":
    main()
