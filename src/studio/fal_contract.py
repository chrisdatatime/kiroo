"""Contrato do pacote de producao do motor fal.ai.

Duas camadas, de proposito:

* CANONICA (`WorkflowPackage`, `Artifact`): o que o resto do Kiroo conhece. Video, narracao, musica (opcional),
  descricao, texto da narracao e 3 imagens com papel (hero, lifestyle, details). Parser, validador, composer, simulado,
  fixtures e testes so falam este formato.
* EXTERNA: o mapeamento das chaves reais de cada workflow da fal.ai, que vive SOMENTE em
  `profiles/fal/workflow_contract.json` e neste modulo (`parse_result`). Todo valor la esta `A CONFIRMAR (Fase 0)` ate
  alguem rodar os workflows no playground. O papel de cada imagem vem do mapeamento, nunca da ordem de uma lista.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER = "A CONFIRMAR"
STYLES = ("dark", "light")
STYLE_LABELS = {"dark": "Escuro", "light": "Claro"}
ROLES = ("hero", "lifestyle", "details")
ROLE_LABELS = {"hero": "Hero Shot", "lifestyle": "Lifestyle", "details": "Detalhes"}
IMAGE_FILES = {"hero": "product_image_01.jpg", "lifestyle": "product_image_02.jpg", "details": "product_image_03.jpg"}
FINAL_VIDEO = "final.mp4"
REQUIRED_COMPONENTS = ("video", "narration")      # sem eles: falha tecnica (sem debito ao cliente)
OPTIONAL_COMPONENTS = ("music",)                   # sem musica: entrega com aviso
CONTRACT_FILE = ("fal", "workflow_contract.json")


class ContractError(ValueError):
    pass


@dataclass
class Artifact:
    """Um arquivo do pacote. `url` (a baixar), `data` (ja em memoria) ou `path` (ja em disco). `recover` guarda de onde
    buscar de novo SO este arquivo (endpoint e request_id do no), sem reexecutar o workflow."""

    kind: str                       # video | narration | music | image
    role: str | None = None         # hero | lifestyle | details (imagens)
    url: str | None = None
    data: bytes | None = None
    path: Path | None = None
    mime: str | None = None
    recover: dict | None = None     # {"endpoint": ..., "request_id": ..., "path": ...}

    @property
    def available(self) -> bool:
        return bool(self.url or self.data or self.path)


@dataclass
class WorkflowPackage:
    video: Artifact | None = None
    narration: Artifact | None = None
    music: Artifact | None = None
    description: str = ""
    narration_text: str = ""
    images: dict[str, Artifact | None] = field(default_factory=lambda: {r: None for r in ROLES})
    nodes: dict = field(default_factory=dict)          # envelope: {node_id: {"endpoint", "request_id"}}
    warnings: list[str] = field(default_factory=list)

    def missing(self) -> list[str]:
        """Componentes ausentes (nomes canonicos: video, narration, music, image:<papel>)."""
        out = []
        for c in (*REQUIRED_COMPONENTS, *OPTIONAL_COMPONENTS):
            a = getattr(self, c)
            if a is None or not a.available:
                out.append(c)
        for r in ROLES:
            a = self.images.get(r)
            if a is None or not a.available:
                out.append(f"image:{r}")
        return out

    def failure_kind(self) -> str | None:
        """None = pacote completo (ou so sem musica). 'technical' = sem video ou sem narracao. 'incomplete' = falta
        imagem (a entrega nao pode ser dada como completa)."""
        miss = self.missing()
        if any(m in REQUIRED_COMPONENTS for m in miss):
            return "technical"
        if any(m.startswith("image:") for m in miss):
            return "incomplete"
        return None

    def missing_images(self) -> list[str]:
        return [m.split(":", 1)[1] for m in self.missing() if m.startswith("image:")]


# ------------------------------------------------------------------ contrato externo
def contract_path(profiles_dir: Path) -> Path:
    return Path(profiles_dir).joinpath(*CONTRACT_FILE)


def load_contract(profiles_dir: Path) -> dict:
    p = contract_path(profiles_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"contrato dos workflows ilegivel ({p.name}): {exc}") from None


def _is_placeholder(v) -> bool:
    return isinstance(v, str) and v.strip().upper().startswith(PLACEHOLDER)


def placeholders(contract: dict, style: str) -> list[str]:
    """Campos do estilo ainda marcados como A CONFIRMAR (a Fase 0 ainda nao os preencheu)."""
    cfg = (contract.get("styles") or {}).get(style)
    if cfg is None:
        return [f"estilo {style} ausente"]
    out: list[str] = []

    def walk(prefix, v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(f"{prefix}.{k}" if prefix else k, x)
        elif _is_placeholder(v):
            out.append(prefix)
    for key in ("input", "output", "recover"):
        walk(key, cfg.get(key))
    return out


def style_config(contract: dict, style: str) -> dict:
    cfg = (contract.get("styles") or {}).get(style)
    if style not in STYLES or cfg is None:
        raise ContractError(f"estilo invalido: {style!r}")
    return cfg


def get_path(obj, path: str):
    """'images.0.url' sobre dicts e listas. Ausente ou placeholder: None (nunca levanta)."""
    if not isinstance(path, str) or not path or _is_placeholder(path):
        return None
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list) and part.lstrip("-").isdigit():
            i = int(part)
            if not -len(cur) <= i < len(cur):
                return None
            cur = cur[i]
        else:
            return None
    return cur


def _url_of(v) -> str | None:
    """Aceita a URL direto ou um objeto de arquivo da fal ({"url": ...})."""
    if isinstance(v, str):
        return v if v.startswith(("http://", "https://")) else None
    if isinstance(v, dict):
        u = v.get("url")
        return u if isinstance(u, str) and u.startswith(("http://", "https://")) else None
    return None


def _text_of(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def build_input(contract: dict, style: str, image_url: str) -> dict:
    """Corpo do submit: o campo da imagem (A CONFIRMAR) mais os extras fixos do estilo."""
    cfg = style_config(contract, style)
    field_ = (cfg.get("input") or {}).get("image_field")
    if not field_ or _is_placeholder(field_):
        raise ContractError("campo de entrada da imagem ainda A CONFIRMAR (Fase 0)")
    return {**((cfg.get("input") or {}).get("extra") or {}), field_: image_url}


def parse_result(result: dict, style: str, contract: dict) -> WorkflowPackage:
    """Resultado bruto da fal.ai -> pacote canonico. Nao baixa nada. O papel de cada imagem vem do mapeamento."""
    cfg = style_config(contract, style)
    out_map = cfg.get("output") or {}
    envelope = isinstance(result, dict) and "output" in result and isinstance(result.get("nodes"), dict)
    output = result.get("output") if envelope else result
    nodes: dict = {}
    if envelope:
        for nid, n in result["nodes"].items():
            if isinstance(n, dict):
                nodes[str(nid)] = {"endpoint": n.get("endpoint"), "request_id": n.get("request_id")}
    pkg = WorkflowPackage(nodes=nodes)
    for kind in ("video", "narration", "music"):
        url = _url_of(get_path(output, out_map.get(kind, "")))
        if url:
            setattr(pkg, kind, Artifact(kind=kind, url=url))
    pkg.description = _text_of(get_path(output, out_map.get("description", "")))
    pkg.narration_text = _text_of(get_path(output, out_map.get("narration_text", "")))
    rec = cfg.get("recover") or {}
    for role in ROLES:
        url = _url_of(get_path(output, (out_map.get("images") or {}).get(role, "")))
        r = rec.get(role) or {}
        nid = r.get("node_id")
        node = nodes.get(str(nid)) if nid and not _is_placeholder(nid) else None
        ok = node and node.get("endpoint") and node.get("request_id") and r.get("path") and not _is_placeholder(r.get("path"))
        recover = {"endpoint": node["endpoint"], "request_id": node["request_id"], "path": r["path"]} if ok else None
        if url or recover:
            pkg.images[role] = Artifact(kind="image", role=role, url=url, recover=recover)
    if pkg.music is None:
        pkg.warnings.append("workflow nao devolveu trilha: o video sai so com a narracao")
    return pkg


# ------------------------------------------------------------------ persistencia (result.json)
def _artifact_to_dict(a: Artifact | None) -> dict | None:
    if a is None:
        return None
    return {"kind": a.kind, "role": a.role, "url": a.url, "path": str(a.path) if a.path else None, "mime": a.mime,
            "recover": a.recover}


def _artifact_from_dict(d: dict | None) -> Artifact | None:
    if not d:
        return None
    return Artifact(kind=d["kind"], role=d.get("role"), url=d.get("url"), path=Path(d["path"]) if d.get("path") else None,
                    mime=d.get("mime"), recover=d.get("recover"))


def package_to_dict(pkg: WorkflowPackage) -> dict:
    """Pacote canonico -> JSON (so enderecos e metadados; os bytes ficam em arquivos). Guardado em result.json."""
    return {"video": _artifact_to_dict(pkg.video), "narration": _artifact_to_dict(pkg.narration),
            "music": _artifact_to_dict(pkg.music), "description": pkg.description, "narration_text": pkg.narration_text,
            "images": {r: _artifact_to_dict(pkg.images.get(r)) for r in ROLES}, "nodes": pkg.nodes,
            "warnings": list(pkg.warnings)}


def package_from_dict(d: dict) -> WorkflowPackage:
    pkg = WorkflowPackage(video=_artifact_from_dict(d.get("video")), narration=_artifact_from_dict(d.get("narration")),
                          music=_artifact_from_dict(d.get("music")), description=d.get("description") or "",
                          narration_text=d.get("narration_text") or "", nodes=d.get("nodes") or {},
                          warnings=list(d.get("warnings") or []))
    for r in ROLES:
        pkg.images[r] = _artifact_from_dict((d.get("images") or {}).get(r))
    return pkg
