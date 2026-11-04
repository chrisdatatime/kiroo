"""Configuração dos agentes editável pela interface (data/agents.json).

Só campos não sensíveis e com valores validados. Modo real, permissão de chamadas
pagas e chaves continuam exclusivamente no .env.
Precedência: padrão → .env → data/agents.json → overrides explícitos no código.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import pricing

X264_PRESETS = ["ultrafast", "veryfast", "faster", "fast", "medium", "slow"]

AGENTS = [
    {"id": "orchestrator", "name": "Orquestrador", "color": "#8b5cf6", "uses_ai": False,
     "role": "Controla o fluxo e as dependências, persiste estados, controla tentativas e orçamento, retoma etapas "
             "interrompidas e encaminha problemas para você.",
     "fields": ["max_inflight_ops", "poll_interval_s"]},
    {"id": "prep", "name": "Preparação", "color": "#0ea5e9", "uses_ai": False,
     "role": "Lê a ficha, organiza as referências oficiais, separa fatos, alegações e desconhecidos e bloqueia "
             "quando falta material. Regras fixas, sem IA.",
     "fields": []},
    {"id": "creative", "name": "Direção criativa", "color": "#f59e0b", "uses_ai": True,
     "role": "Monta o roteiro por cena (objetivo, enquadramento, prompts, movimento, duração, critérios) a partir "
             "do formato e dos perfis; a IA pode refinar, o código valida.",
     "fields": ["planner_model"]},
    {"id": "images", "name": "Imagens", "color": "#ec4899", "uses_ai": True,
     "role": "Gera a imagem estática de cada cena com as fotos oficiais; a cena 1 vira referência de continuidade.",
     "fields": ["image_model", "image_size", "max_image_attempts"]},
    {"id": "review", "name": "Revisão visual", "color": "#14b8a6", "uses_ai": True,
     "role": "Compara imagens e quadros amostrados com as referências, mede proporção, duração e áudio. "
             "Pode responder 'inconclusivo'; não é garantia de qualidade.",
     "fields": ["reviewer_model"]},
    {"id": "videos", "name": "Vídeos", "color": "#ef4444", "uses_ai": True,
     "role": "Anima somente imagens aprovadas e acompanha as operações assíncronas no provedor.",
     "fields": ["video_model", "video_resolution", "max_video_attempts"]},
    {"id": "editor", "name": "Edição", "color": "#22c55e", "uses_ai": False,
     "role": "Monta os takes aprovados com FFmpeg, aplica cortes e textos, gera capa, legenda e relatórios.",
     "fields": ["x264_preset"]},
    {"id": "operator", "name": "Você", "color": "#BEF264", "uses_ai": False,
     "role": "Aprova, reprova e pede correções. Nada é publicado sem a sua revisão final.",
     "fields": []},
]
AGENT_IDS = {a["id"] for a in AGENTS}


def field_options() -> dict:
    image_models = sorted({m for m, _ in pricing.IMAGE_PRICES})
    video_models = sorted({m for m, _ in pricing.VIDEO_PRICES})
    return {
        "planner_model": {"label": "Modelo de planejamento", "type": "select", "choices": sorted(pricing.LLM_PRICES)},
        "reviewer_model": {"label": "Modelo de revisão", "type": "select", "choices": sorted(pricing.LLM_PRICES)},
        "image_model": {"label": "Modelo de imagem", "type": "select", "choices": image_models},
        "image_size": {"label": "Resolução da imagem", "type": "select",
                       "choices_by": {m: sorted(s for mm, s in pricing.IMAGE_PRICES if mm == m) for m in image_models},
                       "depends_on": "image_model"},
        "video_model": {"label": "Modelo de vídeo", "type": "select", "choices": video_models},
        "video_resolution": {"label": "Resolução do vídeo", "type": "select",
                             "choices_by": {m: sorted(r for mm, r in pricing.VIDEO_PRICES if mm == m) for m in video_models},
                             "depends_on": "video_model"},
        "max_image_attempts": {"label": "Tentativas de imagem por cena", "type": "int", "min": 1, "max": 10},
        "max_video_attempts": {"label": "Tentativas de vídeo por cena", "type": "int", "min": 1, "max": 10},
        "max_inflight_ops": {"label": "Operações simultâneas", "type": "int", "min": 1, "max": 8},
        "poll_interval_s": {"label": "Intervalo de consulta (s)", "type": "float", "min": 2, "max": 120},
        "x264_preset": {"label": "Preset de compressão", "type": "select", "choices": X264_PRESETS},
    }


def _path(data_dir: Path) -> Path:
    return data_dir / "agents.json"


def load(data_dir: Path) -> dict:
    p = _path(data_dir)
    empty = {"settings": {}, "agents": {}, "runtime": {}}
    if not p.exists():
        return empty
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    return {"settings": data.get("settings", {}), "agents": data.get("agents", {}), "runtime": data.get("runtime", {})}


def validate_settings(values: dict, current: dict) -> dict:
    opts = field_options()
    merged = {**current, **values}
    clean = {}
    for key, value in values.items():
        spec = opts.get(key)
        if spec is None:
            raise ValueError(f"campo não configurável: {key}")
        if spec["type"] == "select":
            choices = spec.get("choices") or spec["choices_by"].get(merged.get(spec.get("depends_on")), [])
            if value not in choices:
                raise ValueError(f"{spec['label']}: valor inválido {value!r}")
            clean[key] = value
        else:
            cast = int if spec["type"] == "int" else float
            try:
                number = cast(value)
            except (TypeError, ValueError):
                raise ValueError(f"{spec['label']}: número inválido") from None
            if not spec["min"] <= number <= spec["max"]:
                raise ValueError(f"{spec['label']}: use entre {spec['min']} e {spec['max']}")
            clean[key] = number
    # consistência modelo ↔ resolução
    for model_key, dep_key in (("image_model", "image_size"), ("video_model", "video_resolution")):
        allowed = opts[dep_key]["choices_by"].get(merged.get(model_key), [])
        if merged.get(dep_key) not in allowed:
            raise ValueError(f"{opts[dep_key]['label']} {merged.get(dep_key)!r} não tem preço cadastrado para "
                             f"{merged.get(model_key)}")
    return clean


def validate_agents(values: dict) -> dict:
    clean = {}
    for agent_id, cfg in values.items():
        if agent_id not in AGENT_IDS:
            raise ValueError(f"agente desconhecido: {agent_id}")
        item = {}
        if "name" in cfg:
            name = str(cfg["name"]).strip()
            if not 1 <= len(name) <= 24:
                raise ValueError("nome do agente deve ter de 1 a 24 caracteres")
            item["name"] = name
        if "color" in cfg:
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(cfg["color"])):
                raise ValueError("cor deve estar no formato #RRGGBB")
            item["color"] = cfg["color"]
        clean[agent_id] = item
    return clean


def save(data_dir: Path, *, settings: dict | None = None, agents: dict | None = None, current: dict) -> dict:
    data = load(data_dir)
    if settings:
        data["settings"].update(validate_settings(settings, current))
    if agents:
        for agent_id, cfg in validate_agents(agents).items():
            data["agents"].setdefault(agent_id, {}).update(cfg)
    data_dir.mkdir(parents=True, exist_ok=True)
    _path(data_dir).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def save_runtime(data_dir: Path, *, mode: str | None = None, monthly_cap_usd: float | None = None,
                 api_key_defined: bool, current_cap: float) -> dict:
    """Liga/desliga o DEMO e define o teto mensal. Sair do DEMO exige chave e teto > 0."""
    data = load(data_dir)
    runtime = data["runtime"]
    if monthly_cap_usd is not None:
        cap = float(monthly_cap_usd)
        if not 0 <= cap <= 10000:
            raise ValueError("teto mensal deve estar entre 0 e 10000 US$")
        runtime["monthly_cap_usd"] = cap
    if mode is not None:
        if mode not in {"simulated", "real"}:
            raise ValueError("modo inválido")
        if mode == "real":
            if not api_key_defined:
                raise ValueError("defina GEMINI_API_KEY no .env antes de desligar o DEMO")
            if runtime.get("monthly_cap_usd", current_cap) <= 0:
                raise ValueError("defina um teto mensal de gastos maior que zero antes de desligar o DEMO")
        runtime["mode"] = mode
    data_dir.mkdir(parents=True, exist_ok=True)
    _path(data_dir).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return runtime


def agents_with_overrides(data_dir: Path) -> list[dict]:
    overrides = load(data_dir)["agents"]
    return [{**a, **overrides.get(a["id"], {})} for a in AGENTS]
