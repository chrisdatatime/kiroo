"""Monta o orquestrador com provedores simulados ou reais conforme o modo."""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .db import Database
from .ffmpeg import FFmpeg
from .orchestrator import Orchestrator, OrchestratorError
from .providers.simulated import (SimulatedImageGenerator, SimulatedPlanner, SimulatedReviewer,
                                  SimulatedVideoGenerator, SimulationScript)


def build(settings: Settings, *, sim_script: SimulationScript | None = None, sleep=None,
          base_dir: Path | None = None) -> Orchestrator:
    db = Database(settings.db_path)
    ff = FFmpeg(settings.ffmpeg_bin, settings.ffprobe_bin, settings.font_file, settings.x264_preset)
    if settings.mode == "simulated":
        script = sim_script or SimulationScript()
        image = SimulatedImageGenerator(settings.data_dir, settings.image_model, script)
        video = SimulatedVideoGenerator(settings.data_dir, settings.video_model, ff, script)
        planner, reviewer = SimulatedPlanner(), SimulatedReviewer(script)
    else:
        if not (settings.allow_paid_calls and settings.gemini_api_key):
            raise OrchestratorError("modo real exige STUDIO_ALLOW_PAID_CALLS=true e GEMINI_API_KEY")
        from .providers.gemini import GeminiImageGenerator, GeminiPlanner, GeminiReviewer, GeminiVideoGenerator

        key = settings.gemini_api_key
        image = GeminiImageGenerator(key, settings.image_model)
        video = GeminiVideoGenerator(key, settings.video_model)
        planner = GeminiPlanner(key, settings.planner_model)
        reviewer = GeminiReviewer(key, settings.reviewer_model)
    if sleep is None and settings.mode == "simulated":
        import time

        sleep = lambda s: time.sleep(min(s, 0.3))  # noqa: E731 — simulação não precisa esperar de verdade
    kwargs = {"sleep": sleep} if sleep else {}
    return Orchestrator(settings, db, image_gen=image, video_gen=video, planner=planner, reviewer=reviewer,
                        ffmpeg=ff, base_dir=base_dir, **kwargs)
