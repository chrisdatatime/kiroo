"""Revisão visual: checagens técnicas determinísticas + avaliação do revisor (IA ou simulado).

Estratégia de vídeo: N quadros no centro de N janelas iguais + último quadro útil,
comparados com a foto aprovada; áudio medido com volumedetect. Falhas técnicas
(proporção, duração) reprovam independentemente da opinião do modelo.
"""

from __future__ import annotations

from pathlib import Path

from ..ffmpeg import FFmpeg
from ..models import ReviewDecision, ReviewResult, SceneSpec
from ..providers.base import Reviewer
from .fidelity import apply_severity

VIDEO_SAMPLE_FRAMES = 6
ASPECT_TOLERANCE = 0.03
AUDIBLE_DB = -50.0


def _aspect_ok(width: int | None, height: int | None, aspect: str = "9:16") -> bool:
    if not width or not height:
        return False
    a, b = (int(x) for x in aspect.split(":"))
    return abs(width / height - a / b) <= ASPECT_TOLERANCE


def _merge(model_result: ReviewResult, hard_issues: list[str], notes: list[str], extra_checks: dict) -> ReviewResult:
    """Falhas técnicas e de PRODUTO bloqueiam; estética (mãos, luz) vira aviso (agents/fidelity.apply_severity)."""
    result = model_result.model_copy(deep=True)
    result.checks.update(extra_checks)
    result = apply_severity(result, hard_issues)
    if hard_issues:
        result.issues = hard_issues + [i for i in result.issues if i not in hard_issues]
    result.issues += notes
    return result


def review_image(reviewer: Reviewer, ffmpeg: FFmpeg, spec: SceneSpec, image: Path, references: list[Path],
                 aspect: str) -> tuple[ReviewResult, dict]:
    hard, checks = [], {}
    if ffmpeg.available:
        info = ffmpeg.probe(image)
        ok = _aspect_ok(info["width"], info["height"], aspect)
        checks["proporcao"] = "ok" if ok else "problema"
        if not ok:
            hard.append(f"proporção {info['width']}x{info['height']} diferente de {aspect}")
    else:
        checks["proporcao"] = "desconhecido"
    result, meta = reviewer.review_image(spec, image, references)
    return _merge(result, hard, [], checks), meta


def review_video(reviewer: Reviewer, ffmpeg: FFmpeg, spec: SceneSpec, video: Path, approved_image: Path,
                 frames_dir: Path, aspect: str) -> tuple[ReviewResult, dict]:
    probe = ffmpeg.probe(video)
    audio = ffmpeg.audio_levels(video)
    hard, notes, checks = [], [], {}
    checks["proporcao"] = "ok" if _aspect_ok(probe["width"], probe["height"], aspect) else "problema"
    if checks["proporcao"] == "problema":
        hard.append(f"proporção {probe['width']}x{probe['height']} diferente de {aspect}")
    if probe["duration_s"] + 0.05 < spec.target_duration_s:
        checks["duracao"] = "problema"
        hard.append(f"take de {probe['duration_s']:.2f}s menor que a duração útil {spec.target_duration_s:.1f}s")
    else:
        checks["duracao"] = "ok"
    if audio["has_audio"] and audio["max_volume_db"] is not None and audio["max_volume_db"] > AUDIBLE_DB:
        checks["audio"] = "problema"
        notes.append(f"áudio audível no take (pico {audio['max_volume_db']:.1f} dB). Será descartado na montagem; "
                     "confira se há fala/narração indevida.")
    else:
        checks["audio"] = "ok"
    frames = ffmpeg.sample_frames(video, VIDEO_SAMPLE_FRAMES, frames_dir)
    result, meta = reviewer.review_video(spec, frames, approved_image, audio, probe)
    meta = {**meta, "probe": probe, "audio": audio, "frames": [(t, str(p)) for t, p in frames]}
    return _merge(result, hard, notes, checks), meta
