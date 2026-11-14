"""Monta o orquestrador com provedores simulados ou reais conforme o modo."""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .db import Database
from .ffmpeg import FFmpeg
from .orchestrator import Orchestrator, OrchestratorError
from .providers.simulated import (SimulatedImageGenerator, SimulatedPlanner, SimulatedReviewer,
                                  SimulatedVideoGenerator, SimulationScript)


class _MissingProvider:
    """Provedor Gemini ausente (deploy so com fal.ai): qualquer uso falha com mensagem clara, sem rede."""

    provider, model, simulated = "gemini-api", "indisponivel", False

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _fail(*a, **k):
            from .providers.base import PermanentError
            raise PermanentError("GEMINI_API_KEY nao definida: o motor Gemini esta indisponivel neste ambiente")
        return _fail


def _build_fal(settings: Settings, ff: FFmpeg, sim_fal_script):
    """Gerador de workflows do motor fal.ai. Simulado em DEMO; real so com FAL_KEY. Nunca levanta por falta de chave:
    quem precisa dele (producoes engine=fal) recebe o erro claro na hora de usar."""
    from . import budget as budget_mod
    estimator = lambda style: budget_mod.workflow_cost(style)  # noqa: E731
    if settings.mode == "simulated":
        from .providers.simulated_fal import FalSimScript, SimulatedFalWorkflow
        return SimulatedFalWorkflow(settings.data_dir, ff, sim_fal_script or FalSimScript(), estimator=estimator)
    if not (settings.allow_paid_calls and settings.fal_api_key):
        return None
    from .fal_contract import ContractError, load_contract
    from .providers.fal import FalClient, FalWorkflowGenerator
    try:
        contract = load_contract(settings.profiles_dir)
    except ContractError:
        return None
    client = FalClient(settings.fal_api_key, settings.fal_billing_key)
    return FalWorkflowGenerator(client, contract, {"dark": settings.workflow_id_dark, "light": settings.workflow_id_light},
                                start_timeout_s=settings.fal_timeout_s, estimator=estimator)


def build(settings: Settings, *, sim_script: SimulationScript | None = None, sleep=None,
          base_dir: Path | None = None, sim_fal_script=None, fal_gen=None) -> Orchestrator:
    db = Database(settings.db_path)
    ff = FFmpeg(settings.ffmpeg_bin, settings.ffprobe_bin, settings.font_file, settings.x264_preset)
    if settings.mode == "simulated":
        script = sim_script or SimulationScript()
        image = SimulatedImageGenerator(settings.data_dir, settings.image_model, script)
        video = SimulatedVideoGenerator(settings.data_dir, settings.video_model, ff, script)
        planner, reviewer = SimulatedPlanner(), SimulatedReviewer(script)
    else:
        if not (settings.allow_paid_calls and (settings.gemini_api_key or settings.fal_api_key)):
            raise OrchestratorError("modo real exige STUDIO_ALLOW_PAID_CALLS=true e GEMINI_API_KEY (ou FAL_KEY)")
        if settings.gemini_api_key:
            from .providers.gemini import GeminiImageGenerator, GeminiPlanner, GeminiReviewer, GeminiVideoGenerator

            key = settings.gemini_api_key
            image = GeminiImageGenerator(key, settings.image_model)
            video = GeminiVideoGenerator(key, settings.video_model)
            planner = GeminiPlanner(key, settings.planner_model)
            reviewer = GeminiReviewer(key, settings.reviewer_model)
        else:   # deploy so com fal.ai: o motor Gemini fica indisponivel, nunca simulado por engano
            image = video = planner = reviewer = _MissingProvider()
    if sleep is None and settings.mode == "simulated":
        import time

        sleep = lambda s: time.sleep(min(s, 0.3))  # noqa: E731 — simulação não precisa esperar de verdade
    kwargs = {"sleep": sleep} if sleep else {}
    return Orchestrator(settings, db, image_gen=image, video_gen=video, planner=planner, reviewer=reviewer,
                        ffmpeg=ff, base_dir=base_dir, fal_gen=fal_gen or _build_fal(settings, ff, sim_fal_script), **kwargs)
