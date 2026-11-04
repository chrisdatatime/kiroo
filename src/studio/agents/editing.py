"""Edição e entrega: plano de corte validado, montagem FFmpeg, capa e legenda.

Editor (Beto) com estilos: transições entre cenas, cortes no tempo da trilha, efeitos sonoros (whoosh na transição,
"pop" no gancho do primeiro segundo, brilho no fechamento) e loudness normalizado para redes (-14 LUFS).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..claims import find_unsupported_claims
from ..ffmpeg import FFmpeg
from ..models import AudioCue, ClaimKind, ClipCut, EditPlan, MusicBed, ProductSheet, Script, TextOverlay, Transition
from . import sound

# Estilos de edição. "music" = trilha padrão do estilo (o operador pode trocar ou tirar).
EDIT_STYLES = {
    "dinamico": {"label": "Dinâmico", "hint": "transições rápidas, whoosh e batida animada",
                 "transitions": ["smoothleft", "zoomin", "slideup", "smoothright"], "t": 0.35,
                 "music": "batida_pop_120", "music_gain_db": -9.0,
                 "sfx": {"hook": ("pop", -6.0), "transition": ("whoosh", -4.0), "end": ("ding", -9.0)}},
    "suave": {"label": "Suave", "hint": "fusões lentas e trilha calma",
              "transitions": ["fade", "dissolve"], "t": 0.6, "music": "lofi_90", "music_gain_db": -11.0,
              "sfx": {"end": ("ding", -12.0)}},
    "limpo": {"label": "Limpo", "hint": "cortes secos, sem trilha nem efeitos (para usar um som em alta na Shopee)",
              "transitions": ["cut"], "t": 0.0, "music": None, "music_gain_db": 0.0, "sfx": {}},
}
DEFAULT_STYLE = "dinamico"
DISCLOSURE_OVERLAY = re.compile(r"publicidade|gerad[ao]s? por ia|imagens ilustrativas", re.I)


def _snap(d: float, beat: float | None) -> float:
    if not beat:
        return d
    return max(round(d / beat), 2) * beat


def build_edit_plan(script: Script, takes: dict[int, Path], probes: dict[int, dict], *, style: str | None = None,
                    music: dict | None = None, music_path: Path | None = None,
                    sfx_paths: dict[str, Path] | None = None) -> EditPlan:
    """Plano de corte. Sem estilo: cortes secos e silêncio (comportamento original).

    Com transição de duração T, cada clipe (menos o último) ganha T a mais do take, para que a sobreposição não
    encurte o vídeo: a duração final continua a soma das durações úteis do roteiro.
    """
    cfg = EDIT_STYLES.get(style or "")
    beat = 60.0 / music["bpm"] if (music and music.get("bpm")) else None
    targets = [_snap(s.target_duration_s, beat) for s in script.scenes]
    n = len(script.scenes)
    kinds = (cfg["transitions"] if cfg else ["cut"])
    transitions = []
    for k in range(n - 1):
        kind = kinds[k % len(kinds)]
        transitions.append(Transition(kind=kind, duration_s=0.0 if kind == "cut" else cfg["t"]))
    clips = []
    for k, scene in enumerate(script.scenes):
        available = probes[scene.index]["duration_s"]
        extra = transitions[k].duration_s if k < n - 1 else 0.0
        dur = min(targets[k] + extra, available)
        clips.append(ClipCut(scene_index=scene.index, source_path=str(takes[scene.index]), start_s=0.0,
                             duration_s=round(dur, 3)))
    plan = EditPlan(clips=clips, transitions=transitions if cfg else [], style=style or "classico")
    total = plan.total_s()
    plan.overlays = [o.model_copy(update={"end_s": min(o.end_s, total)}) for o in script.overlays]
    if not cfg:
        return plan
    if music and music_path:
        bed = dict(path=str(music_path), title=music["title"], license=music["license"], offset_s=float(music.get("start_s", 0) or 0),
                   gain_db=cfg["music_gain_db"] if music.get("gain_db") is None else float(music["gain_db"]))
        if music.get("fade_in_s") is not None:
            bed["fade_in_s"] = float(music["fade_in_s"])
        if music.get("fade_out_s") is not None:
            bed["fade_out_s"] = float(music["fade_out_s"])
        plan.music = MusicBed(**bed)
    sfx_paths = sfx_paths or {}
    cues = []
    if "hook" in cfg["sfx"] and cfg["sfx"]["hook"][0] in sfx_paths:
        name, gain = cfg["sfx"]["hook"]
        cues.append(AudioCue(path=str(sfx_paths[name]), start_s=0.12, gain_db=gain, label="gancho"))
    if "transition" in cfg["sfx"] and cfg["sfx"]["transition"][0] in sfx_paths:
        name, gain = cfg["sfx"]["transition"]
        boundary = 0.0
        for k, tr in enumerate(transitions):
            boundary += targets[k]
            mid = boundary + tr.duration_s / 2  # o xfade da cena k começa no fim da duração útil dela
            cues.append(AudioCue(path=str(sfx_paths[name]), start_s=round(max(mid - sound.SFX_PEAK_S[name], 0), 3),
                                 gain_db=gain, label=f"transição {k + 1}→{k + 2}"))
    if "end" in cfg["sfx"] and cfg["sfx"]["end"][0] in sfx_paths:
        name, gain = cfg["sfx"]["end"]
        cues.append(AudioCue(path=str(sfx_paths[name]), start_s=round(max(total - 1.6, 0), 3), gain_db=gain,
                             label="fechamento"))
    plan.sfx = cues
    return plan


def validate_edit_plan(plan: EditPlan, probes: dict[int, dict], script: Script, tolerance_s: float) -> list[str]:
    errors = []
    for c in plan.clips:
        dur = probes[c.scene_index]["duration_s"]
        if c.start_s < 0 or c.duration_s <= 0:
            errors.append(f"cena {c.scene_index}: corte inválido ({c.start_s}, {c.duration_s})")
        if c.start_s + c.duration_s > dur + 0.05:
            errors.append(f"cena {c.scene_index}: corte ultrapassa o take ({c.start_s + c.duration_s:.2f}s > {dur:.2f}s)")
    if plan.transitions and len(plan.transitions) != len(plan.clips) - 1:
        errors.append("número de transições não bate com o de clipes")
    for k, t in enumerate(plan.transitions):
        if t.kind != "cut" and not (0 < t.duration_s < min(plan.clips[k].duration_s, plan.clips[k + 1].duration_s)):
            errors.append(f"transição {k + 1}: duração {t.duration_s}s inválida")
    total = plan.total_s()
    if abs(total - script.total_target_s) > tolerance_s:
        errors.append(f"duração final {total:.2f}s fora de {script.total_target_s}±{tolerance_s}s")
    for o in plan.overlays:
        if not (0 <= o.start_s < o.end_s <= total + 0.01):
            errors.append(f"texto de tela fora do intervalo: {o.text!r}")
    return errors


def build_caption(sheet: ProductSheet, fmt: dict) -> tuple[str, list[str]]:
    """Legenda baseada só na ficha validada. Retorna (texto, alertas)."""
    p = sheet.product
    lines = [f"{p.name} — {p.variant}"]
    facts = [c for c in p.claims if c.kind == ClaimKind.VERIFIED and c.text]
    if facts:
        lines.append("")
        lines += [f"• {c.text}" for c in facts]
    lines += ["", fmt["disclosure"]["caption_text"], " ".join(fmt["caption"]["hashtags"])]
    caption = "\n".join(lines)
    warnings = []
    bad = find_unsupported_claims(caption, sheet)
    if bad:
        warnings.append(f"legenda contém termos sem informação verificada: {bad} — revise o nome/fatos da ficha")
    if len(caption) > fmt["caption"]["max_chars"]:
        warnings.append("legenda acima do limite configurado")
    if fmt["disclosure"].get("status") != "revisado":
        warnings.append("texto de identificação (publicidade/IA) ainda não revisado conforme regras vigentes")
    return caption, warnings


def assemble_and_package(ffmpeg: FFmpeg, plan: EditPlan, delivery: Path, workdir: Path, cover_time_s: float) -> dict:
    """final.mp4 (com trilha e efeitos do estilo) e, quando há trilha, final_sem_musica.mp4 (só efeitos) para usar
    um som em alta no editor da Shopee Vídeo."""
    no_music = delivery / "final_sem_musica.mp4"
    final = ffmpeg.assemble(plan, delivery / "final.mp4", workdir, no_music_out=no_music if plan.music else None)
    if not plan.music and no_music.exists():
        no_music.unlink()  # sobra de uma montagem anterior com trilha
    info = ffmpeg.probe(final)
    t = min(cover_time_s, max(info["duration_s"] - 0.2, 0))
    cover = ffmpeg.extract_frame(final, t, delivery / "cover.jpg")
    return {"final": final, "cover": cover, "final_probe": info, "cover_time_s": t,
            "no_music": no_music if plan.music else None}


__all__ = ["build_edit_plan", "validate_edit_plan", "build_caption", "assemble_and_package", "TextOverlay",
           "EDIT_STYLES", "DEFAULT_STYLE"]
