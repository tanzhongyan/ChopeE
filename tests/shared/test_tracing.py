"""Unit tests for the shared X-Ray helpers (SRE-6), with a fake recorder."""
from __future__ import annotations

import asyncio

from chopee import tracing


class FakeSegment:
    def __init__(self):
        self.annotations = {}
        self.http = {}
        self.trace_id = "1-5f0f0f0f-abcdef0123456789abcdef01"
        self.id = "53995c3f42cd8ad8"
        self.sampled = True

    def put_annotation(self, key, value):
        self.annotations[key] = value

    def put_http_meta(self, key, value):
        self.http[key] = value


class FakeRecorder:
    def __init__(self):
        self.segment = FakeSegment()
        self.begun = None
        self.ended = False
        self.config = {}

    def configure(self, **kwargs):
        self.config = kwargs

    def begin_segment(self, name, traceid=None, parent_id=None):
        self.begun = (name, traceid, parent_id)
        return self.segment

    def end_segment(self):
        self.ended = True

    def current_segment(self):
        return self.segment


def enable(monkeypatch, recorder):
    monkeypatch.setattr(tracing, "tracing_enabled", lambda: True)
    monkeypatch.setattr(tracing, "_recorder", lambda: recorder)


def test_init_tracing_configures_once(monkeypatch):
    recorder = FakeRecorder()
    patched = []
    enable(monkeypatch, recorder)
    monkeypatch.setattr(tracing, "_patch_all", lambda: patched.append(True))
    monkeypatch.setattr(tracing, "_configured", False)

    assert tracing.init_tracing("checkout", async_context=True) is True
    assert recorder.config["service"] == "checkout"
    assert recorder.config["context_missing"] == "LOG_ERROR"
    assert "context" in recorder.config and patched == [True]
    assert tracing.init_tracing("checkout") is False  # configure once per process


def test_tracing_enabled_requires_a_deployed_environment(monkeypatch):
    monkeypatch.delenv("AWS_XRAY_DAEMON_ADDRESS", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("CHOPEE_TRACING_DISABLED", raising=False)
    assert tracing.tracing_enabled() is False
    monkeypatch.setenv("AWS_XRAY_DAEMON_ADDRESS", "127.0.0.1:2000")
    assert tracing.tracing_enabled() is True
    monkeypatch.setenv("CHOPEE_TRACING_DISABLED", "1")
    assert tracing.tracing_enabled() is False


def test_init_tracing_is_a_noop_when_disabled(monkeypatch):
    recorder = FakeRecorder()
    monkeypatch.setattr(tracing, "tracing_enabled", lambda: False)
    monkeypatch.setattr(tracing, "_recorder", lambda: recorder)
    assert tracing.init_tracing("checkout") is False
    assert recorder.config == {}


def test_annotate_order_uses_only_the_order_id(monkeypatch):
    recorder = FakeRecorder()
    enable(monkeypatch, recorder)
    tracing.annotate_order("o-1")
    assert recorder.segment.annotations == {"orderId": "o-1"}
    assert "customerId" not in recorder.segment.annotations


def test_current_trace_header_uses_the_active_segment(monkeypatch):
    recorder = FakeRecorder()
    enable(monkeypatch, recorder)
    assert tracing.current_trace_header() == (
        "Root=1-5f0f0f0f-abcdef0123456789abcdef01;Parent=53995c3f42cd8ad8;Sampled=1"
    )


def test_current_trace_header_falls_back_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing, "tracing_enabled", lambda: False)
    assert tracing.current_trace_header() == ""


def test_middleware_links_the_incoming_trace_and_records_status(monkeypatch):
    recorder = FakeRecorder()
    enable(monkeypatch, recorder)
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 202})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"x-amzn-trace-id", b"Root=1-5f0f0f0f-abcdef0123456789abcdef01;Parent=53995c3f42cd8ad8;Sampled=1")],
    }
    asyncio.run(tracing.XRayMiddleware(app)(scope, None, send))

    assert recorder.begun == ("checkout", "1-5f0f0f0f-abcdef0123456789abcdef01", "53995c3f42cd8ad8")
    assert recorder.segment.http["method"] == "POST"
    assert recorder.segment.http["status"] == 202
    assert recorder.ended is True
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.body"]


def test_middleware_is_transparent_when_tracing_is_disabled(monkeypatch):
    recorder = FakeRecorder()
    monkeypatch.setattr(tracing, "tracing_enabled", lambda: False)
    monkeypatch.setattr(tracing, "_recorder", lambda: recorder)
    called = []

    async def app(scope, receive, send):
        called.append(scope["method"])

    asyncio.run(tracing.XRayMiddleware(app)({"type": "http", "method": "GET", "headers": []}, None, None))
    assert called == ["GET"] and recorder.begun is None
