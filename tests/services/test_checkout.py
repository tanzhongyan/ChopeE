import json
import time

import pytest
from botocore.exceptions import ClientError

from chopee import signing
from tests.services.conftest import KEY, SALT, SECRET, queued

ITEMS = {"items": [{"sku": "TEE-01", "quantity": 2}]}


def put_order(aws, order_id=KEY, sub="user-1", status="PENDING_PAYMENT", total=3000):
    aws.table.put_item(Item={
        "PK": f"ORDER#{order_id}", "SK": "META", "customerId": sub, "status": status, "items": [{"sku": "TEE-01", "quantity": 2}],
        "total": total, "currency": "SGD", "createdAt": "2026-10-16T10:00:00Z", "expiresAt": "2026-10-16T10:15:00Z",
        "GSI1PK": f"CUSTOMER#{sub}", "GSI1SK": "ORDER#2026-10-16T10:00:00Z",
    })


def signed(body: dict, secret=SECRET, now=None):
    raw = json.dumps(body, separators=(",", ":"))
    return raw, {signing.HEADER: signing.sign(secret, raw, now), "Content-Type": "application/json"}


def event(order_id=KEY, outcome="succeeded", event_id="evt-1", amount=3000, currency="SGD"):
    return {"eventId": event_id, "orderId": order_id, "outcome": outcome, "amount": amount, "currency": currency,
            "occurredAt": "2026-10-16T10:01:00Z"}


def test_checkout_202_enqueues_then_200_for_same_key(checkout_client, seeded, auth):
    h = {**auth(), "Idempotency-Key": KEY}
    r = checkout_client.post("/api/checkout", json=ITEMS, headers=h)
    assert r.status_code == 202 and r.json() == {"orderId": KEY, "status": "QUEUED"}
    r = checkout_client.post("/api/checkout", json=ITEMS, headers=h)  # retry before the worker ran: still queued, deduped by SQS
    assert r.status_code == 202
    msgs = queued(seeded)
    assert len(msgs) == 1
    assert msgs[0]["type"] == "ORDER_PLACED" and msgs[0]["orderId"] == KEY and msgs[0]["customerId"] == "user-1"
    assert msgs[0]["items"] == [{"sku": "TEE-01", "quantity": 2}]
    # worker has since created the order: same key now returns 200 with the real status
    put_order(seeded)
    r = checkout_client.post("/api/checkout", json=ITEMS, headers=h)
    assert r.status_code == 200 and r.json() == {"orderId": KEY, "status": "PENDING_PAYMENT"}
    assert queued(seeded) == []


def test_checkout_409_when_key_belongs_to_another_customer(checkout_client, seeded, auth):
    put_order(seeded, sub="someone-else")
    r = checkout_client.post("/api/checkout", json=ITEMS, headers={**auth("user-1"), "Idempotency-Key": KEY})
    assert r.status_code == 409 and queued(seeded) == []


@pytest.mark.parametrize(
    "key,body",
    [
        ("not-a-uuid", ITEMS),
        (KEY, {"items": []}),
        (KEY, {"items": [{"sku": "TEE-01", "quantity": 6}]}),
        (KEY, {"items": [{"sku": "TEE-01", "quantity": 1}] * 2}),
        (KEY, {"items": [{"sku": f"S{i}", "quantity": 1} for i in range(11)]}),
        (KEY, {"items": [1]}),
        (KEY, {}),
    ],
)
def test_checkout_400_on_invalid_input(checkout_client, auth, key, body):
    assert checkout_client.post("/api/checkout", json=body, headers={**auth(), "Idempotency-Key": key}).status_code == 400


def test_checkout_requires_jwt(checkout_client):
    assert checkout_client.post("/api/checkout", json=ITEMS, headers={"Idempotency-Key": KEY}).status_code == 401


def test_checkout_503_with_retry_after_when_sqs_fails(seeded, verifier, auth):
    from fastapi.testclient import TestClient
    from services.checkout.app import create_app

    class Broken:
        def send_message(self, **_):
            raise ClientError({"Error": {"Code": "ServiceUnavailable", "Message": "x"}}, "SendMessage")

    client = TestClient(create_app(table=seeded.table, sqs=Broken(), queue_url=seeded.queue_url,
                                   verifier=verifier, webhook_secret=SECRET, log_salt=SALT))
    r = client.post("/api/checkout", json=ITEMS, headers={**auth(), "Idempotency-Key": KEY})
    assert r.status_code == 503 and r.headers["Retry-After"] == "1"


