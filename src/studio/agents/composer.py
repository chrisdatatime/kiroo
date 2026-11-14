"""Composicao final do pacote do motor fal.ai com o FFmpeg do Kiroo (FFmpeg Compose/Merge da fal.ai deram 403).

Recebe video, narracao e (opcionalmente) musica como arquivos separados e entrega UM MP4 vertical de ~15 s.

Regras (decididas com o dono do produto):
* Duracao-alvo T = 15 s, janela aceitavel 14 a 16 s, tolerancia final de T +- 0,3 s.
  - video mais longo que T + 0,3 s: corta em T com fade-out e REENCODA (nunca `-c:v copy` quando ha corte);
  - video mais curto que T - 0,3 s: estende com o ultimo quadro (ate 2 s) e reencoda; alem disso, revisao do admin;
  - dentro de T +- 0,3 s: `-c:v copy` (sem perda de qualidade).
* Narracao: NUNCA corta palavras nem frases. Se nao cabe no espaco (T - offset - folga), tenta `atempo` com teto
  (padrao 1,08, tom preservado). Se ainda nao cabe: revisao do admin, sem entrega automatica.
* Musica: em loop, cortada em T, com fades e ducking por `sidechaincompress` (a narracao e a chave). A trilha fica pelo
  menos ~10 dB abaixo da fala; se nao, o ganho e reduzido; se ainda nao, revisao do admin.
* Saida: 9:16, audio presente, nivel medio na faixa, loudness -14 LUFS.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..ffmpeg import FFmpeg


class ComposeNeedsReview(Exception):
    """O pacote nao pode ser entregue automaticamente com qualidade: pausa para o administrador. `code` e estavel."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ComposeConfig:
    target_s: float = 15.0
    min_s: float = 14.0
    max_s: float = 16.0
    tolerance_s: float = 0.3
    extend_max_s: float = 2.0
    narration_offset_s: float = 0.3
    tail_guard_s: float = 0.5
    atempo_max: float = 1.08
    fade_out_s: float = 0.5
    music_gain_db: float = -8.0
    duck_min_db: float = 10.0
    loudness_lufs: float = -14.0
    aspect_tol: float = 0.03
    level_range_db: tuple[float, float] = (-30.0, -8.0)
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
                   max_s=f("STUDIO_FAL_MAX_S", 16.0), atempo_max=max(f("STUDIO_FAL_ATEMPO_MAX", 1.08), 1.0))


@dataclass
class ComposePlan:
    video_action: str            # copy | cut | extend
    final_s: float
    pad_s: float                 # segundos de ultimo quadro acrescentados (extend)
    atempo: float                # 1.0 = sem ajuste
    narration_s: float           # duracao efetiva da narracao depois do atempo
    notes: list[str] = field(default_factory=list)


@dataclass
class ComposeReport:
    plan: ComposePlan
    out: Path
    duration_s: float
    music: bool
    duck_db: float | None
    gain_db: float | None
    checks: dict
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- planejamento (puro, sem FFmpeg)
def plan_composition(video_s: float, width: int, height: int, narration_s: float, cfg: ComposeConfig) -> ComposePlan:
    if not width or not height or abs(width / height - 9 / 16) > cfg.aspect_tol:
        raise ComposeNeedsReview("video_not_vertical", f"o video nao e vertical 9:16 ({width}x{height})")
    if video_s <= 0 or narration_s <= 0:
        raise ComposeNeedsReview("empty_media", "video ou narracao com duracao invalida")
    T, tol = cfg.target_s, cfg.tolerance_s
    notes: list[str] = []
    if video_s > T + tol:
        action, final, pad = "cut", T, 0.0
        notes.append(f"video de {video_s:.2f}s cortado em {T:g}s com fade-out (reencode)")
    elif video_s < T - tol:
        pad = T - video_s
        if pad > cfg.extend_max_s:
            raise ComposeNeedsReview("video_too_short", f"video de {video_s:.2f}s curto demais: estender {pad:.2f}s passa "
                                                         f"do limite de {cfg.extend_max_s:g}s")
        action, final = "extend", T
        notes.append(f"video de {video_s:.2f}s estendido {pad:.2f}s com o ultimo quadro (reencode)")
    else:
        action, final, pad = "copy", video_s, 0.0
    avail = final - cfg.narration_offset_s - cfg.tail_guard_s
    atempo, eff = 1.0, narration_s
    if narration_s > avail:
        ratio = narration_s / avail
        if ratio > cfg.atempo_max + 1e-9:
            raise ComposeNeedsReview("narration_too_long", f"a narracao ({narration_s:.2f}s) nao cabe em {avail:.2f}s nem com "
                                                           f"velocidade x{cfg.atempo_max:g} (precisaria x{ratio:.3f}); nada foi cortado")
        atempo = round(ratio * 1.002, 4)                     # pequena folga contra arredondamento
        eff = narration_s / atempo
        notes.append(f"narracao acelerada x{atempo:.3f} para caber (sem cortar palavras)")
    return ComposePlan(action, round(final, 3), round(pad, 3), atempo, round(eff, 3), notes)


