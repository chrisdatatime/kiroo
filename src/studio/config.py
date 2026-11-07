"""Configuração por variáveis de ambiente (.env opcional)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _path(value: str | None, default: Path) -> Path:
    return Path(value).expanduser().resolve() if value else default


def _find_binary(name: str, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    found = shutil.which(name)
    if found:
        return found
    # winget instala o FFmpeg em Packages/ e só atualiza o PATH em novos shells
    local = os.environ.get("LOCALAPPDATA")
    if local:
        base = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if base.exists():
            for exe in sorted(base.glob(f"Gyan.FFmpeg*/**/bin/{name}.exe")):
                return str(exe)
    return None


def _default_font() -> str | None:
    for candidate in (
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    assets_dir: Path
    profiles_dir: Path
    mode: str
    allow_paid_calls: bool
    planner_model: str
    reviewer_model: str
    image_model: str
    image_size: str
    video_model: str
    video_resolution: str
    max_inflight_ops: int
    max_image_attempts: int
    max_video_attempts: int
    poll_interval_s: float
    ffmpeg_bin: str | None
    ffprobe_bin: str | None
    font_file: str | None
    x264_preset: str
    monthly_cap_usd: float = 0.0  # teto de gasto real no mês (0 = chamadas pagas bloqueadas)
    gemini_api_key: str | None = field(default=None, repr=False)
    reference_dir: Path | None = None  # STUDIO_REFERENCE_DIR: referências pessoais (foto da apresentadora), fora dos assets da imagem

    @property
    def reference_root(self) -> Path:
        """Onde ficam as referências pessoais (ex.: bia/PERFIL BIA.jpg). Sem STUDIO_REFERENCE_DIR, o mesmo que assets_dir."""
        return self.reference_dir or self.assets_dir

    @property
    def db_path(self) -> Path:
        return self.data_dir / "studio.sqlite3"

    def secret_values(self) -> list[str]:
        """Valores que nunca podem aparecer em logs, respostas ou artefatos."""
        return secret_values(extra=[self.gemini_api_key])


# Variáveis cujo VALOR é segredo (o nome pode aparecer; o valor nunca). MP_* entra inteiro (Mercado Pago).
SECRET_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "STUDIO_GOOGLE_CLIENT_SECRET",
               "STUDIO_SMTP_PASSWORD", "BACKUP_R2_ACCESS_KEY_ID", "BACKUP_R2_SECRET_ACCESS_KEY",
               "LITESTREAM_ACCESS_KEY_ID", "LITESTREAM_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY")
SECRET_PREFIXES = ("MP_",)
SECRET_LISTS = ("STUDIO_INVITE_CODES",)   # vários valores separados por vírgula (legado)


def secret_values(env=None, extra=None) -> list[str]:
    """Todos os valores secretos conhecidos do ambiente: Gemini, Anthropic, Google OAuth, SMTP, Mercado Pago (MP_*),
    backup R2/Litestream e códigos de convite antigos. Mais longos primeiro (um segredo que contém outro é mascarado
    inteiro)."""
    e = os.environ if env is None else env
    out = {v for v in (extra or []) if v}
    out |= {e.get(k) for k in SECRET_VARS if e.get(k)}
    out |= {v for k, v in e.items() if k.startswith(SECRET_PREFIXES) and v}
    for k in SECRET_LISTS:
        out |= {c.strip() for c in (e.get(k) or "").split(",") if c.strip()}
    return sorted((v.strip() for v in out if v and v.strip()), key=len, reverse=True)


def load_settings(env_file: Path | None = None, **overrides) -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    except ImportError:  # pragma: no cover
        pass

    env = os.environ.get
    values = dict(
        data_dir=_path(env("STUDIO_DATA_DIR"), PROJECT_ROOT / "data"),
        assets_dir=_path(env("STUDIO_ASSETS_DIR"), PROJECT_ROOT / "assets"),
        profiles_dir=_path(env("STUDIO_PROFILES_DIR"), PROJECT_ROOT / "profiles"),
        mode=(env("STUDIO_MODE") or "simulated").strip().lower(),
        allow_paid_calls=_bool(env("STUDIO_ALLOW_PAID_CALLS")),
        planner_model=env("STUDIO_PLANNER_MODEL") or "gemini-3.8-flash",
        reviewer_model=env("STUDIO_REVIEWER_MODEL") or "gemini-3.8-flash",
        image_model=env("STUDIO_IMAGE_MODEL") or "gemini-nano-banana-2.1",
        image_size=env("STUDIO_IMAGE_SIZE") or "2K",
        video_model=env("STUDIO_VIDEO_MODEL") or "gemini-omni-1.1-flash",
        video_resolution=env("STUDIO_VIDEO_RESOLUTION") or "720p",
        max_inflight_ops=int(env("STUDIO_MAX_INFLIGHT_OPS") or 2),
        max_image_attempts=int(env("STUDIO_MAX_IMAGE_ATTEMPTS") or 4),
        max_video_attempts=int(env("STUDIO_MAX_VIDEO_ATTEMPTS") or 3),
        poll_interval_s=float(env("STUDIO_POLL_INTERVAL_S") or 10),
        ffmpeg_bin=_find_binary("ffmpeg", env("STUDIO_FFMPEG")),
        ffprobe_bin=_find_binary("ffprobe", env("STUDIO_FFPROBE")),
        font_file=env("STUDIO_FONT_FILE") or _default_font(),
        x264_preset=env("STUDIO_X264_PRESET") or "medium",
        monthly_cap_usd=float(env("STUDIO_MONTHLY_CAP_USD") or 0),
        gemini_api_key=env("GEMINI_API_KEY") or None,
        reference_dir=_path(env("STUDIO_REFERENCE_DIR"), PROJECT_ROOT / "assets") if env("STUDIO_REFERENCE_DIR") else None,
    )
    # Ajustes feitos pela interface (data/agents.json): só campos não sensíveis e já validados.
    from .agent_config import load as load_agent_config, validate_settings

    data_dir = overrides.get("data_dir", values["data_dir"])
    ui = load_agent_config(Path(data_dir))
    ui_settings = ui["settings"]
    runtime = ui["runtime"]  # chave DEMO/real e teto mensal ligados pela interface
    if runtime.get("mode") in {"simulated", "real"}:
        values["mode"] = runtime["mode"]
        values["allow_paid_calls"] = runtime["mode"] == "real"
    if isinstance(runtime.get("monthly_cap_usd"), (int, float)) and runtime["monthly_cap_usd"] >= 0:
        values["monthly_cap_usd"] = float(runtime["monthly_cap_usd"])
    if ui_settings:
        try:
            values.update(validate_settings(ui_settings, values))
        except ValueError:
            pass  # arquivo inválido é ignorado; a interface mostra o erro ao salvar
    values.update(overrides)
    if values["mode"] not in {"simulated", "real"}:
        raise ValueError("STUDIO_MODE deve ser 'simulated' ou 'real'")
    return Settings(**values)