def test_orders_read_is_owner_only(checkout_client, seeded, auth):
    put_order(seeded)
    r = checkout_client.get(f"/api/orders/{KEY}", headers=auth())
    assert r.status_code == 200
    assert r.json() == {"orderId": KEY, "status": "PENDING_PAYMENT", "reason": None, "items": [{"sku": "TEE-01", "quantity": 2}],
                        "total": 3000, "createdAt": "2026-10-16T10:00:00Z", "expiresAt": "2026-10-16T10:15:00Z"}
    assert checkout_client.get(f"/api/orders/{KEY}", headers=auth("other")).status_code == 404
    assert checkout_client.get("/api/orders/33333333-3333-4333-8333-333333333333", headers=auth()).status_code == 404
    assert checkout_client.get(f"/api/orders/{KEY}").status_code == 401


def test_order_history_latest_first_for_caller_only(checkout_client, seeded, auth):
    for i in range(25):
        oid = f"00000000-0000-4000-8000-{i:012d}"
        put_order(seeded, order_id=oid)
        seeded.table.update_item(Key={"PK": f"ORDER#{oid}", "SK": "META"}, UpdateExpression="SET GSI1SK = :s",
                                 ExpressionAttributeValues={":s": f"ORDER#2026-10-16T10:{i:02d}:00Z"})
    put_order(seeded, order_id=KEY, sub="other")
    r = checkout_client.get("/api/orders", headers=auth())
    ids = [o["orderId"] for o in r.json()]
    assert len(ids) == 20 and ids[0].endswith("000000000024") and KEY not in ids


def test_webhook_accepts_valid_signature_once_per_event(checkout_client, seeded):
    put_order(seeded)
    raw, headers = signed(event())
    r = checkout_client.post("/api/webhooks/payment", content=raw, headers=headers)
    assert r.status_code == 200 and r.json() == {"received": True}
    # gateway retry of the same eventId: SQS FIFO deduplicates, so a single message exists
    assert checkout_client.post("/api/webhooks/payment", content=raw, headers=headers).status_code == 200
    msgs = queued(seeded)
    assert len(msgs) == 1
    assert msgs[0]["type"] == "PAYMENT_RESULT" and msgs[0]["customerId"] == "user-1"
    assert msgs[0]["eventId"] == "evt-1" and msgs[0]["outcome"] == "succeeded" and msgs[0]["amount"] == 3000


def test_webhook_rejects_bad_stale_and_missing_signatures(checkout_client, seeded, capsys):
    put_order(seeded)
    raw, _ = signed(event())
    bad = {signing.HEADER: signing.sign("wrong-secret", raw)}
    stale = {signing.HEADER: signing.sign(SECRET, raw, now=int(time.time()) - 301)}
    for headers in (bad, stale, {}, {signing.HEADER: "garbage"}):
        assert checkout_client.post("/api/webhooks/payment", content=raw, headers=headers).status_code == 401
    tampered_headers = {signing.HEADER: signing.sign(SECRET, raw)}
    assert checkout_client.post("/api/webhooks/payment", content=raw.replace("3000", "1"), headers=tampered_headers).status_code == 401
    assert queued(seeded) == []
    assert capsys.readouterr().out.count("WebhookSignatureFailures") >= 5  # EMF metric emitted per failure


def test_webhook_404_unknown_order_and_422_mismatch(checkout_client, seeded):
    put_order(seeded)
    raw, h = signed(event(order_id="33333333-3333-4333-8333-333333333333"))
    assert checkout_client.post("/api/webhooks/payment", content=raw, headers=h).status_code == 404
    for body in (event(amount=1), event(currency="USD")):
        raw, h = signed(body)
        assert checkout_client.post("/api/webhooks/payment", content=raw, headers=h).status_code == 422
    raw, h = signed({"eventId": "x"})
    assert checkout_client.post("/api/webhooks/payment", content=raw, headers=h).status_code == 400
    assert queued(seeded) == []


