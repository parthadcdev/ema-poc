"""Structured JSON logging with credential redaction (spec §7; NF-007, SE-006)."""

from __future__ import annotations

import json
import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),          # OpenAI / Anthropic style
    re.compile(r"AIza[0-9A-Za-z_\-]{8,}"),         # Google API key style
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),  # Bearer tokens
]

_REDACTION = "***REDACTED***"


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTION, text)
    return text


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Collapse lazy %-args into the message so redaction sees the final
        # interpolated string (secrets are often passed as a log argument).
        if record.args:
            record.msg = record.getMessage()
            record.args = ()
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        return json.dumps(payload)


def get_logger(name: str = "ema", log_path: str | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    handler: logging.Handler = (
        logging.FileHandler(log_path) if log_path else logging.StreamHandler()
    )
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
