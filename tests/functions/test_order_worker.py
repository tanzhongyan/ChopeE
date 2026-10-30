"""M1 acceptance checks for order_worker (plan 06 Sections 5.4 and 7)."""
from __future__ import annotations

import json

import pytest

from tests.functions.conftest import load_handler, seed_product, sqs_event, stock_of

ACCEPTED = "2026-10-16T10:00:00Z"


@pytest.fixture
def w(worker_env):
    mod = load_handler("order_worker")
    mod.reset_caches()
    seed_product(worker_env.table, "SKU-A", price=500, stock=10)
    seed_product(worker_env.table, "LIMITED-01", price=1000, stock=50)
    return mod


def placed(order_id, cust="user-1", sku="SKU-A", qty=2):
    return {"type": "ORDER_PLACED", "orderId": order_id, "customerId": cust,
            "items": [{"sku": sku, "quantity": qty}], "acceptedAt": ACCEPTED, "traceId": ""}


def pay(order_id, event_id, outcome="succeeded", amount=1000, cust="user-1"):
    return {"type": "PAYMENT_RESULT", "orderId": order_id, "customerId": cust, "eventId": event_id,
            "outcome": outcome, "amount": amount, "currency": "SGD"}


def expire(order_id, cust="user-1"):
    return {"type": "ORDER_EXPIRE", "orderId": order_id, "customerId": cust, "scheduledAt": ACCEPTED}


def run(w, *bodies):
    return w.lambda_handler(sqs_event(*bodies), None)


def order(aws, oid):
    return aws.table.get_item(Key={"PK": f"ORDER#{oid}", "SK": "META"}).get("Item")


def events_of(aws):
    items = aws.table.scan()["Items"]
    return sorted(i["type"] for i in items if i["PK"].startswith("EVENT#"))


def test_worker_annotates_order_id_only(w, monkeypatch):
    seen = {}
    monkeypatch.setattr(w.tracer, "put_annotation", lambda key, value: seen.__setitem__(key, value))
    monkeypatch.setitem(w.HANDLERS, "ORDER_PLACED", lambda body: None)
    w.process_message(json.dumps(placed("o-1")))
    assert seen == {"orderId": "o-1"}
    assert "customerId" not in seen


def test_order_placed_reserves_stock_and_schedules_expiry(w, worker_env, scheduler):
    assert run(w, placed("o1")) == {"batchItemFailures": []}
    o = order(worker_env, "o1")
    assert o["status"] == "PENDING_PAYMENT" and o["total"] == 1000 and o["currency"] == "SGD"
    assert o["GSI1PK"] == "CUSTOMER#user-1" and o["expiresAt"]
    assert stock_of(worker_env.table, "SKU-A") == 8
    assert events_of(worker_env) == ["OrderPendingPayment"]
    sched = scheduler.get_schedule(Name="expire-o1", GroupName="chopee-expiry")
    assert sched["ActionAfterCompletion"] == "DELETE"
    assert sched["Target"]["SqsParameters"]["MessageGroupId"] == "user-1"
    assert json.loads(sched["Target"]["Input"])["type"] == "ORDER_EXPIRE"


def test_duplicate_order_placed_creates_one_order(w, worker_env):
    run(w, placed("o1"))
    run(w, placed("o1"))
    assert stock_of(worker_env.table, "SKU-A") == 8
    assert events_of(worker_env) == ["OrderPendingPayment"]


def test_duplicate_recreates_missing_schedule(w, worker_env, scheduler):
    run(w, placed("o1"))
    scheduler.delete_schedule(Name="expire-o1", GroupName="chopee-expiry")
    run(w, placed("o1"))
    assert scheduler.get_schedule(Name="expire-o1", GroupName="chopee-expiry")["Name"] == "expire-o1"


def test_competing_orders_never_oversell_limited_stock(w, worker_env):
    for i in range(60):  # 60 customers x qty 1 against 50 units
        assert run(w, placed(f"c{i}", cust=f"u{i}", sku="LIMITED-01", qty=1)) == {"batchItemFailures": []}
    assert stock_of(worker_env.table, "LIMITED-01") == 0
    statuses = [order(worker_env, f"c{i}")["status"] for i in range(60)]
    assert statuses.count("PENDING_PAYMENT") == 50 and statuses.count("REJECTED") == 10
    rejected = order(worker_env, "c59")
    assert rejected["reason"] == "OUT_OF_STOCK"


def test_rejected_order_leaves_other_lines_untouched(w, worker_env):
    seed_product(worker_env.table, "SKU-B", stock=1)
    msg = placed("o1")
    msg["items"] = [{"sku": "SKU-A", "quantity": 2}, {"sku": "SKU-B", "quantity": 3}]
    run(w, msg)
    assert order(worker_env, "o1")["status"] == "REJECTED"
    assert stock_of(worker_env.table, "SKU-A") == 10 and stock_of(worker_env.table, "SKU-B") == 1
    assert events_of(worker_env) == ["OrderRejected"]
    run(w, msg)  # duplicate rejected delivery is harmless
    assert events_of(worker_env) == ["OrderRejected"]