def test_demo_pay_uses_the_same_verify_and_enqueue_path(checkout_client, seeded, auth):
    put_order(seeded)
    r = checkout_client.post(f"/api/demo/pay/{KEY}", json={"outcome": "declined"}, headers=auth())
    assert r.status_code == 200
    msgs = queued(seeded)
    assert len(msgs) == 1 and msgs[0]["outcome"] == "declined" and msgs[0]["customerId"] == "user-1"
    assert checkout_client.post(f"/api/demo/pay/{KEY}", json={"outcome": "maybe"}, headers=auth()).status_code == 400
    assert checkout_client.post(f"/api/demo/pay/{KEY}", json={"outcome": "succeeded"}, headers=auth("other")).status_code == 404
    assert checkout_client.post(f"/api/demo/pay/{KEY}", json={"outcome": "succeeded"}).status_code == 401


def test_demo_pay_disabled_without_flag(seeded, verifier, auth):
    from fastapi.testclient import TestClient
    from services.checkout.app import create_app

    put_order(seeded)
    client = TestClient(create_app(table=seeded.table, sqs=seeded.sqs, queue_url=seeded.queue_url, verifier=verifier,
                                   webhook_secret=SECRET, demo_gateway=False, log_salt=SALT))
    assert client.post(f"/api/demo/pay/{KEY}", json={"outcome": "succeeded"}, headers=auth()).status_code == 404


def test_log_message_names_used_by_report_queries(checkout_client, seeded, auth):
    import logging

    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("checkout")
    handler = Capture()
    logger.addHandler(handler)
    try:
        raw, _ = signed(event())
        checkout_client.post("/api/webhooks/payment", content=raw, headers={signing.HEADER: "t=1,v1=bad"})
        checkout_client.post("/api/checkout", json=ITEMS, headers={**auth(), "Idempotency-Key": KEY})
    finally:
        logger.removeHandler(handler)
    names = {r.getMessage() for r in records}
    assert {"webhook_signature_failure", "http_request", "order_transition"} <= names
    assert "user-1" not in json.dumps([getattr(r, "fields", {}) for r in records])  # customerRef only


def test_checkout_app_installs_xray_middleware(checkout_app):
    from chopee.tracing import XRayMiddleware

    assert any(m.cls is XRayMiddleware for m in checkout_app.user_middleware)


def test_checkout_annotates_order_id_not_customer_id(checkout_client, auth, monkeypatch):
    import services.checkout.app as appmod

    seen = []
    monkeypatch.setattr(appmod, "annotate_order", seen.append)
    r = checkout_client.post("/api/checkout", json=ITEMS, headers={**auth(), "Idempotency-Key": KEY})
    assert r.status_code == 202
    assert seen == [KEY]


def test_order_message_carries_the_trace_header():
    from chopee import models

    msg = models.order_placed("o-1", "u-1", [models.OrderLine("TEE-01", 1)], "2026-10-16T10:00:00Z",
                              "Root=1-aaaaaaaa-bbbbbbbbbbbbbbbbbbbbbbbb;Parent=cccccccccccccccc;Sampled=1")
    kwargs = msg.to_send_kwargs("q")
    assert kwargs["MessageSystemAttributes"]["AWSTraceHeader"]["StringValue"].startswith("Root=")


def test_checkout_uses_the_active_segment_header(checkout_client, seeded, auth, monkeypatch):
    import services.checkout.app as appmod

    header = "Root=1-5f0f0f0f-abcdef0123456789abcdef01;Parent=53995c3f42cd8ad8;Sampled=1"
    monkeypatch.setattr(appmod, "current_trace_header", lambda: header)
    r = checkout_client.post("/api/checkout", json=ITEMS, headers={**auth(), "Idempotency-Key": KEY})
    assert r.status_code == 202
    assert queued(seeded)[0]["traceId"] == header


