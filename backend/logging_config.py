from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_ERROR_LOG = Path("logs/error.log")
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3


def configure_application_logging(name: str = "hynix_basis") -> logging.Logger:
    """Configure one error logger without changing third-party loggers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    if os.getenv("HYNIX_LOG_MODE") == "stderr":
        handler: logging.Handler = logging.StreamHandler()
    else:
        path = Path(os.getenv("HYNIX_ERROR_LOG", DEFAULT_ERROR_LOG))
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUPS,
            encoding="utf-8",
        )
    handler.setLevel(logging.WARNING)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
