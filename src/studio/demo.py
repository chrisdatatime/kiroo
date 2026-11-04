"""Produção de demonstração 100% SIMULADA (placeholders, sem custo)."""

from __future__ import annotations

from .config import Settings
from .models import ProductInput
from .providers.simulated import placeholder_png


def create_demo_production(orch, settings: Settings, *, budget_usd: float = 5.0, format_id: str = "maos_3cenas_15s",
                           art_direction: str = "cozinha_sp_alto_padrao", presenter: str = "bia") -> str:
    inputs = settings.data_dir / "demo_inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    refs = []
    for role in ("front", "side", "lid"):
        f = inputs / f"SIMULADO_ref_{role}.png"
        f.write_bytes(placeholder_png(f"demo-{role}", 540, 960))
        refs.append({"path": str(f), "role": role, "source": "official_listing", "note": "placeholder simulado"})
    product = ProductInput.model_validate({
        "name": "Copo com alça (DEMO SIMULADA)", "variant": "azul-claro",
        "affiliate_link": "https://s.shopee.com.br/SIMULADO-DEMO",
        "references": refs,
        "visual_attributes": {"cor": "azul-claro", "alça": "lateral", "tampa": "transparente com parte escura"},
        "claims": [{"field": "cor", "text": "Cor azul-claro", "kind": "verified", "source": "fotos oficiais (demo)"},
                   {"field": "capacidade", "text": "", "kind": "unknown", "source": "não informado"}],
    })
    return orch.create_production(product, format_id=format_id, art_direction=art_direction, presenter=presenter,
                                  budget_usd=budget_usd)