def test_read_order_is_async_and_annotates_order_id(checkout_app, checkout_client, seeded, auth, monkeypatch):
    import inspect

    import services.checkout.app as appmod

    route = next(r for r in checkout_app.routes if getattr(r, "path", None) == "/api/orders/{order_id}")
    assert inspect.iscoroutinefunction(route.endpoint)
    put_order(seeded)
    seen = []
    monkeypatch.setattr(appmod, "annotate_order", seen.append)
    r = checkout_client.get(f"/api/orders/{KEY}", headers=auth())
    assert r.status_code == 200 and seen == [KEY]


def test_webhook_annotates_order_id_only_after_signature_verification(checkout_client, seeded, monkeypatch):
    import services.checkout.app as appmod

    put_order(seeded)
    seen = []
    monkeypatch.setattr(appmod, "annotate_order", seen.append)

    raw, headers = signed(event(), secret="wrong-secret")
    r = checkout_client.post("/api/webhooks/payment", content=raw, headers=headers)
    assert r.status_code == 401 and seen == []

    raw, headers = signed(event())
    r = checkout_client.post("/api/webhooks/payment", content=raw, headers=headers)
    assert r.status_code == 200 and seen == [KEY]


# ---- plan 05c API-1..API-8 ----
class RecordingTable:
    """Delegates to the real table and records get_item kwargs."""

    def __init__(self, table):
        self._t = table
        self.gets = []

    def get_item(self, **kw):
        self.gets.append(kw)
        return self._t.get_item(**kw)

    def __getattr__(self, name):
        return getattr(self._t, name)


def make_client(seeded, verifier, table=None, sqs=None, **kw):
    from fastapi.testclient import TestClient
    from services.checkout.app import create_app

    return TestClient(create_app(table=table or seeded.table, sqs=sqs or seeded.sqs, queue_url=seeded.queue_url,
                                 verifier=verifier, webhook_secret=SECRET, demo_gateway=True, log_salt=SALT, **kw))


class BrokenSqs:
    def send_message(self, **_):
        raise ClientError({"Error": {"Code": "ServiceUnavailable", "Message": "x"}}, "SendMessage")


def test_every_order_read_is_strongly_consistent(seeded, verifier, auth):
    rec = RecordingTable(seeded.table)
    client = make_client(seeded, verifier, table=rec)
    put_order(seeded)
    client.post("/api/checkout", json=ITEMS, headers={**auth(), "Idempotency-Key": KEY})  # idempotency check
    client.get(f"/api/orders/{KEY}", headers=auth())
    raw, h = signed(event())
    assert client.post("/api/webhooks/payment", content=raw, headers=h).status_code == 200
    assert client.post(f"/api/demo/pay/{KEY}", json={"outcome": "declined"}, headers=auth()).status_code == 200
    assert len(rec.gets) >= 5
    assert all(g.get("ConsistentRead") is True for g in rec.gets)


def test_authentication_does_not_block_the_event_loop(seeded, auth):
    import asyncio

    import httpx
    from services.checkout.app import create_app

    class SlowVerifier:
        def subject(self, authorization):
            time.sleep(0.3)
            return "user-1"

        def _keys(self, kid=None):
            return {}

    app = create_app(table=seeded.table, sqs=seeded.sqs, queue_url=seeded.queue_url, verifier=SlowVerifier(),
                     webhook_secret=SECRET, demo_gateway=True, log_salt=SALT)
    put_order(seeded)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            started = time.perf_counter()
            rs = await asyncio.gather(*[c.get(f"/api/orders/{KEY}", headers={"Authorization": "Bearer x"}) for _ in range(2)])
            return time.perf_counter() - started, rs

    elapsed, rs = asyncio.run(run())
    assert [r.status_code for r in rs] == [200, 200]
    assert elapsed < 0.55  # ~1x the 0.3s sleep, not 2x


def test_jwks_warmup_runs_at_startup_and_tolerates_failure(seeded, verifier):
    from fastapi.testclient import TestClient
    from services.checkout.app import create_app

    calls = []

    class Warm:
        def _keys(self, kid=None):
            calls.append(1)
            raise RuntimeError("jwks down")

        def subject(self, authorization):
            return "user-1"

    app = create_app(table=seeded.table, sqs=seeded.sqs, queue_url=seeded.queue_url, verifier=Warm(),
                     webhook_secret=SECRET, log_salt=SALT)
    with TestClient(app) as client:  # startup must not crash
        assert client.get("/api/healthz").status_code == 200
    assert calls == [1]


