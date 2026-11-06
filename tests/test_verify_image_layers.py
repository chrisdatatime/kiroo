"""scripts/verify_image_layers.py com imagens sintéticas (formato do docker save). Valores fictícios."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_image_layers", ROOT / "scripts" / "verify_image_layers.py")
vil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vil)

ZIP = "kiroo-licensed-assets-2026-11-06.zip"
SECRETS = {"R2_ACCOUNT_ID": b"acct-fake-123", "R2_ACCESS_KEY_ID": b"AKIAFAKEFAKE", "R2_SECRET_ACCESS_KEY": b"fake/secret+KEY"}


def test_imagem_limpa(tmp_path):
    p = vil.synthetic_image(tmp_path / "a.tar", {"app/frontend/dist/index.html": b"<html>", "app/licenses/x.txt": b"licenca"})
    r = vil.scan(p, ZIP, SECRETS)
    assert not vil.is_dirty(r) and r["values_scanned"] and r["files_scanned"] == 2


def test_detecta_zip_segredo_env_e_asset_fora_do_lugar(tmp_path):
    p = vil.synthetic_image(tmp_path / "b.tar", {"tmp/" + ZIP: b"x", "var/log/a.txt": b"... fake/secret+KEY ...",
                                                 "app/assets/characters/nina.png": b"png", "x/outro.zip": b"z"},
                            env=("R2_ACCOUNT_ID=oculto",))
    r = vil.scan(p, ZIP, SECRETS)
    assert r["zip_name_in_paths"] and r["zip_files"] == 2 and r["unexpected_asset_paths"] == 1
    assert r["secret_in_content"] == {"R2_ACCOUNT_ID": False, "R2_ACCESS_KEY_ID": False, "R2_SECRET_ACCESS_KEY": True}
    assert r["env_has_r2"] and vil.is_dirty(r)


def test_relatorio_nao_contem_valores(tmp_path):
    p = vil.synthetic_image(tmp_path / "c.tar", {"a.txt": b"fake/secret+KEY"})
    assert b"fake/secret+KEY" not in json.dumps(vil.scan(p, ZIP, SECRETS)).encode()


def test_selftest_controles_positivo_e_negativo():
    assert vil.selftest() == {"positive_found": True, "negative_not_found": True, "zip_found": True}


def test_entrada_invalida_vira_erro_de_execucao_e_nao_traceback(tmp_path, capsys):
    bad = tmp_path / "x.tar"
    bad.write_bytes(b"nao e tar")
    assert vil.main(["v", str(bad)]) == 3
    assert "erro_execucao" in capsys.readouterr().out
    empty = vil.synthetic_image(tmp_path / "e.tar", {})  # camada sem arquivos
    assert vil.main(["v", str(empty)]) == 3


def test_stdin_vazio_e_nao_verificado(monkeypatch):
    class FakeIn:
        buffer = io.BytesIO(b"")
    monkeypatch.setattr(vil.sys, "stdin", FakeIn())
    assert vil.main(["v", "-"]) == 3


def test_stdin_com_imagem_e_needle_env(tmp_path, monkeypatch, capsys):
    img = vil.synthetic_image(tmp_path / "i.tar", {"app/a.txt": b"zz MARCADOR-FALSO-1 zz"})

    class FakeIn:
        buffer = io.BytesIO(img.read_bytes())

    monkeypatch.setattr(vil.sys, "stdin", FakeIn())
    monkeypatch.setenv("CTRL_POS", "MARCADOR-FALSO-1")
    monkeypatch.setenv("CTRL_NEG", "NAO-EXISTE-XYZ")
    rc = vil.main(["v", "-", "--needle-env", "CTRL_POS", "--needle-env", "CTRL_NEG"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["secret_in_content"]["CTRL_POS"] is True and out["secret_in_content"]["CTRL_NEG"] is False
    assert "MARCADOR-FALSO-1" not in json.dumps(out)
