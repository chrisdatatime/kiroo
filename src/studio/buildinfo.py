"""Qual código está no ar. Gravado em cada produção (evento production_created: mensagem e data.build).

Imagem Docker: STUDIO_BUILD_COMMIT vem do build-arg GIT_COMMIT. Fora do Docker: `git rev-parse HEAD` da pasta do código,
se houver. Sem nenhum dos dois: "desconhecido". Não é segredo (é o mesmo rótulo org.opencontainers.image.revision).
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def commit() -> str:
    env = (os.environ.get("STUDIO_BUILD_COMMIT") or "").strip()
    if env and env != "desconhecido":
        return env[:40]
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent, capture_output=True,
                             text=True, timeout=3, check=False)
        sha = out.stdout.strip()
        if out.returncode == 0 and len(sha) >= 7:
            return sha[:40]
    except (OSError, subprocess.SubprocessError):
        pass
    return "desconhecido"
