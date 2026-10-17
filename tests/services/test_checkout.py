import json
import time

import pytest
from botocore.exceptions import ClientError

from chopee import signing
from tests.services.conftest import KEY, SECRET, queued

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
                                   verifier=verifier, webhook_secret=SECRET))
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
                                   webhook_secret=SECRET, demo_gateway=False))
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
