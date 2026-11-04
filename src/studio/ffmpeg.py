"""Edição determinística com FFmpeg/ffprobe.

Os comandos são montados como listas de argumentos (sem shell). Textos de tela são
gravados em arquivos e lidos via `textfile=`, então o conteúdo nunca é interpretado
como sintaxe de filtro.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .models import EditPlan


class FFmpegError(Exception):
    pass


def _filter_path(path: Path | str) -> str:
    """Escapa um caminho para uso como valor de opção dentro de um filtergraph."""
    s = str(path).replace("\\", "/")
    s = s.replace("'", r"\'").replace(":", r"\:")
    return f"'{s}'"


class FFmpeg:
    def __init__(self, ffmpeg: str | None, ffprobe: str | None, font_file: str | None = None, preset: str = "medium"):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.font_file = font_file
        self.preset = preset

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    def _require(self) -> None:
        if not self.available:
            raise FFmpegError("FFmpeg/ffprobe não encontrados. Instale (winget install Gyan.FFmpeg) ou defina STUDIO_FFMPEG/STUDIO_FFPROBE.")

    def run(self, args: list[str], *, cwd: Path | None = None, timeout: int = 900, loglevel: str = "error") -> subprocess.CompletedProcess:
        self._require()
        cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", loglevel, "-y", *args]
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode != 0:
            raise FFmpegError(f"ffmpeg falhou ({proc.returncode}): {proc.stderr.strip()[-1500:]}")
        return proc

    # ------------------------------------------------------------- inspeção
    def probe(self, path: Path) -> dict:
        self._require()
        proc = subprocess.run(
            [self.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if proc.returncode != 0:
            raise FFmpegError(f"ffprobe falhou: {proc.stderr.strip()[-800:]}")
        data = json.loads(proc.stdout)
        video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
        fps = None
        if video and video.get("avg_frame_rate", "0/0") != "0/0":
            num, den = video["avg_frame_rate"].split("/")
            fps = float(num) / float(den) if float(den) else None
        return {
            "duration_s": float(data.get("format", {}).get("duration", 0) or 0),
            "width": video.get("width") if video else None,
            "height": video.get("height") if video else None,
            "fps": fps,
            "video_codec": video.get("codec_name") if video else None,
            "has_audio": bool(audio),
        }

    def audio_levels(self, path: Path) -> dict:
        """Detecta presença de áudio e volume (volumedetect). Silêncio digital ≈ -91 dB."""
        info = self.probe(path)
        if not info["has_audio"]:
            return {"has_audio": False, "mean_volume_db": None, "max_volume_db": None}
        proc = self.run(["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], loglevel="info")
        mean = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
        peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
        to_f = lambda m: (float("-inf") if m.group(1) == "-inf" else float(m.group(1))) if m else None  # noqa: E731
        return {"has_audio": True, "mean_volume_db": to_f(mean), "max_volume_db": to_f(peak)}

    def sample_frames(self, video: Path, count: int, out_dir: Path) -> list[tuple[float, Path]]:
        """Amostragem uniforme: quadros no centro de `count` janelas iguais + último quadro útil."""
        duration = self.probe(video)["duration_s"]
        if duration <= 0:
            raise FFmpegError(f"duração inválida: {video}")
        out_dir.mkdir(parents=True, exist_ok=True)
        times = [round(duration * (i + 0.5) / count, 3) for i in range(count)]
        times.append(round(max(duration - 0.1, 0), 3))
        frames = []
        for i, t in enumerate(times):
            out = out_dir / f"frame_{i:02d}_{t:06.2f}s.jpg"
            self.extract_frame(video, t, out)
            frames.append((t, out))
        return frames

    def extract_frame(self, video: Path, t: float, out: Path) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        self.run(["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])
        return out

    # ------------------------------------------------------------- geração
    def still_to_clip(self, image: Path, out: Path, seconds: float, width: int, height: int, fps: int = 30,
                      tone: bool = False) -> Path:
        """Clipe com zoom lento a partir de uma imagem (usado pelo modo simulado)."""
        frames = int(seconds * fps)
        vf = (f"scale={width * 2}:{height * 2},zoompan=z='min(zoom+0.0007,1.08)':d={frames}"
              f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},format=yuv420p")
        args = ["-loop", "1", "-i", str(image)]
        if tone:
            args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        args += ["-vf", vf, "-t", f"{seconds}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
        args += ["-c:a", "aac", "-shortest"] if tone else ["-an"]
        out.parent.mkdir(parents=True, exist_ok=True)
        self.run([*args, str(out)])
        return out

    # ------------------------------------------------------------- montagem
    def assemble(self, plan: EditPlan, out: Path, workdir: Path, *, no_music_out: Path | None = None) -> Path:
        """Monta o vídeo (cortes/transições/textos) uma vez e junta o áudio do estilo sem recodificar a imagem.
        `no_music_out`: segunda saída com os mesmos efeitos sonoros, mas sem a trilha."""
        if not plan.clips:
            raise FFmpegError("plano de edição sem clipes")
        if plan.overlays and not self.font_file:
            raise FFmpegError("há textos na tela mas nenhuma fonte foi encontrada (defina STUDIO_FONT_FILE)")
        workdir.mkdir(parents=True, exist_ok=True)
        total = plan.total_s()
        W, H, fps = plan.width, plan.height, plan.fps

        args: list[str] = []
        parts: list[str] = []
        for i, clip in enumerate(plan.clips):
            args += ["-i", str(Path(clip.source_path).resolve())]
            parts.append(
                f"[{i}:v]trim=start={clip.start_s:.3f}:duration={clip.duration_s:.3f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,fps={fps},format=yuv420p,settb=AVTB[v{i}]"
            )
        n = len(plan.clips)
        if not plan.transitions or all(t.kind == "cut" for t in plan.transitions):
            parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc]")
        else:
            cur, length = "v0", plan.clips[0].duration_s
            for k in range(1, n):
                tr = plan.transitions[k - 1]
                nxt = f"x{k}"
                if tr.kind == "cut":
                    parts.append(f"[{cur}][v{k}]concat=n=2:v=1:a=0[{nxt}]")
                    length += plan.clips[k].duration_s
                else:
                    offset = length - tr.duration_s
                    parts.append(f"[{cur}][v{k}]xfade=transition={tr.kind}:duration={tr.duration_s:.3f}"
                                 f":offset={offset:.3f}[{nxt}]")
                    length += plan.clips[k].duration_s - tr.duration_s
                cur = nxt
            parts.append(f"[{cur}]null[vc]")

        last = "vc"
        for j, ov in enumerate(plan.overlays):
            text_file = workdir / f"overlay_{j}.txt"
            text_file.write_text(ov.text, encoding="utf-8")
            y = {"top": "h*0.06", "bottom": "h*0.86-text_h", "center": "(h-text_h)/2"}[ov.position]
            end = min(ov.end_s, total)
            parts.append(
                f"[{last}]drawtext=fontfile={_filter_path(self.font_file)}:textfile={_filter_path(text_file.resolve())}"
                f":fontsize={ov.font_size}:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=14"
                f":x=(w-text_w)/2:y={y}:enable='between(t,{ov.start_s:.2f},{end:.2f})'[o{j}]"
            )
            last = f"o{j}"

        script = workdir / "filtergraph.txt"
        script.write_text(";\n".join(parts), encoding="utf-8")
        video = workdir / "video_only.mp4"
        # "-/opção arquivo" lê o valor da opção a partir de um arquivo (FFmpeg >= 7)
        self.run([*args, "-/filter_complex", str(script.resolve()), "-map", f"[{last}]", "-an",
                  "-c:v", "libx264", "-preset", self.preset, "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps),
                  "-t", f"{total:.3f}", str(video.resolve())])

        out.parent.mkdir(parents=True, exist_ok=True)
        if not plan.music and not plan.sfx and not plan.silent_audio_track:
            self.run(["-i", str(video.resolve()), "-c", "copy", "-movflags", "+faststart", str(out.resolve())])
            return out
        self._mux(video, self._mix_audio(plan, total, workdir / "audio.m4a", with_music=True), out, total)
        if no_music_out is not None:
            self._mux(video, self._mix_audio(plan, total, workdir / "audio_sem_musica.m4a", with_music=False),
                      no_music_out, total)
        return out

    def _mix_audio(self, plan: EditPlan, total: float, out: Path, *, with_music: bool) -> Path:
        """Trilha (com fades e ganho) + efeitos posicionados; loudness -14 LUFS quando há trilha."""
        args: list[str] = []
        parts: list[str] = []
        labels: list[str] = []
        i = 0
        if with_music and plan.music:
            m = plan.music
            args += ["-stream_loop", "-1", "-i", str(Path(m.path).resolve())]
            fo = min(m.fade_out_s, total / 2)
            parts.append(f"[{i}:a]atrim=start={m.offset_s:.3f}:duration={total:.3f},asetpts=PTS-STARTPTS,"
                         f"aformat=sample_rates=48000:channel_layouts=stereo,volume={m.gain_db:.1f}dB,"
                         f"afade=t=in:d={m.fade_in_s:.2f},afade=t=out:st={max(total - fo, 0):.3f}:d={fo:.2f}[m]")
            labels.append("[m]")
            i += 1
        for k, cue in enumerate(plan.sfx):
            if cue.start_s >= total:
                continue
            args += ["-i", str(Path(cue.path).resolve())]
            ms = int(round(cue.start_s * 1000))
            parts.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={cue.gain_db:.1f}dB,"
                         f"adelay={ms}|{ms}[s{k}]")
            labels.append(f"[s{k}]")
            i += 1
        args += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        labels.append(f"[{i}:a]")  # base silenciosa: garante a duração exata mesmo sem trilha
        master = "loudnorm=I={:.1f}:TP=-1.5:LRA=11,".format(plan.loudness_lufs) if (with_music and plan.music) else ""
        parts.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                     f"{master}alimiter=limit=0.89,atrim=duration={total:.3f},aresample=48000[aout]")
        graph = out.with_suffix(".graph.txt")
        graph.write_text(";\n".join(parts), encoding="utf-8")
        self.run([*args, "-/filter_complex", str(graph.resolve()), "-map", "[aout]", "-c:a", "aac", "-b:a", "192k",
                  str(out.resolve())])
        return out

    def _mux(self, video: Path, audio: Path, out: Path, total: float) -> Path:
        self.run(["-i", str(video.resolve()), "-i", str(audio.resolve()), "-map", "0:v", "-map", "1:a",
                  "-c:v", "copy", "-c:a", "copy", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out.resolve())])
        return out