# --------------------------------------------------------------------- medicao
_MEAN = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf) dB")


def segment_mean_db(ff: FFmpeg, path: Path, start: float, dur: float) -> float | None:
    proc = ff.run(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                  loglevel="info")
    m = _MEAN.search(proc.stderr)
    if not m:
        return None
    return float("-inf") if m.group(1) == "-inf" else float(m.group(1))


# --------------------------------------------------------------------- composicao
def _video_part(ff: FFmpeg, video: Path, plan: ComposePlan, cfg: ComposeConfig, workdir: Path) -> Path:
    if plan.video_action == "copy":
        return video
    out = workdir / "video_part.mp4"
    if plan.video_action == "cut":
        vf = f"fade=t=out:st={max(plan.final_s - cfg.fade_out_s, 0):.3f}:d={cfg.fade_out_s:.2f}"
        t = plan.final_s
    else:
        vf = f"tpad=stop_mode=clone:stop_duration={plan.pad_s:.3f}"
        t = plan.final_s
    ff.run(["-i", str(video), "-vf", vf + ",format=yuv420p", "-t", f"{t:.3f}", "-an", "-c:v", "libx264",
            "-preset", ff.preset, "-crf", str(cfg.crf), "-pix_fmt", "yuv420p", str(out)])
    return out


def _narration_track(ff: FFmpeg, narration: Path, plan: ComposePlan, cfg: ComposeConfig, out: Path) -> Path:
    ms = int(round(cfg.narration_offset_s * 1000))
    tempo = f"atempo={plan.atempo:.4f}," if plan.atempo != 1.0 else ""
    af = (f"aformat=sample_rates=48000:channel_layouts=stereo,{tempo}adelay={ms}|{ms},apad,"
          f"atrim=duration={plan.final_s:.3f},asetpts=PTS-STARTPTS")
    ff.run(["-i", str(narration), "-af", af, "-ar", "48000", "-ac", "2", str(out)])
    return out


def _music_ducked(ff: FFmpeg, music: Path, narr_track: Path, plan: ComposePlan, cfg: ComposeConfig, gain_db: float,
                  out: Path, workdir: Path) -> Path:
    T = plan.final_s
    fo = min(1.5, T / 4)
    graph = workdir / "duck.graph.txt"
    graph.write_text(
        f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=duration={T:.3f},asetpts=PTS-STARTPTS,"
        f"volume={gain_db:.1f}dB,afade=t=in:d=0.5,afade=t=out:st={max(T - fo, 0):.3f}:d={fo:.2f}[m];"
        f"[m][1:a]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=350:makeup=1[d]", encoding="utf-8")
    ff.run(["-stream_loop", "-1", "-i", str(music), "-i", str(narr_track), "-/filter_complex", str(graph.resolve()),
            "-map", "[d]", "-t", f"{T:.3f}", "-ar", "48000", str(out)])
    return out


