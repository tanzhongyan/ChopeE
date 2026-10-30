"""X-Ray tracing helpers shared by the FastAPI services and Lambda handlers (SRE-6).

Terraform owns the Fargate sidecar and Lambda active tracing. This module only
adds application segments, annotations and AWS SDK patches. Tracing is disabled
when no X-Ray daemon address is configured (local tests, storefront) or when
CHOPEE_TRACING_DISABLED is set, so it never blocks a request or opens a socket
outside a deployed run.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_TRUE = {"1", "true", "yes", "on"}
log = logging.getLogger("chopee.tracing")


def tracing_enabled() -> bool:
    if os.environ.get("CHOPEE_TRACING_DISABLED", "").lower() in _TRUE:
        return False
    return bool(os.environ.get("AWS_XRAY_DAEMON_ADDRESS") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _recorder():
    from aws_xray_sdk.core import xray_recorder

    return xray_recorder


def _patch_all() -> None:
    from aws_xray_sdk.core import patch_all

    patch_all()


_configured = False


def init_tracing(service: str, *, async_context: bool = False) -> bool:
    """Configure the process-wide recorder once. Returns True when enabled."""
    global _configured
    if not tracing_enabled() or _configured:
        return False
    try:
        recorder = _recorder()
        kwargs: dict[str, Any] = {
            "service": service,
            "daemon_address": os.environ.get("AWS_XRAY_DAEMON_ADDRESS", "127.0.0.1:2000"),
            "context_missing": "LOG_ERROR",
        }
        if async_context:
            from aws_xray_sdk.core.async_context import AsyncContext

            kwargs["context"] = AsyncContext()
        recorder.configure(**kwargs)
        _patch_all()
        _configured = True
        return True
    except Exception:
        # Tracing must never prevent the service from starting, but make the
        # degradation visible in the service log.
        log.warning("xray_init_failed", exc_info=True)
        return False


def annotate(**fields: Any) -> None:
    """Attach safe, low-cardinality annotations to the current segment."""
    if not tracing_enabled():
        return
    try:
        segment = _recorder().current_segment()
        if segment is None:
            return
        for key, value in fields.items():
            if value is not None:
                segment.put_annotation(key, value)
    except Exception:
        log.debug("xray_annotation_failed", exc_info=True)


def annotate_order(order_id: str) -> None:
    if order_id:
        annotate(orderId=str(order_id))


def current_trace_header() -> str:
    """Return a header for the active checkout segment, not the raw inbound header.

    Re-sending the inbound ALB header would override the SDK's own AWSTraceHeader
    and lose the checkout segment as the worker's parent.
    """
    if not tracing_enabled():
        return ""
    try:
        segment = _recorder().current_segment()
        if segment is None:
            return ""
        sampled = "1" if getattr(segment, "sampled", True) else "0"
        return f"Root={segment.trace_id};Parent={segment.id};Sampled={sampled}"
    except Exception:
        log.debug("xray_trace_header_failed", exc_info=True)
        return ""


class XRayMiddleware:
    """One segment per HTTP request, linked to an incoming X-Ray trace header."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not tracing_enabled():
            await self.app(scope, receive, send)
            return

        from aws_xray_sdk.core.models.trace_header import TraceHeader

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        trace_id = parent_id = None
        raw = headers.get("x-amzn-trace-id")
        if raw:
            try:
                header = TraceHeader.from_header_str(raw)
                trace_id, parent_id = header.root, header.parent
            except Exception:
                log.debug("xray_trace_header_parse_failed", exc_info=True)

        segment = None
        try:
            segment = _recorder().begin_segment("checkout", traceid=trace_id, parent_id=parent_id)
            segment.put_http_meta("method", scope.get("method"))
        except Exception:
            log.debug("xray_segment_start_failed", exc_info=True)
            segment = None

        async def send_with_status(message):
            if segment is not None and message.get("type") == "http.response.start":
                try:
                    segment.put_http_meta("status", message.get("status"))
                except Exception:
                    log.debug("xray_status_annotation_failed", exc_info=True)
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            if segment is not None:
                try:
                    _recorder().end_segment()
                except Exception:
                    log.debug("xray_segment_end_failed", exc_info=True)
