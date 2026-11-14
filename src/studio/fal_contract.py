"""Contrato do pacote de producao do motor fal.ai.

Duas camadas, de proposito:

* CANONICA (`WorkflowPackage`, `Artifact`): o que o resto do Kiroo conhece. UM video (ja com a narracao embutida, sem
  musica), UMA foto hero e o texto (titulo + legenda). Parser, validador, composer, simulado, fixtures e testes so
  falam este formato.
* EXTERNA: o mapeamento das chaves reais de cada workflow da fal.ai, que vive SOMENTE em
  `profiles/fal/workflow_contract.json` e neste modulo (`parse_result`). O que ainda depende da fixture real (Fase 0)
  fica `A CONFIRMAR` la.

O workflow e UNICO (wf01white, qualquer cenario e plataforma) e recebe 6 inputs (`image_url` + 5 textos montados em
`prompts/production.py`); devolve `video`, `images` (1 foto hero) e `output` (texto com JSON
`{"title","caption"}`). A saida `audio` do display e intermediaria de TTS: ignorada, nunca entregue nem validada.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER = "A CONFIRMAR"
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

    kind: str                       # video | image | audio
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
    # OPCIONAIS (so quando o display do workflow expoe): audio do ElevenLabs e texto falado, para medir a narracao.
    # Nao fazem parte da entrega nem do que o front ve.
    narration_audio: Artifact | None = None
    narration_text: str = ""
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


def placeholders(contract: dict, include_recover: bool = True) -> list[str]:
    """Pendencias do estilo (A CONFIRMAR). Com `include_recover=False` so as que BLOQUEIAM O ENVIO (input, output e
    `pending`); `recover` e `pending_recover` bloqueiam apenas a recuperacao de foto pelo no (ver `recover_pending`)."""
    cfg = contract.get("workflow")
    if cfg is None:
        return ["bloco workflow ausente"]
    out: list[str] = []

    def walk(prefix, v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(f"{prefix}.{k}" if prefix else k, x)
        elif _is_placeholder(v):
            out.append(prefix)
    for key in ("input", "output") + (("recover",) if include_recover else ()):
        walk(key, cfg.get(key))
    extra = ("pending", "pending_recover") if include_recover else ("pending",)
    for key in extra:
        out.extend(f"pendente: {x}" for x in (cfg.get(key) or []))
    return out


def recover_pending(contract: dict) -> list[str]:
    """Pendencias que bloqueiam SO a recuperacao de foto (recover.* e pending_recover). O envio nao depende delas."""
    block = set(placeholders(contract, include_recover=False))
    return [x for x in placeholders(contract) if x not in block]


def workflow_config(contract: dict) -> dict:
    cfg = contract.get("workflow")
    if not isinstance(cfg, dict):
        raise ContractError("contrato sem o bloco `workflow`")
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


def check_input(contract: dict, payload: dict) -> dict:
    """Confere o corpo do submit (montado por prompts.production.build_fal_arguments) contra os campos do contrato: todos
    presentes e nao vazios, nenhum a mais. Devolve o proprio payload."""
    cfg = workflow_config(contract)
    fields = (cfg.get("input") or {}).get("fields") or []
    if not fields or any(_is_placeholder(f) for f in fields):
        raise ContractError("campos de entrada do workflow ainda A CONFIRMAR (Fase 0)")
    missing = [f for f in fields if not isinstance(payload.get(f), str) or not payload[f].strip()]
    extra = [k for k in payload if k not in fields]
    if missing or extra:
        raise ContractError("entrada do workflow fora do contrato: faltam %s, sobram %s" % (missing or "nenhum", extra or "nenhum"))
    return payload


_WS = "\ufeff \t\r\n"                                  # BOM, espacos e quebras de linha ao redor
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")        # cerca markdown, com ou sem o rotulo (json, JSON...)


def parse_text_output(raw) -> tuple[str, str, list[str]]:
    """Saida `output` do workflow -> (titulo, legenda, avisos). O texto traz JSON `{"title","caption"}` (campos a
    mais, como uma `narration` antiga, sao ignorados: o audio ja vem no video). Aceita cerca
    ```json, cerca sem rotulo, espacos ao redor e dict ja decodificado). JSON invalido, vazio ou com campos vazios (o prompt manda nunca devolver vazio, mas o parser segue defensivo
    quando nao identifica o produto): devolve o que houver, com aviso. NUNCA inventa texto."""
    data = raw
    if isinstance(raw, str):
        txt = _FENCE.sub("", raw.strip(_WS)).strip(_WS)
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


def parse_result(result: dict, contract: dict) -> WorkflowPackage:
    """Resultado bruto da fal.ai -> pacote canonico. Nao baixa nada."""
    cfg = workflow_config(contract)
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
    if out_map.get("narration_audio"):
        url = _url_of(get_path(output, out_map["narration_audio"]))
        if url:
            pkg.narration_audio = Artifact(kind="audio", url=url)
    if out_map.get("narration_text"):
        pkg.narration_text = _text_of(get_path(output, out_map["narration_text"]))
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
            "caption": pkg.caption, "narration_audio": _artifact_to_dict(pkg.narration_audio),
            "narration_text": pkg.narration_text, "nodes": pkg.nodes, "warnings": list(pkg.warnings)}


def package_from_dict(d: dict) -> WorkflowPackage:
    return WorkflowPackage(video=_artifact_from_dict(d.get("video")), hero=_artifact_from_dict(d.get("hero")),
                           title=d.get("title") or "", caption=d.get("caption") or "",
                           narration_audio=_artifact_from_dict(d.get("narration_audio")),
                           narration_text=d.get("narration_text") or "", nodes=d.get("nodes") or {},
                           warnings=list(d.get("warnings") or []))
