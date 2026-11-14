"""Preparo final do video do motor fal.ai com o FFmpeg do Kiroo.

O workflow ja entrega UM MP4 vertical com a narracao embutida e sem musica. Aqui nao ha mixagem: so
validacao, janela de duracao e capa.

Regras (decididas com o dono do produto):
* Validacao com ffprobe: precisa ter stream de VIDEO e de AUDIO. Sem audio (ou sem video) = falha tecnica, sem debito.
* Janela de duracao 14 a 16 s (alvo T = 15 s):
  - dentro da janela: copia sem reencode (`-c copy`);
  - mais longo que a janela: corta em T com fade-out (video e audio) e REENCODA;
  - mais curto que a janela: estende com o ultimo quadro (e silencio no audio) ate T, no maximo 2 s, e reencoda;
    alem disso, revisao do administrador.
* Saida: 9:16, com audio, duracao na janela. Capa (`cover.jpg`) extraida do video final.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..ffmpeg import FFmpeg


class ComposeNeedsReview(Exception):
    """O video nao pode ser entregue automaticamente com qualidade: pausa para o administrador. `code` e estavel."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class SourceInvalid(Exception):
    """O arquivo do workflow nao serve (ilegivel, sem stream de video ou sem audio): falha tecnica, sem debito."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ComposeConfig:
    target_s: float = 15.0
    min_s: float = 14.0
    max_s: float = 16.0
    extend_max_s: float = 2.0
    fade_out_s: float = 0.5
    aspect_tol: float = 0.03
    crf: int = 18
    cover_time_s: float = 13.0

    @classmethod
    def from_env(cls, env=None) -> "ComposeConfig":
        e = os.environ if env is None else env

        def f(name, default):
            try:
                v = float(e.get(name) or default)
            except ValueError:
                return default
            return v if v > 0 else default
        return cls(target_s=f("STUDIO_FAL_TARGET_S", 15.0), min_s=f("STUDIO_FAL_MIN_S", 14.0),
                   max_s=f("STUDIO_FAL_MAX_S", 16.0))


@dataclass
class ComposePlan:
    video_action: str            # copy | cut | extend
    final_s: float
    pad_s: float                 # segundos de ultimo quadro acrescentados (extend)
    notes: list[str] = field(default_factory=list)


@dataclass
class ComposeReport:
    plan: ComposePlan
    out: Path
    duration_s: float
    checks: dict
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- validacao da origem
def check_source(ff: FFmpeg, path: Path) -> dict:
    """ffprobe do video do workflow: precisa ter stream de video E de audio. Levanta SourceInvalid."""
    try:
        info = ff.probe(path)
    except Exception as exc:  # noqa: BLE001 — ffprobe recusou o arquivo
        raise SourceInvalid("video_unreadable", f"video ilegivel pelo ffprobe: {exc}") from None
    if not info["video_codec"] or not info["width"] or not info["height"]:
        raise SourceInvalid("no_video_stream", "o arquivo do workflow nao tem stream de video")
    if not info["has_audio"]:
        raise SourceInvalid("no_audio_stream", "o video do workflow veio sem audio (a narracao deveria estar embutida)")
    if info["duration_s"] <= 0:
        raise SourceInvalid("empty_media", "video com duracao invalida")
    return info


# --------------------------------------------------------------------- planejamento (puro, sem FFmpeg)
def plan_composition(video_s: float, width: int, height: int, cfg: ComposeConfig) -> ComposePlan:
    if not width or not height or abs(width / height - 9 / 16) > cfg.aspect_tol:
        raise ComposeNeedsReview("video_not_vertical", f"o video nao e vertical 9:16 ({width}x{height})")
    if video_s <= 0:
        raise ComposeNeedsReview("empty_media", "video com duracao invalida")
    T = cfg.target_s
    if video_s > cfg.max_s:
        return ComposePlan("cut", T, 0.0, [f"video de {video_s:.2f}s cortado em {T:g}s com fade-out (reencode)"])
    if video_s < cfg.min_s:
        pad = T - video_s
        if pad > cfg.extend_max_s + 1e-9:
            raise ComposeNeedsReview("video_too_short", f"video de {video_s:.2f}s curto demais: estender {pad:.2f}s passa "
                                                         f"do limite de {cfg.extend_max_s:g}s")
        return ComposePlan("extend", T, round(pad, 3),
                           [f"video de {video_s:.2f}s estendido {pad:.2f}s com o ultimo quadro (reencode)"])
    return ComposePlan("copy", round(video_s, 3), 0.0)


# --------------------------------------------------------------------- composicao
def compose(ff: FFmpeg, video: Path, out: Path, workdir: Path, cfg: ComposeConfig | None = None) -> ComposeReport:
    """Gera `out` (MP4 9:16, com audio, duracao na janela). Levanta SourceInvalid (sem video/audio: falha tecnica) ou
    ComposeNeedsReview (nao da para entregar sozinho com qualidade)."""
    cfg = cfg or ComposeConfig.from_env()
    workdir.mkdir(parents=True, exist_ok=True)
    src = check_source(ff, video)
    plan = plan_composition(src["duration_s"], src["width"], src["height"], cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    enc = ["-c:v", "libx264", "-preset", ff.preset, "-crf", str(cfg.crf), "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-b:a", "192k", "-movflags", "+faststart"]
    maps = ["-map", "0:v:0", "-map", "0:a:0"]
    if plan.video_action == "copy":
        ff.run(["-i", str(video), *maps, "-c", "copy", "-movflags", "+faststart", str(out)])
    elif plan.video_action == "cut":
        fo = cfg.fade_out_s
        st = f"{max(plan.final_s - fo, 0):.3f}"
        ff.run(["-i", str(video), *maps, "-t", f"{plan.final_s:.3f}",
                "-vf", f"fade=t=out:st={st}:d={fo:.2f},format=yuv420p", "-af", f"afade=t=out:st={st}:d={fo:.2f}",
                *enc, str(out)])
    else:
        ff.run(["-i", str(video), *maps, "-t", f"{plan.final_s:.3f}",
                "-vf", f"tpad=stop_mode=clone:stop_duration={plan.pad_s:.3f},format=yuv420p",
                "-af", f"apad=whole_dur={plan.final_s:.3f}", *enc, str(out)])
    checks = validate_output(ff, out, cfg)
    return ComposeReport(plan=plan, out=out, duration_s=checks["duration_s"], checks=checks, warnings=list(plan.notes))


def validate_output(ff: FFmpeg, path: Path, cfg: ComposeConfig) -> dict:
    """Duracao na janela, 9:16 e audio presente. Levanta ComposeNeedsReview se falhar."""
    info = ff.probe(path)
    problems = []
    if not (cfg.min_s - 0.1 <= info["duration_s"] <= cfg.max_s + 0.1):
        problems.append(f"duracao {info['duration_s']:.2f}s fora da janela de {cfg.min_s:g} a {cfg.max_s:g}s")
    if not info["width"] or abs(info["width"] / info["height"] - 9 / 16) > cfg.aspect_tol:
        problems.append(f"proporcao {info['width']}x{info['height']} nao e 9:16")
    if not info["has_audio"]:
        problems.append("sem audio")
    if problems:
        raise ComposeNeedsReview("output_invalid", "; ".join(problems))
    return {"duration_s": info["duration_s"], "width": info["width"], "height": info["height"], "has_audio": True}


def make_cover(ff: FFmpeg, final: Path, out: Path, cfg: ComposeConfig | None = None) -> Path:
    cfg = cfg or ComposeConfig()
    dur = ff.probe(final)["duration_s"]
    return ff.extract_frame(final, min(cfg.cover_time_s, max(dur - 0.2, 0)), out)


# --------------------------------------------------------------------- legenda
def build_caption(title: str, caption: str, fmt: dict | None) -> tuple[str, list[str]]:
    """caption.txt: titulo + legenda DO WORKFLOW (nunca inventadas) e, se o formato tiver, a identificacao de publicidade
    e as hashtags. Sem titulo e sem legenda: so a identificacao, com aviso."""
    title, caption = (title or "").strip(), (caption or "").strip()
    warnings: list[str] = []
    lines = [x for x in (title, caption) if x]
    if not lines:
        warnings.append("sem titulo e sem legenda do workflow: caption.txt so tem a identificacao de publicidade")
    else:
        warnings.append("titulo e legenda vem do modelo de visao do workflow e nao foram verificados: confira antes de publicar")
    body = "\n\n".join(lines)
    if fmt:
        tail = "\n".join([fmt["disclosure"]["caption_text"], " ".join(fmt["caption"]["hashtags"])])
        text = (body + "\n\n" if body else "") + tail
        if len(text) > fmt["caption"]["max_chars"]:
            warnings.append("legenda acima do limite configurado")
        return text, warnings
    return body, warnings
