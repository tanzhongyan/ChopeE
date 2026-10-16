"""Outbox event builders (plan 06 Sections 5.1 and 5.5)."""
from __future__ import annotations

import time
import uuid

from . import keys

ORDER_PENDING_PAYMENT = "OrderPendingPayment"
ORDER_PAID = "OrderPaid"
ORDER_CANCELLED = "OrderCancelled"
ORDER_REJECTED = "OrderRejected"
EVENT_TYPES = (ORDER_PENDING_PAYMENT, ORDER_PAID, ORDER_CANCELLED, ORDER_REJECTED)

# Lambda event-source filter for outbox_relay (Streams).
OUTBOX_STREAM_FILTER = {
    "eventName": ["INSERT"],
    "dynamodb": {"Keys": {"PK": {"S": [{"prefix": "EVENT#"}]}}},
}


def outbox_item(event_type, order_id, customer_ref, status, occurred_at, now=None, event_id=None) -> dict:
    """Item to Put inside the same transaction as the state change."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type}")
    event_id = event_id or str(uuid.uuid4())
    now = int(now if now is not None else time.time())
    return {
        **keys.event_key(event_id),
        "eventId": event_id,
        "type": event_type,
        "orderId": order_id,
        "customerRef": customer_ref,
        "status": status,
        "occurredAt": occurred_at,
        "ttl": now + keys.EVENT_TTL_SECONDS,
    }


def sns_attributes(event_type: str) -> dict:
    return {"eventType": {"DataType": "String", "StringValue": event_type}}


LOGISTICS_FILTER = {"eventType": [ORDER_PAID]}
CUSTOMER_FILTER = {"eventType": [ORDER_PENDING_PAYMENT, ORDER_PAID, ORDER_CANCELLED, ORDER_REJECTED]}
