"""Structured JSON logging and customer pseudonyms. Never log email, tokens or payloads."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging as _logging
import sys
import time


def pseudonymise(log_salt: str, sub: str) -> str:
    """customerRef: first 12 hex chars of HMAC-SHA256(log_salt, sub)."""
    return hmac.new(log_salt.encode(), sub.encode(), hashlib.sha256).hexdigest()[:12]


class _JsonFormatter(_logging.Formatter):
    def format(self, record: _logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "service": record.name,
            "message": record.getMessage(),
        }
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, separators=(",", ":"), default=str)


def get_logger(service: str, level: int = _logging.INFO) -> _logging.Logger:
    """JSON logger to stdout (CloudWatch). Pass extra fields via ``extra={"fields": {...}}``."""
    logger = _logging.getLogger(service)
    if not any(getattr(h, "_chopee", False) for h in logger.handlers):
        handler = _logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        handler._chopee = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
