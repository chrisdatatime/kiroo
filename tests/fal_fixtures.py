"""Apoio dos testes do motor fal.ai: contrato de AMOSTRA (chaves inventadas, nao as reais) e resultados falsos.

Nada aqui e o formato real dos workflows: o real fica A CONFIRMAR (Fase 0) em profiles/fal/workflow_contract.json.
Quando as fixtures reais forem salvas localmente, os testes de integracao delas usam o contrato preenchido.
"""

from __future__ import annotations

import copy

SAMPLE_CONTRACT = {
    "version": 1,
    "status": "AMOSTRA DE TESTE",
    "styles": {
        style: {
            "workflow_env": f"WORKFLOW_ID_{style.upper()}",
            "input": {"image_field": "photo_url", "extra": {"language": "pt-BR"}},
            "expected_duration_s": 15,
            "output": {
                "video": "final.video.url", "narration": "audio.voice.url", "music": "audio.music.url",
                "description": "text.description", "narration_text": "text.script",
                "images": {"hero": "pics.2.url", "lifestyle": "pics.0.url", "details": "pics.1.url"},
            },
            "recover": {
                "hero": {"node_id": "n_hero", "path": "image.url"},
                "lifestyle": {"node_id": "n_life", "path": "image.url"},
                "details": {"node_id": "n_det", "path": "image.url"},
            },
        } for style in ("dark", "light")
    },
}

BASE = "https://v3.fal.media/files/x"


def sample_contract():
    return copy.deepcopy(SAMPLE_CONTRACT)


def sample_result(*, drop=(), envelope=True):
    """Resultado bruto fictício. `drop`: caminhos a remover (ex.: 'audio.music', 'pics.1')."""
    out = {
        "final": {"video": {"url": f"{BASE}/final.mp4"}},
        "audio": {"voice": {"url": f"{BASE}/voz.mp3"}, "music": {"url": f"{BASE}/trilha.mp3"}},
        "text": {"description": "Copo azul de aco inox.", "script": "Conheca o copo que acompanha seu dia."},
        # a ORDEM da lista nao define o papel: o mapeamento do contrato define (aqui, deliberadamente embaralhada)
        "pics": [{"url": f"{BASE}/lifestyle.jpg"}, {"url": f"{BASE}/details.jpg"}, {"url": f"{BASE}/hero.jpg"}],
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
    return {"output": out, "nodes": {
        "n_hero": {"endpoint": "fal-ai/img/a", "request_id": "r-hero"},
        "n_life": {"endpoint": "fal-ai/img/b", "request_id": "r-life"},
        "n_det": {"endpoint": "fal-ai/img/c", "request_id": "r-det"},
    }}
