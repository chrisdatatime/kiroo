"""Varre TODAS as camadas de uma imagem salva (`docker save`) sem imprimir segredos.

Uso:  docker save kiroo:local -o kiroo.tar && python scripts/verify_image_layers.py kiroo.tar

Procura em nomes e conteúdos: (i) o nome do ZIP de assets (de assets.lock); (ii) os valores reais de R2_ACCOUNT_ID,
R2_ACCESS_KEY_ID e R2_SECRET_ACCESS_KEY lidos de os.environ; (iii) qualquer *.zip; (iv) caminhos de assets fora do esperado;
(v) segredos em Config.Env. Só imprime True/False e contagens, nunca valores. Saída 0 = limpo.
"""

from __future__ import annotations

import json
import os
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R2_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
# Onde arte/assets podem existir na imagem final (o resto é inesperado).
EXPECTED_PREFIXES = ("app/assets/maps/", "app/frontend/dist/", "app/licenses/", "app/profiles/")


def scan(tar_path: Path, zip_name: str, secrets: dict[str, bytes]) -> dict:
    res = {"zip_name_in_paths": False, "zip_name_in_content": False, "zip_files": 0, "unexpected_asset_paths": 0,
           "secret_in_content": {k: False for k in secrets}, "env_has_r2": False, "layers": 0}
    needle = zip_name.encode()
    with tarfile.open(tar_path) as outer:
        names = set(outer.getnames())
        manifest = json.load(outer.extractfile("manifest.json")) if "manifest.json" in names else []
        for image in manifest:
            cfg = json.load(outer.extractfile(image["Config"]))
            for entry in (cfg.get("config") or {}).get("Env") or []:
                if entry.split("=", 1)[0].upper().startswith("R2_") or entry.split("=", 1)[0] in R2_VARS:
                    res["env_has_r2"] = True
        layer_names = [l for img in manifest for l in img.get("Layers", [])] or [n for n in names if n.endswith(".tar")]
        for layer in layer_names:
            res["layers"] += 1
            with tarfile.open(fileobj=outer.extractfile(layer)) as lt:
                for m in lt:
                    p = m.name.lstrip("./")
                    low = p.lower()
                    if zip_name.lower() in low:
                        res["zip_name_in_paths"] = True
                    if low.endswith(".zip"):
                        res["zip_files"] += 1
                    if m.isfile() and any(s in low for s in ("/characters/", "/tilesets/", "assets/home/", "perfil bia")) \
                            and not p.startswith(EXPECTED_PREFIXES):
                        res["unexpected_asset_paths"] += 1
                    if not m.isfile() or m.size == 0 or m.size > 256 * 1024 * 1024:
                        continue
                    data = lt.extractfile(m).read()
                    if needle in data:
                        res["zip_name_in_content"] = True
                    for k, v in secrets.items():
                        if v and v in data:
                            res["secret_in_content"][k] = True
    return res


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    lock = json.loads((ROOT / "assets.lock").read_text(encoding="utf-8"))
    secrets = {k: os.environ.get(k, "").encode() for k in R2_VARS}
    print("variáveis R2 presentes no ambiente desta varredura:", {k: bool(v) for k, v in secrets.items()})
    res = scan(Path(argv[1]), lock["object"], secrets)
    print(json.dumps(res, indent=2))
    dirty = (res["zip_name_in_paths"] or res["zip_name_in_content"] or res["zip_files"] or res["unexpected_asset_paths"]
             or res["env_has_r2"] or any(res["secret_in_content"].values()))
    print("RESULTADO:", "LIMPO" if not dirty else "ENCONTRADO (ver acima)")
    return 1 if dirty else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
