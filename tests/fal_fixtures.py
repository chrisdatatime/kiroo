"""Apoio dos testes do motor fal.ai: contrato de AMOSTRA (chaves inventadas, nao as reais) e resultados falsos.

Nada aqui e o formato real dos workflows: o real (parcialmente A CONFIRMAR, Fase 0) fica em profiles/fal/workflow_contract.json.
Quando as fixtures reais forem salvas localmente, os testes de integracao delas usam o contrato preenchido.
"""

from __future__ import annotations

import copy

SAMPLE_CONTRACT = {
    "version": 2,
    "status": "AMOSTRA DE TESTE",
    "styles": {
        style: {
            "workflow_env": f"WORKFLOW_ID_{style.upper()}",
            "input": {"image_field": "image_url", "extra": {}},
            "expected_duration_s": 15,
            "output": {"video": "video.url", "image": "images.0.url", "text": "output"},
            "recover": {"hero": {"node_id": "n_hero", "path": "image.url"}},
        } for style in ("dark", "light")
    },
}

BASE = "https://v3.fal.media/files/x"


def sample_contract():
    return copy.deepcopy(SAMPLE_CONTRACT)


TEXT = '{"title": "Copo azul de aco inox", "caption": "Mantem a bebida gelada por horas."}'


def sample_result(*, drop=(), envelope=True, text=TEXT):
    """Resultado bruto fictício no escopo real: video (com a narracao embutida), images (1 foto hero) e output (texto
    com JSON). `audio` e o intermediario de TTS do display: presente e IGNORADO. `drop`: caminhos a remover."""
    out = {
        "video": {"url": f"{BASE}/final.mp4"},
        "audio": {"url": f"{BASE}/voz.mp3"},
        "images": [{"url": f"{BASE}/hero.jpg"}],
        "output": text,
    }
    for d in drop:
        cur = out
        parts = d.split(".")
        for p in parts[:-1]:
            cur = cur[int(p)] if isinstance(cur, list) else cur[p]
        last = parts[-1]
        if isinstance(cur, list):
            cur[int(last)] = {}
        else:
            cur.pop(last, None)
    if not envelope:
        return out
    return {"output": out, "nodes": {"n_hero": {"endpoint": "fal-ai/img/a", "request_id": "r-hero"}}}
