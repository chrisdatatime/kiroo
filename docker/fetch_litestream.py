"""Baixa o binário do Litestream fixado em docker/litestream.lock e confere o SHA-256 (stage `litestream` do Dockerfile).

    python fetch_litestream.py --lock litestream.lock --out /out/litestream

Falha fechada: hash ausente, "PENDING" ou divergente => o build para. Nenhuma credencial é usada (release pública).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import tarfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

MAX_BYTES = 64 * 1024 * 1024


class LitestreamError(Exception):
    pass


def read_lock(path: Path) -> dict:
    try:
        lock = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LitestreamError(f"litestream.lock ilegível: {exc}") from None
    for key in ("version", "url", "sha256"):
        if not isinstance(lock.get(key), str) or not lock[key]:
            raise LitestreamError(f"litestream.lock sem o campo '{key}'")
    u = urlparse(lock["url"])
    if u.scheme != "https" or u.hostname != "github.com" or not u.path.startswith("/benbjohnson/litestream/releases/download/"):
        raise LitestreamError("litestream.lock: a URL precisa ser uma release oficial em https://github.com/benbjohnson/litestream")
    if not re.fullmatch(r"[0-9a-f]{64}", lock["sha256"]):
        raise LitestreamError(
            "litestream.lock: sha256 pendente ou inválido. Preencha com o SHA-256 do tar.gz da release "
            "(veja docs/BACKUP.md, 'Fixar o hash do Litestream') antes de construir a imagem.")
    return lock


def extract_binary(blob: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.split("/")[-1] == "litestream" and 0 < m.size <= MAX_BYTES:
                f = tf.extractfile(m)
                if f is not None:
                    return f.read()
    raise LitestreamError("binário 'litestream' não encontrado no pacote")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        lock = read_lock(a.lock)
        with urllib.request.urlopen(lock["url"], timeout=60) as resp:   # noqa: S310 — host validado em read_lock
            blob = resp.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise LitestreamError("pacote maior que o limite")
        got = hashlib.sha256(blob).hexdigest()
        if got != lock["sha256"]:
            raise LitestreamError(f"SHA-256 diferente do litestream.lock (esperado {lock['sha256']}, obtido {got})")
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(extract_binary(blob))
        a.out.chmod(a.out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"litestream {lock['version']} ok (sha256 conferido)")
        return 0
    except LitestreamError as exc:
        print(f"fetch_litestream: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
