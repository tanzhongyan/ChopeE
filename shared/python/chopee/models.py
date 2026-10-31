"""Pydantic-free plain dataclasses for items, queue messages and API bodies."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Any

ORDER_PLACED = "ORDER_PLACED"
PAYMENT_RESULT = "PAYMENT_RESULT"
ORDER_EXPIRE = "ORDER_EXPIRE"
MESSAGE_TYPES = (ORDER_PLACED, PAYMENT_RESULT, ORDER_EXPIRE)

MAX_LINES = 10
MAX_QTY = 5


class InvalidMessage(ValueError):
    """Raised for malformed input: bad queue messages (worker -> DLQ) and invalid checkout lines (API -> 400)."""


@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int


def validate_lines(items: list[dict]) -> list[OrderLine]:
    """Validate checkout lines: 1-10 lines, qty 1-5, distinct SKUs."""
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_LINES:
        raise InvalidMessage("items must have 1-10 lines")
    lines: list[OrderLine] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise InvalidMessage("each line must be an object")
        sku, qty = raw.get("sku"), raw.get("quantity")
        if not isinstance(sku, str) or not sku or sku in seen:
            raise InvalidMessage("invalid or duplicate sku")
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
            raise InvalidMessage("quantity must be 1-5")
        seen.add(sku)
        lines.append(OrderLine(sku, qty))
    return lines


def is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value.lower()
    except (ValueError, AttributeError, TypeError):
        return False


@dataclass
class QueueMessage:
    """A message on chopee-orders.fifo plus its FIFO attributes (plan 06 Section 5.3)."""

    type: str
    body: dict[str, Any]
    group_id: str
    dedup_id: str | None = None

    def to_send_kwargs(self, queue_url: str) -> dict:
        kwargs = {
            "QueueUrl": queue_url,
            "MessageBody": json.dumps({"type": self.type, **self.body}, separators=(",", ":")),
            "MessageGroupId": self.group_id,
        }
        if self.dedup_id:
            kwargs["MessageDeduplicationId"] = self.dedup_id
        trace_id = self.body.get("traceId")
        if trace_id:
            kwargs["MessageSystemAttributes"] = {
                "AWSTraceHeader": {"DataType": "String", "StringValue": trace_id}
            }
        return kwargs


def order_placed(order_id, customer_id, items, accepted_at, trace_id="") -> QueueMessage:
    return QueueMessage(
        ORDER_PLACED,
        {
            "orderId": order_id,
            "customerId": customer_id,
            "items": [asdict(i) if isinstance(i, OrderLine) else i for i in items],
            "acceptedAt": accepted_at,
            "traceId": trace_id,
        },
        group_id=customer_id,
        dedup_id=order_id,
    )


def payment_result(order_id, customer_id, event_id, outcome, amount, currency) -> QueueMessage:
    return QueueMessage(
        PAYMENT_RESULT,
        {
            "orderId": order_id,
            "customerId": customer_id,
            "eventId": event_id,
            "outcome": outcome,
            "amount": amount,
            "currency": currency,
        },
        group_id=customer_id,
        dedup_id=event_id,
    )


_REQUIRED = {
    ORDER_PLACED: ("orderId", "customerId", "items", "acceptedAt"),
    PAYMENT_RESULT: ("orderId", "customerId", "eventId", "outcome", "amount", "currency"),
    ORDER_EXPIRE: ("orderId", "customerId", "scheduledAt"),
}


def parse_message(raw: str | bytes | dict) -> tuple[str, dict]:
    """Parse and validate a queue body. Anything unexpected raises InvalidMessage."""
    try:
        body = json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw)
    except (ValueError, TypeError) as exc:
        raise InvalidMessage("body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise InvalidMessage("body is not an object")
    mtype = body.get("type")
    if mtype not in MESSAGE_TYPES:
        raise InvalidMessage(f"unknown message type: {mtype!r}")
    missing = [f for f in _REQUIRED[mtype] if f not in body]
    if missing:
        raise InvalidMessage(f"{mtype} missing fields: {missing}")
    return mtype, body
