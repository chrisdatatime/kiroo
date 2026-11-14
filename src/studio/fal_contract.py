"""Contrato do pacote de producao do motor fal.ai.

Duas camadas, de proposito:

* CANONICA (`WorkflowPackage`, `Artifact`): o que o resto do Kiroo conhece. UM video (ja com a narracao embutida, sem
  musica), UMA foto hero e o texto (titulo + legenda). Parser, validador, composer, simulado, fixtures e testes so
  falam este formato.
* EXTERNA: o mapeamento das chaves reais de cada workflow da fal.ai, que vive SOMENTE em
  `profiles/fal/workflow_contract.json` e neste modulo (`parse_result`). O que ainda depende da fixture real (Fase 0)
  fica `A CONFIRMAR` la.

O workflow tem UM input (`image_url`) e devolve `video`, `images` (1 foto hero) e `output` (texto com JSON
`{"title","caption"}`). A saida `audio` do display e intermediaria de TTS: ignorada, nunca entregue nem validada.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER = "A CONFIRMAR"
STYLES = ("dark", "light")
STYLE_LABELS = {"dark": "Escuro", "light": "Claro"}
HERO_LABEL = "Hero Shot"
HERO_FILE = "product_image_01.jpg"
FINAL_VIDEO = "final.mp4"
COVER_FILE = "cover.jpg"
CAPTION_FILE = "caption.txt"
REQUIRED_COMPONENTS = ("video",)                  # sem video (ou sem audio nele): falha tecnica (sem debito ao cliente)
CONTRACT_FILE = ("fal", "workflow_contract.json")


class ContractError(ValueError):
    pass


@dataclass
class Artifact:
    """Um arquivo do pacote. `url` (a baixar), `data` (ja em memoria) ou `path` (ja em disco). `recover` guarda de onde
    buscar de novo SO este arquivo (endpoint e request_id do no), sem reexecutar o workflow."""

    kind: str                       # video | image
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
    hero: Artifact | None = None
    title: str = ""
    caption: str = ""
    nodes: dict = field(default_factory=dict)          # envelope: {node_id: {"endpoint", "request_id"}}
    warnings: list[str] = field(default_factory=list)

    def missing(self) -> list[str]:
        """Componentes ausentes (nomes canonicos: video, hero)."""
        out = []
        if self.video is None or not self.video.available:
            out.append("video")
        if self.hero is None or not self.hero.available:
            out.append("hero")
        return out

    def failure_kind(self) -> str | None:
        """None = pacote completo. 'technical' = sem video. 'incomplete' = falta a foto hero (a entrega nao pode ser dada
        como completa). Falta de titulo/legenda NAO entra aqui: e so aviso."""
        miss = self.missing()
        if "video" in miss:
            return "technical"
        if "hero" in miss:
            return "incomplete"
        return None


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
    out.extend(f"pendente: {x}" for x in (cfg.get("pending") or []))
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


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_text_output(raw) -> tuple[str, str, list[str]]:
    """Saida `output` do workflow -> (titulo, legenda, avisos). O texto traz JSON `{"title","caption"}` (aceita cerca
    ```json e dict ja decodificado). JSON invalido, vazio ou com campos vazios (o prompt manda devolver strings vazias
    quando nao identifica o produto): devolve o que houver, com aviso. NUNCA inventa texto."""
    data = raw
    if isinstance(raw, str):
        txt = _FENCE.sub("", raw.strip()).strip()
        if not txt:
            return "", "", ["o workflow nao devolveu titulo nem legenda: escreva a legenda antes de publicar"]
        try:
            data = json.loads(txt)
        except ValueError:
            a, b = txt.find("{"), txt.rfind("}")
            try:
                data = json.loads(txt[a:b + 1]) if 0 <= a < b else None
            except ValueError:
                data = None
    if not isinstance(data, dict):
        return "", "", ["o texto do workflow nao e um JSON valido (title/caption): descartado; escreva a legenda antes de publicar"]
    title, caption = _text_of(data.get("title")), _text_of(data.get("caption"))
    warns = []
    if not title and not caption:
        warns.append("o workflow nao identificou o produto (titulo e legenda vazios): escreva a legenda antes de publicar")
    elif not title:
        warns.append("o workflow nao devolveu titulo")
    elif not caption:
        warns.append("o workflow nao devolveu legenda")
    return title, caption, warns


def parse_result(result: dict, style: str, contract: dict) -> WorkflowPackage:
    """Resultado bruto da fal.ai -> pacote canonico. Nao baixa nada."""
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
    url = _url_of(get_path(output, out_map.get("video", "")))
    if url:
        pkg.video = Artifact(kind="video", url=url)
    r = (cfg.get("recover") or {}).get("hero") or {}
    url = _url_of(get_path(output, out_map.get("image", "")))
    nid = r.get("node_id")
    node = nodes.get(str(nid)) if nid and not _is_placeholder(nid) else None
    ok = node and node.get("endpoint") and node.get("request_id") and r.get("path") and not _is_placeholder(r.get("path"))
    recover = {"endpoint": node["endpoint"], "request_id": node["request_id"], "path": r["path"]} if ok else None
    if url or recover:
        pkg.hero = Artifact(kind="image", url=url, recover=recover)
    pkg.title, pkg.caption, warns = parse_text_output(get_path(output, out_map.get("text", "")))
    pkg.warnings.extend(warns)
    return pkg


# ------------------------------------------------------------------ persistencia (result.json)
def _artifact_to_dict(a: Artifact | None) -> dict | None:
    if a is None:
        return None
    return {"kind": a.kind, "url": a.url, "path": str(a.path) if a.path else None, "mime": a.mime, "recover": a.recover}


def _artifact_from_dict(d: dict | None) -> Artifact | None:
    if not d:
        return None
    return Artifact(kind=d["kind"], url=d.get("url"), path=Path(d["path"]) if d.get("path") else None,
                    mime=d.get("mime"), recover=d.get("recover"))


def package_to_dict(pkg: WorkflowPackage) -> dict:
    """Pacote canonico -> JSON (so enderecos e metadados; os bytes ficam em arquivos). Guardado em result.json."""
    return {"video": _artifact_to_dict(pkg.video), "hero": _artifact_to_dict(pkg.hero), "title": pkg.title,
            "caption": pkg.caption, "nodes": pkg.nodes, "warnings": list(pkg.warnings)}


def package_from_dict(d: dict) -> WorkflowPackage:
    return WorkflowPackage(video=_artifact_from_dict(d.get("video")), hero=_artifact_from_dict(d.get("hero")),
                           title=d.get("title") or "", caption=d.get("caption") or "", nodes=d.get("nodes") or {},
                           warnings=list(d.get("warnings") or []))
