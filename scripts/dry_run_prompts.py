"""Imprime os 6 argumentos FINAIS que o workflow da fal.ai receberia, SEM chamar a fal.ai (nenhuma rede, nenhum custo).

Uso:  python scripts/dry_run_prompts.py [--scene home_light] [--platform shopee_video] [--name "Fone X"]
      python scripts/dry_run_prompts.py --all                       # resumo das 12 combinacoes
      python scripts/dry_run_prompts.py --diff video --platform mercado_livre   # original x novo (unificado)
      python scripts/dry_run_prompts.py --diff-html saida.html      # original x novo lado a lado (todos os nos)
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from studio.prompts import production as pp  # noqa: E402

ORIGINAL = ROOT / "profiles" / "fal" / "wf01white_original_prompts.json"
# entrada nova -> no original que ela substitui (scene_prompt alimenta os dois Kontext)
DIFF_MAP = {"video": ("video_prompt", "video"), "narration": ("platform_strategy", "narration"),
            "vision": ("product_context", "vision"), "copy": ("copywriting_prompt", "title_caption"),
            "lifestyle": ("scene_prompt", "lifestyle_image"), "hero": ("scene_prompt", "hero_image")}


def _original() -> dict:
    return json.loads(ORIGINAL.read_text(encoding="utf-8"))["nodes"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", default=pp.DEFAULT_SCENE, choices=sorted(pp.SCENES))
    ap.add_argument("--platform", default=pp.DEFAULT_PLATFORM, choices=sorted(pp.PLATFORMS))
    ap.add_argument("--name", default=None, help="nome do produto (opcional)")
    ap.add_argument("--image-url", default="https://example.invalid/foto.jpg")
    ap.add_argument("--all", action="store_true", help="imprime so um resumo das 12 combinacoes")
    ap.add_argument("--diff", choices=sorted(DIFF_MAP), help="diff unificado original x novo de um no")
    ap.add_argument("--diff-html", metavar="ARQUIVO", help="grava o diff lado a lado (HTML) de todos os nos")
    a = ap.parse_args()
    if a.all:
        for s in pp.SCENES:
            for p in pp.PLATFORMS:
                args = pp.build_fal_arguments(a.image_url, s, p, a.name)
                print(f"{s:13} x {p:14} -> " + ", ".join(f"{k}={len(v)}c" for k, v in args.items()))
        return 0
    args = pp.build_fal_arguments(a.image_url, a.scene, a.platform, a.name)
    if a.diff or a.diff_html:
        orig = _original()
        if a.diff:
            key, node = DIFF_MAP[a.diff]
            sys.stdout.writelines(difflib.unified_diff(orig[node]["text"].splitlines(True), (args[key] + "\n").splitlines(True),
                                                       f"original/{node}", f"novo/{key} ({a.scene}, {a.platform})"))
            return 0
        hd = difflib.HtmlDiff(wrapcolumn=70)
        parts = [f"<h1>Original x novo (PROMPT_VERSION {pp.PROMPT_VERSION}; {a.scene}, {a.platform}, nome={a.name!r})</h1>"]
        for label, (key, node) in DIFF_MAP.items():
            parts.append(f"<h2>{label}: no original {node} ({orig[node]['node_id']}) x entrada nova {key}</h2>")
            parts.append(hd.make_table(orig[node]["text"].splitlines(), args[key].splitlines(), "original", "novo"))
        Path(a.diff_html).write_text("<!doctype html><meta charset='utf-8'><style>body{font-family:sans-serif}"
                                     "table.diff{font-family:monospace;font-size:12px;border-collapse:collapse}"
                                     ".diff_add{background:#cfc}.diff_chg{background:#ffa}.diff_sub{background:#fbb}</style>"
                                     + "\n".join(parts), encoding="utf-8")
        print(f"diff gravado em {a.diff_html}", file=sys.stderr)
        return 0
    print(f"# PROMPT_VERSION {pp.PROMPT_VERSION} | cenario {a.scene} | plataforma {a.platform} | nome {a.name!r}\n")
    for k, v in args.items():
        print(f"===== {k} =====\n{v}\n")
    print("(dry-run: nada foi enviado)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
