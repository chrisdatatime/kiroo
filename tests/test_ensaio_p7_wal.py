"""Sonda do passo 7 do ensaio (scripts/ensaio_p7_wal.py), rodada no host contra um banco WAL de verdade.

Confere: tamanhos do banco/-wal, page_size por PRAGMA (immutable) e pelo cabecalho, a escolha do ultimo indice do
WAL-sombra do Litestream e que a sonda nao escreve nada (o -wal continua com o mesmo tamanho e conteudo).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SONDA = Path(__file__).resolve().parents[1] / "scripts" / "ensaio_p7_wal.py"
GEN = "0123456789abcdef"


def rodar(dados: Path) -> dict:
    r = subprocess.run([sys.executable, "-I", str(SONDA), str(dados)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def banco_wal(dados: Path, page_size: int = 4096, linhas: int = 200) -> sqlite3.Connection:
    """Banco em WAL com escritas ainda no -wal (conexao aberta, autocheckpoint desligado)."""
    dados.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(dados / "studio.sqlite3", isolation_level=None)
    con.execute(f"PRAGMA page_size={page_size}")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE t (x TEXT)")
    for i in range(linhas):
        con.execute("INSERT INTO t VALUES (?)", ("x" * 500 + str(i),))
    return con


def test_sonda_le_tamanhos_page_size_e_sombra_sem_escrever(tmp_path):
    dados = tmp_path / "data"
    con = banco_wal(dados)
    try:
        wal = dados / "studio.sqlite3-wal"
        antes = wal.read_bytes()
        assert len(antes) > 32
        sombra = dados / ".studio.sqlite3-litestream"
        (sombra / "generations" / GEN / "wal").mkdir(parents=True)
        (sombra / "generation").write_text(GEN + "\n", encoding="ascii")
        for nome, tam in [("00000009.wal", 999), ("0000000a.wal", 4152), ("00000002.wal", 7), ("lixo.wal", 1)]:
            (sombra / "generations" / GEN / "wal" / nome).write_bytes(b"\0" * tam)

        out = rodar(dados)

        assert out["page_size"] == 4096 and out["page_size_cabecalho"] == 4096
        assert out["db_bytes"] == (dados / "studio.sqlite3").stat().st_size
        assert out["wal_arquivo_bytes"] == len(antes)
        assert (out["wal_arquivo_bytes"] - 32) % (4096 + 24) == 0          # quadros inteiros: a formula do limite vale
        # indice em HEXADECIMAL: 0000000a vem depois de 00000009; "lixo.wal" nao conta
        assert out["geracao"] == GEN and out["sombra_indice"] == "0000000a" and out["sombra_bytes"] == 4152
        assert out["sombra_arquivos"] == 3
        assert wal.read_bytes() == antes                                   # nada escrito no -wal
    finally:
        con.close()


def test_sonda_page_size_8192_e_sem_sombra(tmp_path):
    dados = tmp_path / "data"
    con = banco_wal(dados, page_size=8192, linhas=20)
    try:
        out = rodar(dados)
        assert out["page_size"] == 8192 and out["page_size_cabecalho"] == 8192
        assert (out["wal_arquivo_bytes"] - 32) % (8192 + 24) == 0
        assert out["geracao"] is None and out["sombra_bytes"] is None and out["sombra_arquivos"] == 0
    finally:
        con.close()


def test_sonda_volume_sem_banco_nem_wal(tmp_path):
    out = rodar(tmp_path)
    assert out["db_bytes"] is None and out["wal_arquivo_bytes"] is None and out["shm_bytes"] is None
    assert out["page_size"] is None and out["page_size_cabecalho"] is None
    assert not (tmp_path / "studio.sqlite3").exists()                     # nao cria o banco


def test_sonda_arquivo_que_nao_e_sqlite_e_geracao_invalida(tmp_path):
    (tmp_path / "studio.sqlite3").write_bytes(b"nao sou sqlite" * 20)
    sombra = tmp_path / ".studio.sqlite3-litestream"
    sombra.mkdir()
    (sombra / "generation").write_text("../../etc", encoding="ascii")
    out = rodar(tmp_path)
    assert out["page_size_cabecalho"] is None and out["page_size"] is None
    assert out["geracao"] is None and out["sombra_bytes"] is None


def test_sonda_wal_apagado_no_fechamento(tmp_path):
    """Ao fechar a ultima conexao o SQLite faz checkpoint e APAGA o -wal: por isso o roteiro prefere o WAL-sombra."""
    dados = tmp_path / "data"
    banco_wal(dados, linhas=50).close()
    out = rodar(dados)
    assert out["wal_arquivo_bytes"] is None and out["page_size"] == 4096
