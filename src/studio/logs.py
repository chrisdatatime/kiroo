"""Logging com redação de segredos."""

from __future__ import annotations

import logging
from pathlib import Path


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for secret in self.secrets:
            msg = msg.replace(secret, "***")
        record.msg, record.args = msg, None
        return True


def setup_logging(log_dir: Path, secrets: list[str], verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("studio")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    redact = RedactingFilter(secrets)
    for handler in (logging.FileHandler(log_dir / "studio.log", encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(fmt)
        handler.addFilter(redact)
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(logging.WARNING if not verbose else logging.DEBUG)
        logger.addHandler(handler)
