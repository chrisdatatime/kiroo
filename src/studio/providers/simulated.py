"""Provedores SIMULADOS — claramente identificados e sem custo real.

Servem para desenvolver e testar a esteira inteira. Os arquivos gerados são
placeholders (imagem listrada / clipe com zoom) e NÃO comprovam integração real.
O estado das operações fica em disco (data/sim_ops) para simular um serviço remoto
que sobrevive a reinícios do processo.
"""

from __future__ import annotations

import hashlib
import json
import struct
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from .. import pricing
from ..ffmpeg import FFmpeg
from ..models import ReviewDecision, ReviewResult, SceneSpec, Script
from .base import FactsRequest, ImageRequest, OpResult, OpState, PermanentError, PlanningContext, TransientError, VideoRequest

SIM_PROVIDER = "simulated"


def placeholder_png(seed: str, width: int = 540, height: int = 960) -> bytes:
    """PNG listrado determinístico (stdlib), cor derivada do seed."""
    h = hashlib.sha256(seed.encode()).digest()
    base = (60 + h[0] % 150, 60 + h[1] % 150, 60 + h[2] % 150)
    alt = tuple(min(255, c + 45) for c in base)
    rows = bytearray()
    band_top, band_bottom = int(height * 0.45), int(height * 0.55)
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if band_top <= y < band_bottom:
                px = (245, 245, 245)
            else:
                px = alt if ((x + y) // 40) % 2 else base
            rows.extend(px)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    text = chunk(b"tEXt", b"Comment\x00SIMULADO - placeholder sem valor visual")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + text + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")


@dataclass
class SimulationScript:
    """Roteiro de falhas/decisões para testes. Listas são consumidas em ordem."""

    image_submit_failures: list[str] = field(default_factory=list)  # "transient" | "permanent"
    video_submit_failures: list[str] = field(default_factory=list)
    video_polls_before_done: int = 1
    video_with_audio: bool = False
    # Além de ReviewDecision, aceita "aesthetic": reprovado pelo modelo SÓ por estética (mão) → vira aviso.
    image_reviews: list[ReviewDecision] = field(default_factory=list)
    video_reviews: list[ReviewDecision] = field(default_factory=list)


class _SimOps:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "sim_ops"
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, op_id: str, state: dict) -> None:
        (self.dir / f"{op_id}.json").write_text(json.dumps(state), encoding="utf-8")

    def load(self, op_id: str) -> dict:
        p = self.dir / f"{op_id}.json"
        if not p.exists():
            raise PermanentError(f"operação simulada desconhecida: {op_id}")
        return json.loads(p.read_text(encoding="utf-8"))


def _raise_scripted(queue: list[str]) -> None:
    if queue:
        kind = queue.pop(0)
        if kind == "transient":
            raise TransientError("falha transitória simulada (ex.: 503)")
        raise PermanentError("falha permanente simulada (ex.: requisição recusada)")


class SimulatedImageGenerator:
    provider = SIM_PROVIDER
    simulated = True

    def __init__(self, data_dir: Path, model: str, script: SimulationScript | None = None):
        self.model = model
        self.ops = _SimOps(data_dir)
        self.script = script or SimulationScript()
        self.submit_count = 0

    def params(self, request: ImageRequest) -> dict:
        return {"aspect_ratio": request.aspect_ratio, "image_size": request.image_size}

    def estimate_cost(self, request: ImageRequest) -> tuple[float, str]:
        cost, src = pricing.image_cost(self.model, request.image_size, len(request.reference_images))
        return cost, f"SIMULADO — custo equivalente estimado; {src}"

    def submit(self, request: ImageRequest) -> str:
        _raise_scripted(self.script.image_submit_failures)
        self.submit_count += 1
        op_id = f"sim-img-{uuid.uuid4().hex[:10]}"
        out = self.ops.dir / f"{op_id}.png"
        out.write_bytes(placeholder_png(request.prompt + op_id))
        self.ops.save(op_id, {"status": "done", "file": str(out)})
        return op_id

    def poll(self, op_id: str) -> OpResult:
        state = self.ops.load(op_id)
        return OpResult(OpState.SUCCEEDED, data=Path(state["file"]).read_bytes(), mime_type="image/png",
                        confirmed_cost_usd=0.0)


