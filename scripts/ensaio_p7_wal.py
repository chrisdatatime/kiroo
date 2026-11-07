"""Sonda do passo 7 do ensaio: tamanhos do banco, do -wal e do WAL-sombra do Litestream num volume PARADO.

Uso (dentro de um container descartavel, volume montado SO LEITURA):  python ensaio_p7_wal.py /data
Imprime um JSON. Nada e escrito: so os.stat, leitura do cabecalho do banco e uma conexao sqlite com immutable=1
(nao cria -shm, nao faz checkpoint, nao apaga o -wal). Sem credenciais: so tamanhos, page_size e o id da geracao.

Campos:
  db_bytes, wal_arquivo_bytes, shm_bytes   tamanho de studio.sqlite3 / -wal / -shm (null = arquivo ausente)
  page_size                                PRAGMA page_size (conexao somente leitura, immutable=1)
  page_size_cabecalho                      bytes 16-17 do cabecalho do banco (conferencia; 1 = 65536)
  geracao, sombra_indice, sombra_bytes     ultimo indice do WAL-sombra do Litestream:
                                           .studio.sqlite3-litestream/generations/<geracao>/wal/<indice>.wal
  sombra_arquivos                          quantos indices de WAL-sombra existem na geracao
"""
import glob
import json
import os
import re
import sqlite3
import sys


def tamanho(caminho):
    try:
        return os.path.getsize(caminho)
    except OSError:
        return None


def page_size_cabecalho(db):
    try:
        with open(db, "rb") as f:
            h = f.read(100)
    except OSError:
        return None
    if len(h) < 100 or not h.startswith(b"SQLite format 3\x00"):
        return None
    v = int.from_bytes(h[16:18], "big")
    return 65536 if v == 1 else v


def page_size_pragma(db):
    if not os.path.isfile(db):
        return None
    try:
        con = sqlite3.connect("file:" + db + "?mode=ro&immutable=1", uri=True)
        try:
            # sem ler o banco o PRAGMA page_size devolve o padrao (4096) ate para um arquivo que nao e SQLite:
            # schema_version forca a leitura do cabecalho e falha com "file is not a database"
            con.execute("PRAGMA schema_version").fetchone()
            return int(con.execute("PRAGMA page_size").fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return None


def sombra(dados, nome_db):
    vazio = {"geracao": None, "sombra_indice": None, "sombra_bytes": None, "sombra_arquivos": 0}
    base = os.path.join(dados, "." + nome_db + "-litestream")
    try:
        with open(os.path.join(base, "generation"), encoding="ascii") as f:
            gen = f.read().strip()
    except (OSError, UnicodeDecodeError):
        return vazio
    if not re.fullmatch(r"[0-9a-f]{16}", gen):
        return vazio
    arqs = [p for p in glob.glob(os.path.join(base, "generations", gen, "wal", "*.wal"))
            if re.fullmatch(r"[0-9a-f]{8}\.wal", os.path.basename(p))]
    if not arqs:
        return dict(vazio, geracao=gen)
    ultimo = max(arqs, key=lambda p: int(os.path.basename(p)[:8], 16))
    return {"geracao": gen, "sombra_indice": os.path.basename(ultimo)[:8], "sombra_bytes": tamanho(ultimo),
            "sombra_arquivos": len(arqs)}


def sonda(dados):
    db = os.path.join(dados, "studio.sqlite3")
    out = {"db_bytes": tamanho(db), "wal_arquivo_bytes": tamanho(db + "-wal"), "shm_bytes": tamanho(db + "-shm"),
           "page_size": page_size_pragma(db), "page_size_cabecalho": page_size_cabecalho(db)}
    out.update(sombra(dados, "studio.sqlite3"))
    return out


if __name__ == "__main__":
    print(json.dumps(sonda(sys.argv[1] if len(sys.argv) > 1 else "/data")))
