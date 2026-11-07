"""Regressão: restore.sh dentro da imagem acha a configuração do Litestream (/etc/litestream.yml).

Roda a imagem (padrão kiroo:dados; troque com KIROO_TEST_IMAGE) com `docker run --rm --network none`, sem
credenciais reais. O restore.sh do repositório é montado por cima do da imagem (somente leitura), para testar a
versão atual do script contra o layout da imagem (litestream.yml só em /etc). Pulado sem Docker ou sem a imagem.
"""
import os
import shutil
import subprocess

import pytest

from .backup_common import ROOT

IMAGE = os.environ.get("KIROO_TEST_IMAGE", "kiroo:dados")


def _has_image() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _has_image(), reason=f"docker ou imagem {IMAGE} indisponível")


def _run(env: dict, *args: str):
    cmd = ["docker", "run", "--rm", "--network", "none", "--tmpfs", "/data", "--tmpfs", "/tmp",
           "-v", f"{ROOT / 'scripts' / 'restore.sh'}:/app/scripts/restore.sh:ro"]
    for k in env:
        cmd += ["-e", k]                          # só o nome: valor vem do ambiente deste processo
    cmd += ["--entrypoint", "bash", IMAGE, "/app/scripts/restore.sh", "--dest", "/tmp/r", "--db-only", *args]
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("BACKUP_", "LITESTREAM_", "STUDIO_ENV"))}
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                       env={**clean, **env})
    return p.returncode, p.stdout + p.stderr


def test_sem_credenciais_para_na_checagem_de_variaveis():
    code, out = _run({"STUDIO_ENV": "staging"})
    assert code == 2, out
    assert "variáveis ausentes" in out and "BACKUP_R2_SECRET_ACCESS_KEY" in out
    assert "configuracao do Litestream nao encontrada" not in out


def test_com_variaveis_ficticias_usa_etc_litestream_yml():
    fake = {"STUDIO_ENV": "staging", "BACKUP_R2_PREFIX": "ensaio", "BACKUP_R2_ENDPOINT": "http://127.0.0.1:9",
            "BACKUP_R2_ACCESS_KEY_ID": "ficticio", "BACKUP_R2_SECRET_ACCESS_KEY": "ficticio-nao-e-segredo"}
    code, out = _run(fake)
    # passou da configuração e chegou ao litestream, que falha por falta de rede (código 4 do restore.sh)
    assert code == 4, out
    assert "litestream restore falhou" in out and "ensaio/db" in out
    low = out.lower()
    assert "configuracao do litestream nao encontrada" not in low and "no such file" not in low
    assert "ficticio-nao-e-segredo" not in out


def test_litestream_config_inexistente_falha_com_mensagem_clara():
    code, out = _run({"STUDIO_ENV": "staging", "LITESTREAM_CONFIG": "/nao/existe.yml"})
    assert code == 2 and "LITESTREAM_CONFIG aponta para arquivo inexistente" in out, out