class SimulatedVideoGenerator:
    provider = SIM_PROVIDER
    simulated = True

    def __init__(self, data_dir: Path, model: str, ffmpeg: FFmpeg, script: SimulationScript | None = None):
        self.model = model
        self.ops = _SimOps(data_dir)
        self.ffmpeg = ffmpeg
        self.script = script or SimulationScript()
        self.submit_count = 0

    def params(self, request: VideoRequest) -> dict:
        return {"aspect_ratio": request.aspect_ratio, "resolution": request.resolution,
                "target_duration_s": request.target_duration_s}

    def estimate_cost(self, request: VideoRequest) -> tuple[float, str]:
        cost, src = pricing.video_cost(self.model, request.resolution)
        return cost, f"SIMULADO — custo equivalente estimado; {src}"

    def submit(self, request: VideoRequest) -> str:
        _raise_scripted(self.script.video_submit_failures)
        self.submit_count += 1
        op_id = f"sim-vid-{uuid.uuid4().hex[:10]}"
        self.ops.save(op_id, {
            "status": "running",
            "polls_left": self.script.video_polls_before_done,
            "start_image": str(request.start_image),
            "seconds": max(request.target_duration_s + 1.0, 4.0),
            "audio": self.script.video_with_audio,
        })
        return op_id

    def poll(self, op_id: str) -> OpResult:
        state = self.ops.load(op_id)
        if state["status"] == "running" and state["polls_left"] > 0:
            state["polls_left"] -= 1
            self.ops.save(op_id, state)
            return OpResult(OpState.RUNNING)
        out = self.ops.dir / f"{op_id}.mp4"
        if not out.exists():
            self.ffmpeg.still_to_clip(Path(state["start_image"]), out, state["seconds"], 540, 960, tone=state["audio"])
            state["status"] = "done"
            self.ops.save(op_id, state)
        return OpResult(OpState.SUCCEEDED, data=out.read_bytes(), mime_type="video/mp4", confirmed_cost_usd=0.0)


class SimulatedPlanner:
    provider = SIM_PROVIDER
    model = "template"
    simulated = True

    def test_task(self, role: str, prompt: str) -> tuple[str, dict]:
        return "SIMULADO: nenhum modelo foi chamado. Este seria o pedido enviado:\n" + prompt[:900], {}

    def describe_product(self, req: FactsRequest) -> tuple[dict, dict]:
        """SIMULADO: nenhuma foto é analisada; a ficha repete só o que o operador digitou."""
        from ..agents.fidelity import looks_complex
        attrs = req.visual_attributes or {}
        complex_ = looks_complex(req.name, "", attrs)
        return ({"summary_en": "", "colors": [v for k, v in attrs.items() if "cor" in k.lower() or "color" in k.lower()],
                 "must_keep": [f"{k}: {v}" for k, v in attrs.items()][:10], "asymmetric": complex_,
                 "complexity": "complex" if complex_ else "simple"},
                {"note": "SIMULADO: ficha técnica sem análise visual (só atributos digitados)"})

    def refine_script(self, ctx: PlanningContext) -> tuple[Script, dict]:
        script = ctx.draft.model_copy(update={"planner": "simulated:template (sem IA)", "simulated": True})
        return script, {"note": "SIMULADO: roteiro = template do formato, sem refinamento por IA"}


class SimulatedReviewer:
    provider = SIM_PROVIDER
    model = "none"
    simulated = True

    def __init__(self, script: SimulationScript | None = None):
        self.script = script or SimulationScript()

    def _result(self, queue: list[ReviewDecision], method: str) -> ReviewResult:
        decision = queue.pop(0) if queue else ReviewDecision.INCONCLUSIVE
        issues, fix, critical, warnings = [], None, [], []
        checks = {"produto": "desconhecido", "maos": "desconhecido", "cenario": "desconhecido", "enquadramento": "desconhecido"}
        if decision == "aesthetic":   # só a mão saiu errada: o produto está certo
            decision = ReviewDecision.REJECTED
            warnings = ["(simulado) dedo a mais na mão esquerda"]
            checks.update(produto="ok", maos="problema")
        elif decision == ReviewDecision.REJECTED:
            issues = ["(simulado) problema fictício para teste de correção"]
            critical = list(issues)
            fix = "(simulado) manter tampa e alça idênticas às fotos oficiais"
        return ReviewResult(
            decision=decision,
            checks=checks,
            issues=issues, critical_issues=critical, warnings=warnings,
            suggested_fix=fix,
            method=f"SIMULADO — nenhuma análise visual foi feita. {method}",
            reviewer="simulated",
            simulated=True,
        )

    def review_image(self, spec: SceneSpec, image: Path, references: list[Path]) -> tuple[ReviewResult, dict]:
        return self._result(self.script.image_reviews, f"{len(references)} referências seriam comparadas."), {}

    def review_video(self, spec, frames, approved_image, audio, probe) -> tuple[ReviewResult, dict]:
        result = self._result(self.script.video_reviews, f"{len(frames)} quadros amostrados.")
        return result, {}
