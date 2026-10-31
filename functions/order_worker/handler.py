"""order_worker: reserve stock, apply payment results, expire orders (plan 06 Section 5.4).

Every state transition is one TransactWriteItems. Unknown or malformed messages raise so the
FIFO redrive policy moves them to the DLQ after three attempts. A failure only blocks the rest of
its own message group (customer), so other customers in the same batch are not redelivered.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import boto3
from aws_lambda_powertools import Tracer
from aws_lambda_powertools.metrics import Metrics, MetricUnit
from aws_lambda_powertools.utilities.batch import SqsFifoPartialProcessor, process_partial_response
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.config import Config
from botocore.exceptions import ClientError

from chopee import events, keys, models
from chopee.logging import get_logger, pseudonymise

CONFIG = Config(max_pool_connections=64, retries={"mode": "standard"})
CATALOG_TTL_SECONDS = 60
SCHEDULE_PREFIX = "expire-"

log = get_logger("order_worker")
metrics = Metrics(namespace=os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "ChopeE"), service="order_worker")
tracer = Tracer(service="order_worker", disabled=not bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME")))
processor = SqsFifoPartialProcessor(skip_group_on_error=True)  # a failure only blocks its own customer group
processor.raise_on_entire_batch_failure = False  # report every item instead of failing the invocation

_ser, _de = TypeSerializer(), TypeDeserializer()
_clients: dict = {}
_catalog_cache: dict[str, tuple[float, dict]] = {}
_salt: str | None = None


# ---------------------------------------------------------------------------- plumbing
def _client(name: str):
    if name not in _clients:
        _clients[name] = boto3.client(name, config=CONFIG)
    return _clients[name]


def _table() -> str:
    return os.environ.get("TABLE_NAME", keys.TABLE_NAME)


def _expiry_minutes() -> int:
    return int(os.environ.get("EXPIRY_MINUTES", "15"))


def _customer_ref(sub: str) -> str:
    global _salt
    if _salt is None:
        _salt = os.environ.get("LOG_SALT") or _client("ssm").get_parameter(
            Name=os.environ.get("LOG_SALT_PARAM", "/chopee/log-salt"), WithDecryption=True
        )["Parameter"]["Value"]
    return pseudonymise(_salt, sub)


def reset_caches() -> None:
    """Test hook: clients, catalog cache and salt are per-process."""
    _clients.clear()
    _catalog_cache.clear()
    global _salt
    _salt = None


def _now() -> int:
    return int(time.time())


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ser_item(item: dict) -> dict:
    return {k: _ser.serialize(v) for k, v in item.items()}


def _put(item: dict, condition: str | None = "attribute_not_exists(PK)") -> dict:
    op = {"TableName": _table(), "Item": _ser_item(item)}
    if condition:
        op["ConditionExpression"] = condition
    return {"Put": op}


def _stock_update(sku: str, quantity: int, reserve: bool) -> dict:
    op = {
        "TableName": _table(),
        "Key": _ser_item(keys.stock_key(sku)),
        "UpdateExpression": "SET available = available " + ("- " if reserve else "+ ") + ":q",
        "ExpressionAttributeValues": {":q": {"N": str(quantity)}},
    }
    if reserve:
        op["ConditionExpression"] = "available >= :q"
    return {"Update": op}


def _transact(ops: list[dict]) -> list[str] | None:
    """Run the transaction. Returns None on success or the per-item cancellation codes."""
    try:
        _client("dynamodb").transact_write_items(TransactItems=ops)
        return None
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        return [r.get("Code", "None") for r in exc.response.get("CancellationReasons", [])]


def _only_conditional(codes: list[str] | None, allowed: set[int]) -> bool:
    """True when every failing item is a ConditionalCheckFailed at an index we expect."""
    if not codes:
        return False
    failed = [i for i, c in enumerate(codes) if c != "None"]
    return bool(failed) and all(codes[i] == "ConditionalCheckFailed" and i in allowed for i in failed)


def _get_order(order_id: str) -> dict | None:
    resp = _client("dynamodb").get_item(TableName=_table(), Key=_ser_item(keys.order_key(order_id)), ConsistentRead=True)
    return {k: _de.deserialize(v) for k, v in resp["Item"].items()} if "Item" in resp else None


def _product(sku: str) -> dict:
    cached = _catalog_cache.get(sku)
    if cached and time.time() - cached[0] < CATALOG_TTL_SECONDS:
        return cached[1]
    resp = _client("dynamodb").get_item(TableName=_table(), Key=_ser_item(keys.product_key(sku)))
    if "Item" not in resp:
        raise models.InvalidMessage(f"unknown sku {sku}")
    product = {k: _de.deserialize(v) for k, v in resp["Item"].items()}
    _catalog_cache[sku] = (time.time(), product)
    return product


def _outbox(event_type: str, order_id: str, customer_id: str, status: str) -> dict:
    return _put(events.outbox_item(event_type, order_id, _customer_ref(customer_id), status, _iso(_now())))


def _lines(order: dict) -> list[tuple[str, int]]:
    return [(i["sku"], int(i["quantity"])) for i in order["items"]]


# ---------------------------------------------------------------------------- scheduler
def _ensure_expiry_schedule(order_id: str, customer_id: str, expires_epoch: int) -> None:
    """CreateSchedule expire-{orderId}; an existing schedule (ConflictException) is fine.

    Runs before the reservation: if it keeps failing the message reaches the DLQ with no stock held.
    """
    at = max(expires_epoch, _now() + 10)
    payload = {
        "type": models.ORDER_EXPIRE,
        "orderId": order_id,
        "customerId": customer_id,
        "scheduledAt": _iso(at),
    }
    try:
        _client("scheduler").create_schedule(
            Name=f"{SCHEDULE_PREFIX}{order_id}",
            GroupName=os.environ.get("SCHEDULE_GROUP", "chopee-expiry"),
            ScheduleExpression=f"at({datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')})",
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            Target={
                "Arn": os.environ["ORDERS_QUEUE_ARN"],
                "RoleArn": os.environ["SCHEDULER_ROLE"],
                "Input": json.dumps(payload, separators=(",", ":")),
                "SqsParameters": {"MessageGroupId": customer_id},
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConflictException":
            raise


# ---------------------------------------------------------------------------- transitions
def handle_order_placed(body: dict) -> None:
    order_id, customer_id = body["orderId"], body["customerId"]
    lines = models.validate_lines(body["items"])  # InvalidMessage -> poison message
    priced, total = [], 0
    for line in lines:
        price = int(_product(line.sku)["price"])
        priced.append({"sku": line.sku, "quantity": line.quantity, "price": price})
        total += price * line.quantity

    now = _now()
    expires = now + _expiry_minutes() * 60
    created_at = body["acceptedAt"]
    order = {
        **keys.order_key(order_id),
        **keys.order_gsi1(customer_id, created_at),
        "orderId": order_id,
        "customerId": customer_id,
        "status": keys.ORDER_PENDING_PAYMENT,
        "items": priced,
        "total": total,
        "currency": "SGD",
        "createdAt": created_at,
        "expiresAt": _iso(expires),
    }
    _ensure_expiry_schedule(order_id, customer_id, expires)
    ops = [_put(order)]
    ops += [_stock_update(i["sku"], i["quantity"], reserve=True) for i in priced]
    ops.append(_outbox(events.ORDER_PENDING_PAYMENT, order_id, customer_id, keys.ORDER_PENDING_PAYMENT))
    last = len(ops) - 1
    codes = _transact(ops)

    if codes is None:
        metrics.add_metric("OrdersReserved", MetricUnit.Count, 1)
        log.info("order_transition", extra={"fields": {"orderId": order_id, "status": keys.ORDER_PENDING_PAYMENT}})
        return
    if codes[0] == "ConditionalCheckFailed":  # duplicate delivery: order already exists
        log.info("duplicate_ignored", extra={"fields": {"orderId": order_id, "type": models.ORDER_PLACED}})
        return
    if _only_conditional(codes, set(range(1, last))):  # out of stock on at least one line
        reject = {**order, "status": keys.ORDER_REJECTED, "reason": "OUT_OF_STOCK", "items": priced}
        reject.pop("expiresAt")
        rejected = _transact([_put(reject), _outbox(events.ORDER_REJECTED, order_id, customer_id, keys.ORDER_REJECTED)])
        if rejected is not None and rejected[0] != "ConditionalCheckFailed":
            raise RuntimeError(f"reject transaction cancelled: {rejected}")
        metrics.add_metric("OrdersRejected", MetricUnit.Count, 1)
        log.info("order_transition", extra={"fields": {"orderId": order_id, "status": keys.ORDER_REJECTED, "reason": "OUT_OF_STOCK"}})
        return
    raise RuntimeError(f"ORDER_PLACED transaction cancelled: {codes}")  # throttling / conflict -> retry


def handle_payment_result(body: dict) -> None:
    order_id, customer_id, event_id = body["orderId"], body["customerId"], body["eventId"]
    outcome = body["outcome"]
    if outcome == "succeeded":
        _payment_succeeded(order_id, customer_id, event_id, int(body["amount"]))
    elif outcome == "declined":
        _release(order_id, customer_id, "PAYMENT_DECLINED", event_id=event_id, amount=body.get("amount"), currency=body.get("currency"))
    else:
        raise models.InvalidMessage(f"unknown payment outcome {outcome!r}")


def _payment_succeeded(order_id: str, customer_id: str, event_id: str, amount: int) -> None:
    update = {
        "Update": {
            "TableName": _table(),
            "Key": _ser_item(keys.order_key(order_id)),
            "UpdateExpression": "SET #s = :paid",
            "ConditionExpression": "#s = :pending AND #t = :amount",
            "ExpressionAttributeNames": {"#s": "status", "#t": "total"},
            "ExpressionAttributeValues": _ser_item(
                {":paid": keys.ORDER_PAID, ":pending": keys.ORDER_PENDING_PAYMENT, ":amount": amount}
            ),
        }
    }
    ledger = _put(
        {**keys.payment_key(order_id, event_id), "outcome": "succeeded", "amount": amount, "currency": "SGD", "receivedAt": _iso(_now())}
    )
    codes = _transact([update, ledger, _outbox(events.ORDER_PAID, order_id, customer_id, keys.ORDER_PAID)])
    if codes is None:
        metrics.add_metric("OrdersPaid", MetricUnit.Count, 1)
        log.info("order_transition", extra={"fields": {"orderId": order_id, "status": keys.ORDER_PAID}})
        return
    if codes[1] == "ConditionalCheckFailed":
        log.info("duplicate_ignored", extra={"fields": {"orderId": order_id, "eventId": event_id}})
        return
    if codes[0] != "ConditionalCheckFailed":
        raise RuntimeError(f"PAYMENT_RESULT transaction cancelled: {codes}")
    order = _get_order(order_id)
    if order is None:
        raise models.InvalidMessage(f"payment for unknown order {order_id}")
    if order["status"] == keys.ORDER_PENDING_PAYMENT:
        raise models.InvalidMessage("payment amount does not match order total")
    recon = _put(
        {**keys.recon_key(order_id, event_id), "kind": "LATE_PAYMENT", "orderStatus": order["status"], "amount": amount, "receivedAt": _iso(_now())}
    )
    if _transact([recon]) is None:
        metrics.add_metric("LatePayments", MetricUnit.Count, 1)
        log.warning("late_payment", extra={"fields": {"orderId": order_id, "eventId": event_id, "orderStatus": order["status"]}})


def _release(order_id: str, customer_id: str, reason: str, event_id: str | None = None, amount=None, currency=None) -> None:
    """Cancel a pending order and return its stock, in one transaction (decline or expiry)."""
    order = _get_order(order_id)
    if order is None and event_id is None:  # expiry for an order that never reserved stock
        log.info("noop_no_order", extra={"fields": {"orderId": order_id, "reason": reason}})
        return
    if order is None:
        raise models.InvalidMessage(f"{reason} for unknown order {order_id}")
    if order["status"] != keys.ORDER_PENDING_PAYMENT:
        log.info("noop_not_pending", extra={"fields": {"orderId": order_id, "status": order["status"], "reason": reason}})
        return
    cancel = {
        "Update": {
            "TableName": _table(),
            "Key": _ser_item(keys.order_key(order_id)),
            "UpdateExpression": "SET #s = :cancelled, reason = :reason",
            "ConditionExpression": "#s = :pending",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": _ser_item(
                {":cancelled": keys.ORDER_CANCELLED, ":reason": reason, ":pending": keys.ORDER_PENDING_PAYMENT}
            ),
        }
    }
    ops = [cancel] + [_stock_update(s, q, reserve=False) for s, q in _lines(order)]
    if event_id:
        ops.append(
            _put({**keys.payment_key(order_id, event_id), "outcome": "declined", "amount": amount, "currency": currency, "receivedAt": _iso(_now())})
        )
    ops.append(_outbox(events.ORDER_CANCELLED, order_id, customer_id, keys.ORDER_CANCELLED))
    codes = _transact(ops)
    if codes is None:
        metrics.add_metric("OrdersCancelled", MetricUnit.Count, 1)
        log.info("order_transition", extra={"fields": {"orderId": order_id, "status": keys.ORDER_CANCELLED, "reason": reason}})
        return
    ledger_idx = len(ops) - 2 if event_id else None
    if codes[0] == "ConditionalCheckFailed" or (ledger_idx is not None and codes[ledger_idx] == "ConditionalCheckFailed"):
        log.info("noop_not_pending", extra={"fields": {"orderId": order_id, "reason": reason}})
        return
    raise RuntimeError(f"{reason} transaction cancelled: {codes}")


def handle_order_expire(body: dict) -> None:
    _release(body["orderId"], body["customerId"], "PAYMENT_TIMEOUT")


HANDLERS = {
    models.ORDER_PLACED: handle_order_placed,
    models.PAYMENT_RESULT: handle_payment_result,
    models.ORDER_EXPIRE: handle_order_expire,
}


@tracer.capture_method
def process_message(raw: str) -> None:
    mtype, body = models.parse_message(raw)  # raises InvalidMessage on anything unexpected
    tracer.put_annotation("orderId", body["orderId"])
    HANDLERS[mtype](body)


def record_handler(record) -> None:
    try:
        process_message(record.body)
    except models.InvalidMessage:
        log.error("poison_message", extra={"fields": {"messageId": record.message_id}})
        raise


@metrics.log_metrics
@tracer.capture_lambda_handler
def lambda_handler(event, context):
    return process_partial_response(
        event=event, record_handler=record_handler, processor=processor, context=context
    )


handler = lambda_handler  # Terraform entry point: handler.handler
