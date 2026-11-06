"""scripts/verify_image_layers.py com uma 'imagem' sintética (formato do docker save). Valores fictícios."""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_image_layers", ROOT / "scripts" / "verify_image_layers.py")
vil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vil)

ZIP = "kiroo-licensed-assets-2026-11-06.zip"
SECRETS = {"R2_ACCOUNT_ID": b"acct-fake-123", "R2_ACCESS_KEY_ID": b"AKIAFAKEFAKE", "R2_SECRET_ACCESS_KEY": b"fake/secret+KEY"}


def _tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for n, b in files.items():
            i = tarfile.TarInfo(n)
            i.size = len(b)
            t.addfile(i, io.BytesIO(b))
    return buf.getvalue()


def image(path: Path, layer_files: dict[str, bytes], env=("PATH=/usr/bin",)) -> Path:
    layer = _tar(layer_files)
    cfg = json.dumps({"config": {"Env": list(env)}}).encode()
    manifest = json.dumps([{"Config": "cfg.json", "Layers": ["l1/layer.tar"]}]).encode()
    path.write_bytes(_tar({"manifest.json": manifest, "cfg.json": cfg, "l1/layer.tar": layer}))
    return path


def test_imagem_limpa(tmp_path):
    p = image(tmp_path / "a.tar", {"app/frontend/dist/index.html": b"<html>", "app/licenses/x.txt": b"licenca"})
    r = vil.scan(p, ZIP, SECRETS)
    assert not any([r["zip_name_in_paths"], r["zip_name_in_content"], r["zip_files"], r["unexpected_asset_paths"], r["env_has_r2"],
                    *r["secret_in_content"].values()])


def test_detecta_zip_segredo_env_e_asset_fora_do_lugar(tmp_path):
    p = image(tmp_path / "b.tar", {"tmp/" + ZIP: b"x", "var/log/a.txt": b"... fake/secret+KEY ...",
                                   "app/assets/characters/nina.png": b"png", "x/outro.zip": b"z"}, env=("R2_ACCOUNT_ID=oculto",))
    r = vil.scan(p, ZIP, SECRETS)
    assert r["zip_name_in_paths"] and r["zip_files"] == 2 and r["unexpected_asset_paths"] == 1
    assert r["secret_in_content"] == {"R2_ACCOUNT_ID": False, "R2_ACCESS_KEY_ID": False, "R2_SECRET_ACCESS_KEY": True}
    assert r["env_has_r2"]


def test_relatorio_nao_contem_valores(tmp_path):
    p = image(tmp_path / "c.tar", {"a.txt": b"fake/secret+KEY"})
    assert b"fake/secret+KEY" not in json.dumps(vil.scan(p, ZIP, SECRETS)).encode()
