"""Logging com redação de segredos e saída JSON (uma linha por evento) para produção."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Contexto da requisição em andamento (request_id, workspace_id). Mutável: o handler cria, as camadas de baixo preenchem.
REQUEST_INFO: contextvars.ContextVar[dict | None] = contextvars.ContextVar("studio_request_info", default=None)


def _mask(text: str, secrets: list[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "***")
    return text


def redact(text) -> str:
    """Mascara qualquer segredo conhecido do ambiente (para mensagens de erro que vão à interface ou ao banco)."""
    from .config import secret_values
    return _mask(str(text), [s for s in secret_values() if len(s) >= 6])


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = _mask(record.getMessage(), self.secrets), None
        if record.exc_info and not record.exc_text:   # o traceback também pode carregar a chave na mensagem
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _mask(record.exc_text, self.secrets)
        if record.stack_info:
            record.stack_info = _mask(record.stack_info, self.secrets)
        return True


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por registro. Só campos conhecidos: nível, mensagem fixa, id da requisição, rota, status,
    duração e workspace. O corpo das requisições, e-mails, códigos e tokens nunca entram aqui."""

    FIELDS = ("request_id", "method", "route", "status", "duration_ms", "workspace_id", "pid", "event",
              "settle_s", "interrupted")

    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = [s for s in (secrets or []) if s and len(s) >= 6]

    def format(self, record: logging.LogRecord) -> str:
        info = REQUEST_INFO.get() or {}
        out: dict = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                     "level": record.levelname, "logger": record.name,
                     "msg": _mask(record.getMessage(), self.secrets)}
        for key in self.FIELDS:
            value = getattr(record, key, None)
            if value is None:
                value = info.get(key)
            if value is not None:
                out[key] = value
        if record.exc_info:  # só o tipo da exceção: a mensagem pode carregar dados do usuário
            out["error"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
        return _mask(json.dumps(out, ensure_ascii=False, default=str), self.secrets)


def setup_logging(log_dir: Path, secrets: list[str], verbose: bool = False, *, json_stdout: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("studio")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    redact = RedactingFilter(secrets)
    file_handler = logging.FileHandler(log_dir / "studio.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    file_handler.addFilter(redact)
    logger.addHandler(file_handler)
    if json_stdout:
        out = logging.StreamHandler(sys.stdout)
        out.setFormatter(JsonFormatter(secrets))
        out.setLevel(logging.DEBUG if verbose else logging.INFO)
    else:
        out = logging.StreamHandler()
        out.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        out.addFilter(redact)
        out.setLevel(logging.WARNING if not verbose else logging.DEBUG)
    logger.addHandler(out)
