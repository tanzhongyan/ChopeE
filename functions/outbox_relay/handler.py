"""outbox_relay: DynamoDB Streams (outbox items only) -> SNS chopee-order-events (plan 06 Section 5.5)."""
from __future__ import annotations

import json
import os

import boto3
from boto3.dynamodb.types import TypeDeserializer
from botocore.config import Config

from chopee import events
from chopee.logging import get_logger

log = get_logger("outbox_relay")
_de = TypeDeserializer()
_sns = None


def _client():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns", config=Config(max_pool_connections=32, retries={"mode": "standard"}))
    return _sns


def is_outbox_insert(record: dict) -> bool:
    """Defence in depth: the event source mapping already filters to this."""
    pk = record.get("dynamodb", {}).get("Keys", {}).get("PK", {}).get("S", "")
    return record.get("eventName") == "INSERT" and pk.startswith("EVENT#")


def publish(record: dict) -> None:
    image = {k: _de.deserialize(v) for k, v in record["dynamodb"]["NewImage"].items()}
    message = {k: image[k] for k in ("eventId", "type", "orderId", "customerRef", "status", "occurredAt") if k in image}
    _client().publish(
        TopicArn=os.environ["TOPIC_ARN"],
        Message=json.dumps(message, separators=(",", ":")),
        MessageAttributes=events.sns_attributes(message["type"]),
    )
    log.info("event_published", extra={"fields": {"eventId": message["eventId"], "eventType": message["type"]}})


def lambda_handler(event, context):
    """Stop at the first failure and report it: Streams retries from that record onward."""
    for record in event.get("Records", []):
        if not is_outbox_insert(record):
            continue
        try:
            publish(record)
        except Exception:
            log.exception("publish_failed")
            return {"batchItemFailures": [{"itemIdentifier": record["dynamodb"]["SequenceNumber"]}]}
    return {"batchItemFailures": []}
