"""Testes de integração REAL (pagos). Desligados por padrão.

Para rodar (gera 1 imagem e, opcionalmente, 1 vídeo — custo real):
    STUDIO_RUN_REAL_TESTS=1 STUDIO_REAL_TEST_BUDGET_USD=2 GEMINI_API_KEY=... pytest -m real tests/integration
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real

ENABLED = os.environ.get("STUDIO_RUN_REAL_TESTS") == "1" and os.environ.get("GEMINI_API_KEY")
BUDGET = float(os.environ.get("STUDIO_REAL_TEST_BUDGET_USD", "0"))


@pytest.mark.skipif(not ENABLED or BUDGET <= 0, reason="integração real desligada ou sem orçamento")
def test_real_image_generation_with_reference(tmp_path):
    from studio import pricing
    from studio.providers.base import ImageRequest, OpState
    from studio.providers.gemini import GeminiImageGenerator

    ref = Path(os.environ["STUDIO_REAL_TEST_REFERENCE"])  # foto oficial de produto
    model = os.environ.get("STUDIO_IMAGE_MODEL", "gemini-nano-banana-2.1")
    req = ImageRequest(prompt="Vertical 9:16 product photo on a light kitchen countertop. Keep the product identical "
                              "to the reference. No text.", reference_images=[ref], aspect_ratio="9:16", image_size="1K")
    cost, _ = pricing.image_cost(model, "1K", 1)
    assert cost <= BUDGET
    gen = GeminiImageGenerator(os.environ["GEMINI_API_KEY"], model)
    op = gen.submit(req)
    import time
    for _ in range(60):
        result = gen.poll(op)
        if result.state != OpState.RUNNING:
            break
        time.sleep(5)
    assert result.state == OpState.SUCCEEDED, result.error
    (tmp_path / "real.png").write_bytes(result.data)
