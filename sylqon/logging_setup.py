"""Central logging configuration for Sylqon.

Both entrypoints (``python -m sylqon.main`` and ``python -m sylqon.server``)
call :func:`setup_logging` so the pipeline logs identically whether it runs
headless or behind the dashboard. Verbosity is driven by ``config.LOG_LEVEL``
(``SYLQON_DEBUG=1`` or ``SYLQON_LOG_LEVEL=DEBUG`` surfaces the many
``log.debug()`` calls in the pipeline). The file handler rotates so
``sylqon.log`` can't grow unbounded.
"""
from __future__ import annotations

import json
import logging
import logging.handlers

from sylqon import config

_HUMAN_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Guard so repeated calls (main.run then a re-import, tests, etc.) don't stack
# duplicate handlers on the root logger.
_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    """One JSON object per record — easier to grep/ship than the human format."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _build_formatter() -> logging.Formatter:
    return _JsonFormatter() if config.LOG_JSON else logging.Formatter(_HUMAN_FORMAT)


def setup_logging(force: bool = False) -> None:
    """Configure root logging once. Idempotent unless ``force`` is set."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    formatter = _build_formatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_PATH,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any handlers a prior basicConfig / call installed so level and
    # format actually take effect (basicConfig is a no-op if handlers exist).
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    _CONFIGURED = True
    logging.getLogger(__name__).debug(
        "Logging configured: level=%s json=%s file=%s", config.LOG_LEVEL, config.LOG_JSON, config.LOG_PATH
    )