def compose(ff: FFmpeg, video: Path, narration: Path, music: Path | None, out: Path, workdir: Path,
            cfg: ComposeConfig | None = None) -> ComposeReport:
    """Monta `out` (MP4 9:16 ~T s). Levanta ComposeNeedsReview quando nao da para entregar sozinho com qualidade."""
    cfg = cfg or ComposeConfig.from_env()
    workdir.mkdir(parents=True, exist_ok=True)
    vp, np_ = ff.probe(video), ff.probe(narration)
    plan = plan_composition(vp["duration_s"], vp["width"] or 0, vp["height"] or 0, np_["duration_s"], cfg)
    v = _video_part(ff, video, plan, cfg, workdir)
    narr = _narration_track(ff, narration, plan, cfg, workdir / "narration_track.wav")
    speech = (cfg.narration_offset_s, max(plan.narration_s, 0.5))
    warnings = list(plan.notes)
    duck_db = gain_db = None
    labels = ["[0:a]"]
    args = ["-i", str(narr)]
    if music is not None:
        gain_db = cfg.music_gain_db
        narr_db = segment_mean_db(ff, narr, *speech)
        for attempt in range(3):
            ducked = _music_ducked(ff, music, narr, plan, cfg, gain_db, workdir / "music_ducked.wav", workdir)
            mus_db = segment_mean_db(ff, ducked, *speech)
            duck_db = (narr_db - mus_db) if (narr_db is not None and mus_db is not None) else None
            if duck_db is None or duck_db >= cfg.duck_min_db:
                break
            gain_db -= (cfg.duck_min_db - duck_db) + 1.0
        if duck_db is not None and duck_db < cfg.duck_min_db:
            raise ComposeNeedsReview("music_too_loud", f"a trilha ficou so {duck_db:.1f} dB abaixo da narracao "
                                                       f"(minimo {cfg.duck_min_db:g} dB)")
        if gain_db != cfg.music_gain_db:
            warnings.append(f"ganho da trilha reduzido para {gain_db:.1f} dB para ficar abaixo da fala")
        args += ["-i", str(ducked)]
        labels.append("[1:a]")
    mix = workdir / "mix.m4a"
    graph = workdir / "mix.graph.txt"
    graph.write_text("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                     f"loudnorm=I={cfg.loudness_lufs:.1f}:TP=-1.5:LRA=11,alimiter=limit=0.89,"
                     f"atrim=duration={plan.final_s:.3f},aresample=48000[aout]", encoding="utf-8")
    ff.run([*args, "-/filter_complex", str(graph.resolve()), "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", str(mix)])
    out.parent.mkdir(parents=True, exist_ok=True)
    ff.run(["-i", str(v), "-i", str(mix), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy",
            "-t", f"{plan.final_s:.3f}", "-movflags", "+faststart", str(out)])
    checks = validate_output(ff, out, cfg)
    return ComposeReport(plan=plan, out=out, duration_s=checks["duration_s"], music=music is not None, duck_db=duck_db,
                         gain_db=gain_db, checks=checks, warnings=warnings)


def validate_output(ff: FFmpeg, path: Path, cfg: ComposeConfig) -> dict:
    """Duracao T +- tolerancia, 9:16, audio presente e nivel medio na faixa. Levanta ComposeNeedsReview se falhar."""
    info = ff.probe(path)
    lv = ff.audio_levels(path)
    problems = []
    if abs(info["duration_s"] - cfg.target_s) > cfg.tolerance_s + 0.05:
        problems.append(f"duracao {info['duration_s']:.2f}s fora de {cfg.target_s:g}s +-{cfg.tolerance_s:g}s")
    if not info["width"] or abs(info["width"] / info["height"] - 9 / 16) > cfg.aspect_tol:
        problems.append(f"proporcao {info['width']}x{info['height']} nao e 9:16")
    if not info["has_audio"]:
        problems.append("sem audio")
    mean = lv.get("mean_volume_db")
    if mean is None or not (cfg.level_range_db[0] <= mean <= cfg.level_range_db[1]):
        problems.append(f"nivel medio de audio {mean} dB fora de {cfg.level_range_db}")
    if problems:
        raise ComposeNeedsReview("output_invalid", "; ".join(problems))
    return {"duration_s": info["duration_s"], "width": info["width"], "height": info["height"],
            "mean_volume_db": mean, "has_audio": True}


def make_cover(ff: FFmpeg, final: Path, out: Path, cfg: ComposeConfig | None = None) -> Path:
    cfg = cfg or ComposeConfig()
    dur = ff.probe(final)["duration_s"]
    return ff.extract_frame(final, min(cfg.cover_time_s, max(dur - 0.2, 0)), out)


# --------------------------------------------------------------------- legenda
def build_caption(name: str, description: str, fmt: dict | None) -> tuple[str, list[str]]:
    """Legenda: o nome do produto (se houver) ou a descricao vinda do workflow quando o nome esta vazio."""
    name, description = (name or "").strip(), (description or "").strip()
    warnings: list[str] = []
    lines = [name or description.split("\n", 1)[0][:120] or "Produto"]
    if name and description:
        lines += ["", description]
    if description:
        warnings.append("a descricao vem do modelo de visao do workflow e nao foi verificada: confira antes de publicar")
    elif not name:
        warnings.append("sem nome nem descricao: legenda minima")
    if fmt:
        lines += ["", fmt["disclosure"]["caption_text"], " ".join(fmt["caption"]["hashtags"])]
        text = "\n".join(lines)
        if len(text) > fmt["caption"]["max_chars"]:
            warnings.append("legenda acima do limite configurado")
        return text, warnings
    return "\n".join(lines), warnings
