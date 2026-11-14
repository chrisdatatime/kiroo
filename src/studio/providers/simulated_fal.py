"""Workflow fal.ai SIMULADO: pacote sintetico completo, sem rede e sem custo.

Gera com o FFmpeg (lavfi) um video 9:16, narracao e musica, e 3 JPGs DISTINTOS (um por papel). Serve para desenvolver e
testar a esteira inteira. NAO comprova integracao real nem qualidade. O estado de cada execucao fica em disco
(data/sim_ops), como no simulador do Gemini, e sobrevive a reinicios.

Falhas injetaveis por componente (`FalSimScript`): sem musica, sem video, sem narracao, sem a imagem N, imagem
corrompida, falha de envio, envio incerto, erro ao concluir e recuperacao posterior de uma imagem.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .. import fal_contract
from ..fal_contract import Artifact, WorkflowPackage
from ..ffmpeg import FFmpeg
from .base import OpResult, OpState, PermanentError, TransientError, WorkflowRequest
from .fal import SubmitInfo, UncertainSubmit

SIM_PROVIDER = "simulated"
ROLE_COLORS = {"hero": "0x2F55D4", "lifestyle": "0xE46F5A", "details": "0x3FB8AF"}


@dataclass
class FalSimScript:
    """Roteiro de falhas/decisoes para testes. Listas sao consumidas em ordem."""

    polls_before_done: int = 0
    submit_failures: list[str] = field(default_factory=list)        # "transient" | "permanent" | "uncertain"
    missing: set[str] = field(default_factory=set)                  # video, narration, music, image:hero|lifestyle|details
    corrupt: set[str] = field(default_factory=set)                  # imagens corrompidas: "image:hero", ...
    recoverable: set[str] = field(default_factory=set)              # imagens ausentes que uma busca por no recupera
    error_on_complete: str | None = None                            # texto: o workflow termina com erro
    video_seconds: float = 15.0
    narration_seconds: float = 11.5
    music_seconds: float = 20.0
    video_size: tuple[int, int] = (540, 960)
    description: str = "Produto simulado em ambiente de teste."
    narration_text: str = "Texto de narracao simulado."
    cost_usd: float = 1.0


class _SimOps:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "sim_ops"
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, op_id: str, state: dict) -> None:
        (self.dir / f"{op_id}.json").write_text(json.dumps(state), encoding="utf-8")

    def load(self, op_id: str) -> dict:
        p = self.dir / f"{op_id}.json"
        if not p.exists():
            raise PermanentError(f"operacao simulada desconhecida: {op_id}")
        return json.loads(p.read_text(encoding="utf-8"))


class SimulatedFalWorkflow:
    provider = SIM_PROVIDER
    simulated = True

    def __init__(self, data_dir: Path, ffmpeg: FFmpeg, script: FalSimScript | None = None, estimator=None):
        self.model = "fal-workflow-simulado"
        self.ops = _SimOps(data_dir)
        self.ffmpeg = ffmpeg
        self.script = script or FalSimScript()
        self._estimator = estimator
        self.submit_count = 0
        self.cancelled: list[str] = []
        self.recover_calls = 0

    # ---------------------------------------------------------------- contrato do gerador
    def params(self, request: WorkflowRequest) -> dict:
        return {"style": request.style, "workflow": f"simulado/{request.style}"}

    def estimate_cost(self, request: WorkflowRequest) -> tuple[float, str]:
        if self._estimator is not None:
            cost, src = self._estimator(request.style)
            return cost, f"SIMULADO - custo equivalente estimado; {src}"
        return self.script.cost_usd, "SIMULADO - custo equivalente estimado"

    def _raise_scripted(self) -> None:
        if not self.script.submit_failures:
            return
        kind = self.script.submit_failures.pop(0)
        if kind == "transient":
            raise TransientError("falha transitoria simulada (ex.: 503)")
        if kind == "uncertain":
            raise UncertainSubmit("envio sem resposta (simulado)")
        raise PermanentError("falha permanente simulada (ex.: requisicao recusada)")

    def submit_full(self, request: WorkflowRequest) -> SubmitInfo:
        self._raise_scripted()
        self.submit_count += 1
        op_id = f"sim-fal-{uuid.uuid4().hex[:10]}"
        files = self._render(op_id, request.style)
        self.ops.save(op_id, {"polls_left": self.script.polls_before_done, "style": request.style, "files": files,
                              "error": self.script.error_on_complete, "recoverable": sorted(self.script.recoverable),
                              "description": self.script.description, "narration_text": self.script.narration_text})
        return SubmitInfo(op_id, {"workflow": f"simulado/{request.style}", "style": request.style})

    def submit(self, request: WorkflowRequest) -> str:
        return self.submit_full(request).request_id

    def poll(self, op_id: str, meta: dict | None = None, style: str | None = None) -> OpResult:
        st = self.ops.load(op_id)
        if st["polls_left"] > 0:
            st["polls_left"] -= 1
            self.ops.save(op_id, st)
            return OpResult(OpState.RUNNING)
        if st.get("error"):
            return OpResult(OpState.FAILED, error=st["error"], permanent=True)
        pkg = WorkflowPackage(description=st["description"], narration_text=st["narration_text"],
                              nodes={"sim": {"endpoint": "simulado/no", "request_id": op_id}})
        for kind in ("video", "narration", "music"):
            f = st["files"].get(kind)
            if f:
                setattr(pkg, kind, Artifact(kind=kind, path=Path(f)))
        for role in fal_contract.ROLES:
            f = st["files"].get(f"image:{role}")
            if f and role not in st["recoverable"]:
                pkg.images[role] = Artifact(kind="image", role=role, path=Path(f))
            elif role in st["recoverable"]:
                pkg.images[role] = Artifact(kind="image", role=role, recover={"endpoint": "simulado/no", "request_id": op_id,
                                                                              "path": role})
        if pkg.music is None:
            pkg.warnings.append("workflow nao devolveu trilha: o video sai so com a narracao")
        return OpResult(OpState.SUCCEEDED, package=pkg, confirmed_cost_usd=0.0,
                        usage={"request_id": op_id, "nodes": pkg.nodes})

    def cancel(self, op_id: str, meta: dict | None = None) -> None:
        self.cancelled.append(op_id)

    def fetch(self, artifact: Artifact) -> bytes:
        if artifact.data is not None:
            return artifact.data
        if artifact.path is not None:
            return Path(artifact.path).read_bytes()
        raise PermanentError("artefato simulado sem origem")

    def recover_artifact(self, artifact: Artifact) -> Artifact | None:
        """Recupera so este arquivo pelo no (simulado: so se o roteiro de falhas liberou)."""
        self.recover_calls += 1
        rec = artifact.recover or {}
        st = self.ops.load(rec["request_id"])
        role = artifact.role
        f = st["files"].get(f"image:{role}")
        if role in st["recoverable"] and f and Path(f).exists():
            return Artifact(kind="image", role=role, path=Path(f))
        return None

    def reconcile_cost(self, request_ids: list[str]) -> float | None:
        return None

    # ---------------------------------------------------------------- geracao sintetica (FFmpeg)
    def _render(self, op_id: str, style: str) -> dict:
        d = self.ops.dir / op_id
        d.mkdir(parents=True, exist_ok=True)
        s, w, h = self.script, *self.script.video_size
        out: dict[str, str] = {}
        miss = set(s.missing)
        # ficheiros que existem mesmo "ausentes" no pacote recuperavel ficam gravados para a busca por no
        if "video" not in miss:
            p = d / "video.mp4"
            self.ffmpeg.run(["-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=30:duration={s.video_seconds}",
                             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", str(p)])
            out["video"] = str(p)
        if "narration" not in miss:
            p = d / "narration.wav"
            expr = "0.45*sin(2*PI*190*t)*(0.55+0.45*sin(2*PI*3.3*t))"
            self.ffmpeg.run(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={s.narration_seconds}", "-ac", "1", str(p)])
            out["narration"] = str(p)
        if "music" not in miss:
            p = d / "music.wav"
            expr = "0.5*(sin(2*PI*261.6*t)+sin(2*PI*329.6*t)+sin(2*PI*392*t))/3*(0.8+0.2*sin(2*PI*2*t))"
            self.ffmpeg.run(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={s.music_seconds}", "-ac", "2", str(p)])
            out["music"] = str(p)
        for role in fal_contract.ROLES:
            key = f"image:{role}"
            p = d / f"{role}.jpg"
            self.ffmpeg.run(["-f", "lavfi", "-i", f"color=c={ROLE_COLORS[role]}:s=720x1280", "-frames:v", "1",
                             "-vf", "format=yuvj420p", "-q:v", "3", str(p)])
            if key in s.corrupt:
                p.write_bytes(p.read_bytes()[:-40] if p.stat().st_size > 400 else b"\xff\xd8\xff\x00")
            if key in miss and role not in s.recoverable:
                p.unlink()
                continue
            out[key] = str(p)                     # recuperavel: existe no no, mas nao veio no pacote (ver poll)
        return out
