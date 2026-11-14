"""Fixtures REAIS dos workflows (Fase 0), salvas localmente. Pulado enquanto a pasta estiver vazia.

Como usar (detalhes em docs/FAL.md): rode cada workflow UMA vez no playground, salve o JSON do resultado em
tests/fixtures/fal_real/<nome>/result.json (com o envelope, se possivel) e preencha o que sobrou A CONFIRMAR em
profiles/fal/workflow_contract.json (indice da foto em `images`, recuperacao pelo no). Este teste confere que o
contrato preenchido le o resultado real: video, foto hero e o JSON {"title","caption"} em `output`.
Nada aqui chama a rede nem gasta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio import fal_contract as fc
from studio.config import PROJECT_ROOT

FIX = Path(__file__).parent / "fixtures" / "fal_real"
CASES = [d.name for d in sorted(FIX.glob("*")) if (d / "result.json").is_file()] if FIX.is_dir() else []


@pytest.mark.skipif(not CASES, reason="sem fixtures reais em tests/fixtures/fal_real/<nome>/result.json (Fase 0)")
@pytest.mark.parametrize("case", CASES)
def test_filled_contract_reads_the_real_result(case):
    contract = fc.load_contract(PROJECT_ROOT / "profiles")
    assert fc.placeholders(contract) == [], "contrato ainda tem campos A CONFIRMAR"
    result = json.loads((FIX / case / "result.json").read_text(encoding="utf-8"))
    pkg = fc.parse_result(result, contract)
    assert pkg.missing() == [], f"o resultado real nao traz: {pkg.missing()}"
    assert pkg.failure_kind() is None
    assert pkg.video.url and pkg.hero.url
    # o prompt manda descrever de forma generica quando nao identifica o produto: so conferimos que o JSON foi lido
    assert pkg.title or pkg.caption or pkg.warnings
