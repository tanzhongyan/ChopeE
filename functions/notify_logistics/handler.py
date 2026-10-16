"""notify_logistics: SNS subscriber, logs a synthetic outcome once per event (plan 06 Section 5.5)."""
from __future__ import annotations

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

from chopee import keys
from chopee.logging import get_logger

CONSUMER = "logistics"
HANDLES = ("OrderPaid", )
log = get_logger("notify_logistics")
_ddb = None


def _table():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb").Table(os.environ.get("TABLE_NAME", keys.TABLE_NAME))
    return _ddb


def first_delivery(event_id: str) -> bool:
    """Conditional put CONSUMED#{consumer}#{eventId}; False when this event was already handled."""
    try:
        _table().put_item(
            Item={**keys.consumed_key(CONSUMER, event_id), "ttl": int(time.time()) + keys.EVENT_TTL_SECONDS},
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def lambda_handler(event, context):
    for record in event.get("Records", []):
        message = json.loads(record["Sns"]["Message"])
        if message.get("type") not in HANDLES:
            continue
        fields = {"eventId": message["eventId"], "eventType": message["type"], "orderId": message["orderId"],
                  "customerRef": message.get("customerRef")}
        if not first_delivery(message["eventId"]):
            log.info("duplicate_ignored", extra={"fields": fields})
            continue
        log.info("fulfilment_requested", extra={"fields": fields})


handler = lambda_handler  # Terraform entry point: handler.handler
