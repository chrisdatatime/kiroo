"""Falha se algum arquivo licenciado/pessoal estiver rastreado pelo Git (baseado em `git ls-files`).

Uso: python scripts/check_licensed_files.py [--repo <pasta>]
Não apaga nem reescreve nada; só lê o índice. Arte LimeZu, a foto pessoal e pacotes ZIP ficam fora do Git
(entram na imagem pelo pacote privado; ver docs/DOCKER.md).
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

# (padrão fnmatch sobre o caminho com "/", motivo). `*` casa também "/" em fnmatch.
FORBIDDEN = (
    ("assets/characters/*", "personagens LimeZu (licença: não distribuir)"),
    ("assets/tilesets/*", "tilesets LimeZu (licença: não distribuir)"),
    ("frontend/src/assets/home/*", "imagens da home derivadas de arte LimeZu"),
    ("assets/bia/*", "foto pessoal da apresentadora"),
    ("pacote-assets/*", "pacote privado de assets"),
    ("*.zip", "pacotes ZIP (podem conter arte licenciada)"),
    ("*-office/*", "projeto de terceiros (escritório virtual), fora do deploy"),
    ("data/*", "dados de execução"),
    ("*.sqlite3", "banco de dados"),
    ("*.sqlite3-wal", "banco de dados"),
    ("*.sqlite3-shm", "banco de dados"),
)


def tracked_files(repo: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def violations(files: list[str]) -> list[tuple[str, str]]:
    found = []
    for f in files:
        for pattern, why in FORBIDDEN:
            if fnmatch.fnmatchcase(f, pattern):
                found.append((f, why))
                break
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    bad = violations(tracked_files(Path(args.repo)))
    if bad:
        print("arquivos licenciados/pessoais rastreados pelo Git (remova do índice com `git rm --cached`):", file=sys.stderr)
        for f, why in bad:
            print(f"  {f}  <- {why}", file=sys.stderr)
        return 1
    print("ok: nenhum arquivo licenciado ou pessoal rastreado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
