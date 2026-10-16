"""Webhook HMAC signing: v1 = hex(HMAC_SHA256(secret, f"{t}.{raw_body}")) (plan 06 Section 5.2)."""
from __future__ import annotations

import hashlib
import hmac
import time

HEADER = "X-ChopeE-Signature"
TOLERANCE_SECONDS = 300


class SignatureError(Exception):
    pass


def _mac(secret: str, t: int, raw_body: str) -> str:
    return hmac.new(secret.encode(), f"{t}.{raw_body}".encode(), hashlib.sha256).hexdigest()


def sign(secret: str, raw_body: str, now: int | None = None) -> str:
    t = int(time.time() if now is None else now)
    return f"t={t},v1={_mac(secret, t, raw_body)}"


def verify(secret: str, header: str | None, raw_body: str, now: int | None = None) -> None:
    """Raise SignatureError on a missing, malformed, bad or stale signature."""
    if not header:
        raise SignatureError("missing signature")
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t, v1 = int(parts["t"]), parts["v1"]
    except (ValueError, KeyError) as exc:
        raise SignatureError("malformed signature") from exc
    now = int(time.time() if now is None else now)
    if abs(now - t) > TOLERANCE_SECONDS:
        raise SignatureError("stale signature")
    if not hmac.compare_digest(_mac(secret, t, raw_body), v1):
        raise SignatureError("bad signature")