def test_webhook_and_demo_pay_503_with_retry_after_when_sqs_fails(seeded, verifier, auth):
    client = make_client(seeded, verifier, sqs=BrokenSqs())
    put_order(seeded)
    raw, h = signed(event())
    r = client.post("/api/webhooks/payment", content=raw, headers=h)
    assert r.status_code == 503 and r.headers["Retry-After"] == "1"
    r = client.post(f"/api/demo/pay/{KEY}", json={"outcome": "succeeded"}, headers=auth())
    assert r.status_code == 503 and r.headers["Retry-After"] == "1"


def test_enqueue_failed_log_uses_customer_ref_only(seeded, verifier, caplog):
    import logging

    caplog.set_level(logging.INFO)
    client = make_client(seeded, verifier, sqs=BrokenSqs())
    put_order(seeded)
    raw, h = signed(event())
    client.post("/api/webhooks/payment", content=raw, headers=h)
    recs = [r for r in caplog.records if r.getMessage() == "enqueue_failed"]
    assert len(recs) == 1
    fields = json.dumps(recs[0].fields)
    assert "customerRef" in fields and "user-1" not in fields and KEY in fields


def test_demo_pay_409_unless_pending_but_webhook_still_records_late_payment(checkout_client, seeded, auth):
    put_order(seeded, status="PAID")
    r = checkout_client.post(f"/api/demo/pay/{KEY}", json={"outcome": "succeeded"}, headers=auth())
    assert r.status_code == 409 and r.json() == {"error": "order not pending"}
    assert queued(seeded) == []
    raw, h = signed(event())
    assert checkout_client.post("/api/webhooks/payment", content=raw, headers=h).status_code == 200
    assert len(queued(seeded)) == 1


def test_claim_blocks_second_customer_before_worker_runs(checkout_client, seeded, auth):
    first = checkout_client.post("/api/checkout", json=ITEMS, headers={**auth("user-1"), "Idempotency-Key": KEY})
    second = checkout_client.post("/api/checkout", json=ITEMS, headers={**auth("user-2"), "Idempotency-Key": KEY})
    assert first.status_code == 202
    assert second.status_code == 409 and second.json() == {"error": "idempotency key belongs to another customer"}
    msgs = queued(seeded)
    assert len(msgs) == 1 and msgs[0]["customerId"] == "user-1"
    claim = seeded.table.get_item(Key={"PK": f"ORDER#{KEY}", "SK": "CLAIM"})["Item"]
    assert claim["customerId"] == "user-1" and int(claim["ttl"]) > time.time() + 3000


def test_same_customer_retry_after_claim_is_202_not_409(checkout_client, seeded, auth):
    h = {**auth("user-1"), "Idempotency-Key": KEY}
    assert checkout_client.post("/api/checkout", json=ITEMS, headers=h).status_code == 202
    assert checkout_client.post("/api/checkout", json=ITEMS, headers=h).status_code == 202
    assert len(queued(seeded)) == 1


def test_claim_write_failure_is_503_with_retry_after(seeded, verifier, auth):
    class FailingPut(RecordingTable):
        def put_item(self, **kw):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "PutItem")

    client = make_client(seeded, verifier, table=FailingPut(seeded.table))
    r = client.post("/api/checkout", json=ITEMS, headers={**auth(), "Idempotency-Key": KEY})
    assert r.status_code == 503 and r.headers["Retry-After"] == "1"
    assert queued(seeded) == []


def test_webhook_and_demo_pay_verify_signature_exactly_once(checkout_client, seeded, auth, monkeypatch):
    put_order(seeded)
    calls = []
    real = signing.verify
    monkeypatch.setattr(signing, "verify", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    raw, h = signed(event())
    assert checkout_client.post("/api/webhooks/payment", content=raw, headers=h).status_code == 200
    assert len(calls) == 1
    calls.clear()
    assert checkout_client.post(f"/api/demo/pay/{KEY}", json={"outcome": "declined"}, headers=auth()).status_code == 200
    assert len(calls) == 1
