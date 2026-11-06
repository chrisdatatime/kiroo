"""Varre TODAS as camadas de uma imagem salva (`docker save`) sem imprimir segredos.

Uso:
  docker save kiroo:local | python scripts/verify_image_layers.py -          # streaming, sem caminho de arquivo
  python scripts/verify_image_layers.py kiroo.tar [--needle-env VAR ...]     # arquivo
  python scripts/verify_image_layers.py --selftest                           # controles de sanidade em imagem sintética

Procura em nomes e conteúdos: o nome do ZIP (de assets.lock), qualquer *.zip, caminhos de assets fora do esperado, Config.Env
com R2_* e os VALORES reais de R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY (e de outras variáveis dadas em --needle-env)
lidos de os.environ. Imprime só JSON com booleanos/contagens, nunca valores.

Códigos de saída: 0 = varredura executada e limpa; 1 = varredura executada e ENCONTROU algo; 3 = a varredura não pôde rodar
(erro de execução/entrada vazia) -> o chamador deve tratar como NAO_VERIFICADO. `values_scanned` diz se algum valor foi procurado.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R2_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
# Onde arte/assets podem existir na imagem final (o resto é inesperado).
EXPECTED_PREFIXES = ("app/assets/maps/", "app/frontend/dist/", "app/licenses/", "app/profiles/")


class ScanError(Exception):
    """A varredura não conseguiu rodar (entrada vazia/inválida)."""


def scan(tar_path: Path, zip_name: str, secrets: dict[str, bytes]) -> dict:
    res = {"zip_name_in_paths": False, "zip_name_in_content": False, "zip_files": 0, "unexpected_asset_paths": 0,
           "secret_in_content": {k: False for k in secrets}, "env_has_r2": False, "layers": 0, "files_scanned": 0,
           "values_scanned": any(secrets.values())}
    needle = zip_name.encode()
    try:
        outer = tarfile.open(tar_path)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ScanError(f"entrada não é um tar válido ({type(exc).__name__})") from None
    with outer:
        names = set(outer.getnames())
        if "manifest.json" not in names:
            raise ScanError("manifest.json ausente: não é uma imagem de `docker save`")
        manifest = json.load(outer.extractfile("manifest.json"))
        for image in manifest:
            cfg = json.load(outer.extractfile(image["Config"]))
            for entry in (cfg.get("config") or {}).get("Env") or []:
                if entry.split("=", 1)[0].upper().startswith("R2_"):
                    res["env_has_r2"] = True
        layer_names = [layer for img in manifest for layer in img.get("Layers", [])]
        if not layer_names:
            raise ScanError("nenhuma camada listada no manifest")
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
                    res["files_scanned"] += 1
                    if needle in data:
                        res["zip_name_in_content"] = True
                    for k, v in secrets.items():
                        if v and v in data:
                            res["secret_in_content"][k] = True
    if res["files_scanned"] == 0:
        raise ScanError("nenhum arquivo lido nas camadas")
    return res


def is_dirty(res: dict) -> bool:
    return bool(res["zip_name_in_paths"] or res["zip_name_in_content"] or res["zip_files"] or res["unexpected_asset_paths"]
                or res["env_has_r2"] or any(res["secret_in_content"].values()))


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for n, b in files.items():
            i = tarfile.TarInfo(n)
            i.size = len(b)
            t.addfile(i, io.BytesIO(b))
    return buf.getvalue()


def synthetic_image(path: Path, layer_files: dict[str, bytes], env=("PATH=/usr/bin",)) -> Path:
    manifest = json.dumps([{"Config": "cfg.json", "Layers": ["l1/layer.tar"]}]).encode()
    cfg = json.dumps({"config": {"Env": list(env)}}).encode()
    path.write_bytes(_tar_bytes({"manifest.json": manifest, "cfg.json": cfg, "l1/layer.tar": _tar_bytes(layer_files)}))
    return path


def selftest() -> dict:
    """Controle positivo/negativo do próprio scanner (valores fictícios, nada vem do ambiente real)."""
    pos, neg = b"CTRL-POS-" + os.urandom(6).hex().encode(), b"CTRL-NEG-" + os.urandom(6).hex().encode()
    d = Path(tempfile.mkdtemp(prefix="kiroo-selftest-"))
    try:
        img = synthetic_image(d / "i.tar", {"app/x.txt": b"abc " + pos + b" def", "tmp/pacote.zip": b"z"})
        r = scan(img, "pacote.zip", {"POS": pos, "NEG": neg})
        return {"positive_found": r["secret_in_content"]["POS"], "negative_not_found": not r["secret_in_content"]["NEG"],
                "zip_found": r["zip_files"] == 1 and r["zip_name_in_paths"]}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(argv: list[str]) -> int:
    try:
        if argv[1:2] == ["--selftest"]:
            r = selftest()
            print(json.dumps(r))
            return 0 if all(r.values()) else 3
        if len(argv) < 2:
            print(__doc__)
            return 3
        extra = [argv[i + 1] for i, a in enumerate(argv) if a == "--needle-env" and i + 1 < len(argv)]
        lock = json.loads((ROOT / "assets.lock").read_text(encoding="utf-8"))
        secrets = {k: os.environ.get(k, "").encode() for k in (*R2_VARS, *extra)}
        src = argv[1]
        tmp = None
        if src == "-":
            tmp = tempfile.NamedTemporaryFile(prefix="kiroo-save-", suffix=".tar", delete=False)
            shutil.copyfileobj(sys.stdin.buffer, tmp, 1 << 20)
            tmp.close()
            if os.path.getsize(tmp.name) == 0:
                os.unlink(tmp.name)
                raise ScanError("entrada vazia (docker save não produziu dados)")
            src = tmp.name
        try:
            res = scan(Path(src), lock["object"], secrets)
        finally:
            if tmp:
                os.unlink(tmp.name)
        res["secrets_present_in_env"] = {k: bool(v) for k, v in secrets.items()}
        print(json.dumps(res))
        return 1 if is_dirty(res) else 0
    except ScanError as exc:
        print(json.dumps({"erro_execucao": str(exc)}))
        return 3
    except Exception as exc:  # noqa: BLE001 - nunca deixar traceback: o chamador classifica como NAO_VERIFICADO
        print(json.dumps({"erro_execucao": type(exc).__name__}))
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
