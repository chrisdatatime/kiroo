"""Kit de som do editor: trilhas e efeitos.

- Trilhas e efeitos "do estúdio" são SINTETIZADOS pelo FFmpeg (sem amostras de terceiros): livres de direitos.
- Trilhas próprias: `assets/music/library.json` com arquivos que o operador tem licença para usar em vídeo comercial
  (campo "license" obrigatório; sem ele a faixa não aparece).
- Músicas "virais"/em alta são protegidas por direitos autorais e licenciadas só dentro de cada plataforma. Por isso o
  editor entrega também uma versão sem música, para o som em alta ser escolhido no editor da própria Shopee Vídeo.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..ffmpeg import FFmpeg

STUDIO_LICENSE = "gerada pelo estúdio (síntese própria, livre de direitos)"

# Trilhas sintetizadas: BPM, progressão (Hz por compasso) e intensidade.
BUILTIN_TRACKS = {
    "batida_pop_120": {"title": "Batida pop 120 (estúdio)", "bpm": 120, "mood": "animada",
                       "bass": [55.0, 43.65, 49.0, 41.2], "minor": [True, False, False, False], "hats": 0.22,
                       "clap": 0.35, "kick": 0.9},
    "lofi_90": {"title": "Lo-fi 90 (estúdio)", "bpm": 90, "mood": "calma",
                "bass": [49.0, 41.2, 43.65, 36.71], "minor": [False, True, False, False], "hats": 0.12,
                "clap": 0.18, "kick": 0.6},
}

SFX = {
    "whoosh": ("anoisesrc=d=0.75:c=pink:a=0.9:r=48000,bandpass=f=1600:width_type=o:w=2.2,"
               "afade=t=in:d=0.45:curve=qsin,afade=t=out:st=0.45:d=0.3:curve=qsin,volume=1.6"),
    "pop": "aevalsrc='0.9*sin(2*PI*(1250-850*min(t/0.06\\,1))*t)*exp(-38*t)':s=48000:d=0.16",
    "ding": ("aevalsrc='0.45*sin(2*PI*1760*t)*exp(-4.5*t)+0.28*sin(2*PI*2637*t)*exp(-6*t)"
             "+0.14*sin(2*PI*3520*t)*exp(-8*t)':s=48000:d=1.4"),
}
SFX_PEAK_S = {"whoosh": 0.45, "pop": 0.02, "ding": 0.0}  # onde o som "acontece" dentro do arquivo


def _track_graph(cfg: dict, seconds: float) -> str:
    b = 60.0 / cfg["bpm"]
    bar = 4 * b
    f = cfg["bass"]
    sel = (f"if(lt(mod(t\\,{16 * b})\\,{bar})\\,{f[0]}\\,if(lt(mod(t\\,{16 * b})\\,{2 * bar})\\,{f[1]}\\,"
           f"if(lt(mod(t\\,{16 * b})\\,{3 * bar})\\,{f[2]}\\,{f[3]})))")
    third = (f"if(lt(mod(t\\,{16 * b})\\,{bar})\\,{1.189 if cfg['minor'][0] else 1.26}\\,"
             f"if(lt(mod(t\\,{16 * b})\\,{2 * bar})\\,{1.189 if cfg['minor'][1] else 1.26}\\,"
             f"if(lt(mod(t\\,{16 * b})\\,{3 * bar})\\,{1.189 if cfg['minor'][2] else 1.26}\\,"
             f"{1.189 if cfg['minor'][3] else 1.26})))")
    pump = f"(1-0.75*exp(-7*mod(t\\,{b})))"  # "sidechain": a trilha respira com o bumbo
    kick = f"{cfg['kick']}*sin(2*PI*(48+110*exp(-28*mod(t\\,{b})))*mod(t\\,{b}))*exp(-8*mod(t\\,{b}))"
    clap = f"{cfg['clap']}*(random(1)*2-1)*exp(-26*mod(t-{b}\\,{2 * b}))*gte(t\\,{b})"
    hats = f"{cfg['hats']}*(random(2)*2-1)*exp(-110*mod(t\\,{b / 2}))"
    bass = f"0.32*{pump}*sin(2*PI*{sel}*t)"
    pad = (f"0.07*{pump}*(sin(2*PI*4*{sel}*t)+sin(2*PI*4*{sel}*{third}*t)+sin(2*PI*4*{sel}*1.498*t))")
    d = f"{seconds:.2f}"
    return ";\n".join([
        f"aevalsrc='{kick}':s=48000:d={d}[k]",
        f"aevalsrc='{clap}':s=48000:d={d},highpass=f=900,lowpass=f=7000[c]",
        f"aevalsrc='{hats}':s=48000:d={d},highpass=f=6500[h]",
        f"aevalsrc='{bass}':s=48000:d={d},lowpass=f=260[b]",
        f"aevalsrc='{pad}':s=48000:d={d},lowpass=f=2400,aecho=0.6:0.5:180:0.25[p]",
        "[k][c][h][b][p]amix=inputs=5:normalize=0,alimiter=limit=0.89,aformat=channel_layouts=stereo[out]",
    ])


def library(assets_dir: Path) -> list[dict]:
    """Trilhas disponíveis: as do estúdio + as licenciadas pelo operador em assets/music/library.json."""
    out = [{"id": k, "title": v["title"], "bpm": v["bpm"], "mood": v["mood"], "license": STUDIO_LICENSE,
            "builtin": True} for k, v in BUILTIN_TRACKS.items()]
    lib = Path(assets_dir) / "music" / "library.json"
    if lib.is_file():
        try:
            items = json.loads(lib.read_text(encoding="utf-8"))
        except ValueError:
            items = []
        for it in items if isinstance(items, list) else []:
            f = Path(assets_dir) / "music" / str(it.get("file", ""))
            if it.get("id") and it.get("license") and f.is_file() and it["id"] not in BUILTIN_TRACKS:
                out.append({"id": str(it["id"]), "title": str(it.get("title") or it["id"]), "bpm": it.get("bpm"),
                            "mood": it.get("mood", ""), "license": str(it["license"]), "source": it.get("source", ""),
                            "start_s": float(it.get("start_s", 0) or 0), "path": str(f), "builtin": False})
    return out


def track_file(ffmpeg: FFmpeg, cache: Path, entry: dict, seconds: float = 32.0) -> Path:
    """Arquivo de áudio da trilha (sintetiza e guarda em cache as do estúdio)."""
    if not entry.get("builtin"):
        return Path(entry["path"])
    cfg = BUILTIN_TRACKS[entry["id"]]
    out = cache / f"{entry['id']}_{int(seconds)}s.wav"
    if not out.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        graph = cache / f"{entry['id']}.graph.txt"
        graph.write_text(_track_graph(cfg, seconds), encoding="utf-8")
        ffmpeg.run(["-/filter_complex", str(graph.resolve()), "-map", "[out]", "-ar", "48000", str(out.resolve())])
    return out


def sfx_file(ffmpeg: FFmpeg, cache: Path, name: str) -> Path:
    out = cache / f"sfx_{name}.wav"
    if not out.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        ffmpeg.run(["-f", "lavfi", "-i", SFX[name], "-ac", "2", "-ar", "48000", str(out.resolve())])
    return out


__all__ = ["library", "track_file", "sfx_file", "SFX", "SFX_PEAK_S", "BUILTIN_TRACKS", "STUDIO_LICENSE"]
