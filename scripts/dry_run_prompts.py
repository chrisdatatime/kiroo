"""Imprime os 6 argumentos que o workflow da fal.ai receberia, SEM chamar a fal.ai (nenhuma rede, nenhum custo).

Uso:  python scripts/dry_run_prompts.py [--scene home_light] [--platform shopee_video] [--name "Fone X"] [--all]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studio.prompts import production as pp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scene", default=pp.DEFAULT_SCENE, choices=sorted(pp.SCENES))
    ap.add_argument("--platform", default=pp.DEFAULT_PLATFORM, choices=sorted(pp.PLATFORMS))
    ap.add_argument("--name", default=None, help="nome do produto (opcional)")
    ap.add_argument("--image-url", default="https://example.invalid/foto.jpg")
    ap.add_argument("--all", action="store_true", help="imprime so um resumo das 12 combinacoes")
    a = ap.parse_args()
    if a.all:
        for s in pp.SCENES:
            for p in pp.PLATFORMS:
                args = pp.build_fal_arguments(a.image_url, s, p, a.name)
                print(f"{s:13} x {p:14} -> " + ", ".join(f"{k}={len(v)}c" for k, v in args.items()))
        return 0
    args = pp.build_fal_arguments(a.image_url, a.scene, a.platform, a.name)
    for k, v in args.items():
        print(f"===== {k} =====\n{v}\n")
    print("(dry-run: nada foi enviado)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