def test_payment_success_marks_paid_once(w, worker_env):
    run(w, placed("o1"))
    run(w, pay("o1", "e1"))
    run(w, pay("o1", "e1"))  # gateway retry
    o = order(worker_env, "o1")
    assert o["status"] == "PAID"
    assert events_of(worker_env) == ["OrderPaid", "OrderPendingPayment"]
    assert worker_env.table.get_item(Key={"PK": "ORDER#o1", "SK": "PAYMENT#e1"})["Item"]["outcome"] == "succeeded"


def test_decline_releases_stock_once(w, worker_env):
    run(w, placed("o1"))
    run(w, pay("o1", "e1", outcome="declined"))
    run(w, pay("o1", "e1", outcome="declined"))
    run(w, pay("o1", "e2", outcome="declined"))  # different event id, order no longer pending
    o = order(worker_env, "o1")
    assert (o["status"], o["reason"]) == ("CANCELLED", "PAYMENT_DECLINED")
    assert stock_of(worker_env.table, "SKU-A") == 10
    assert events_of(worker_env).count("OrderCancelled") == 1


def test_expiry_releases_stock_once(w, worker_env):
    run(w, placed("o1"))
    run(w, expire("o1"))
    run(w, expire("o1"))
    o = order(worker_env, "o1")
    assert (o["status"], o["reason"]) == ("CANCELLED", "PAYMENT_TIMEOUT")
    assert stock_of(worker_env.table, "SKU-A") == 10


def test_expiry_after_payment_is_noop(w, worker_env):
    run(w, placed("o1"))
    run(w, pay("o1", "e1"))
    run(w, expire("o1"))
    assert order(worker_env, "o1")["status"] == "PAID"
    assert stock_of(worker_env.table, "SKU-A") == 8


def test_success_vs_expiry_race_finalises_once(w, worker_env):
    for first, second in (("pay", "expire"), ("expire", "pay")):
        oid = f"race-{first}"
        run(w, placed(oid, cust="r1"))
        before = stock_of(worker_env.table, "SKU-A")
        msgs = {"pay": pay(oid, f"e-{oid}", cust="r1"), "expire": expire(oid, cust="r1")}
        run(w, msgs[first])
        run(w, msgs[second])
        status = order(worker_env, oid)["status"]
        assert status == ("PAID" if first == "pay" else "CANCELLED")
        assert stock_of(worker_env.table, "SKU-A") == (before if first == "pay" else before + 2)


def test_late_payment_after_cancellation_writes_recon(w, worker_env):
    run(w, placed("o1"))
    run(w, expire("o1"))
    run(w, pay("o1", "late1"))
    recon = worker_env.table.get_item(Key={"PK": "ORDER#o1", "SK": "RECON#late1"})["Item"]
    assert recon["kind"] == "LATE_PAYMENT"
    assert order(worker_env, "o1")["status"] == "CANCELLED"
    assert stock_of(worker_env.table, "SKU-A") == 10
    run(w, pay("o1", "late1"))  # redelivery of the same late event is harmless


def test_amount_mismatch_on_pending_order_goes_to_dlq_path(w, worker_env):
    run(w, placed("o1"))
    result = run(w, pay("o1", "e1", amount=1))
    assert result["batchItemFailures"] == [{"itemIdentifier": "m0"}]
    assert order(worker_env, "o1")["status"] == "PENDING_PAYMENT"


@pytest.mark.parametrize(
    "body",
    [
        {"type": "NOPE", "orderId": "x"},
        {"type": "ORDER_PLACED", "orderId": "x"},
        "not json",
        "[1, 2]",
    ],
)
def test_unknown_or_malformed_message_raises(w, body):
    result = run(w, body)
    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]}


def test_unknown_sku_is_poison(w, worker_env):
    assert run(w, placed("o1", sku="NO-SUCH"))["batchItemFailures"] == [{"itemIdentifier": "m0"}]
    assert order(worker_env, "o1") is None


def test_fifo_batch_stops_after_first_failure(w):
    result = run(w, placed("o1"), {"type": "BAD"}, placed("o2"))
    assert [f["itemIdentifier"] for f in result["batchItemFailures"]] == ["m1", "m2"]


def test_poison_message_reaches_dlq_after_three_receives(worker_env):
    sqs = worker_env.sqs
    sqs.send_message(QueueUrl=worker_env.queue_url, MessageBody='{"type":"BAD"}', MessageGroupId="g")
    for _ in range(3):
        msgs = sqs.receive_message(QueueUrl=worker_env.queue_url, VisibilityTimeout=0, MaxNumberOfMessages=1).get("Messages", [])
        assert msgs
    msgs = sqs.receive_message(QueueUrl=worker_env.queue_url, MaxNumberOfMessages=1).get("Messages", [])
    dlq = sqs.receive_message(QueueUrl=worker_env.dlq_url, MaxNumberOfMessages=1).get("Messages", [])
    assert msgs == [] and len(dlq) == 1


def test_no_pii_in_outbox(w, worker_env):
    run(w, placed("o1", cust="secret-sub-123"))
    ev = [i for i in worker_env.table.scan()["Items"] if i["PK"].startswith("EVENT#")][0]
    assert "secret-sub-123" not in json.dumps(ev, default=str) and len(ev["customerRef"]) == 12
