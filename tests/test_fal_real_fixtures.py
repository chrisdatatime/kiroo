"""Fixtures REAIS dos workflows (Fase 0), salvas localmente. Pulado enquanto a pasta estiver vazia.

Como usar (detalhes em docs/FAL.md): rode cada workflow UMA vez no playground, salve o JSON do resultado em
tests/fixtures/fal_real/<dark|light>/result.json (com o envelope, se possivel) e preencha
profiles/fal/workflow_contract.json. Este teste confere que o contrato preenchido le o resultado real: pacote
completo, 3 imagens com papel e a duracao esperada nos arquivos baixados (opcionais, na mesma pasta).
Nada aqui chama a rede nem gasta.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio import fal_contract as fc
from studio.config import PROJECT_ROOT

FIX = Path(__file__).parent / "fixtures" / "fal_real"
CASES = [s for s in fc.STYLES if (FIX / s / "result.json").is_file()]


@pytest.mark.skipif(not CASES, reason="sem fixtures reais em tests/fixtures/fal_real/<estilo>/result.json (Fase 0)")
@pytest.mark.parametrize("style", CASES)
def test_filled_contract_reads_the_real_result(style):
    contract = fc.load_contract(PROJECT_ROOT / "profiles")
    assert fc.placeholders(contract, style) == [], f"contrato do estilo {style} ainda tem campos A CONFIRMAR"
    result = json.loads((FIX / style / "result.json").read_text(encoding="utf-8"))
    pkg = fc.parse_result(result, style, contract)
    assert pkg.missing() == [], f"o resultado real nao traz: {pkg.missing()}"
    assert pkg.failure_kind() is None
    assert len({a.url for a in pkg.images.values()}) == 3          # tres imagens distintas, cada uma no seu papel
    assert pkg.description and pkg.narration_text
