#!/usr/bin/env python3
"""Send a poison message to the orders FIFO queue to demonstrate the DLQ alarm (plan 06 Section 5.3)."""
from __future__ import annotations

import argparse
import json
import uuid

KINDS = ("unknown-type", "malformed")


def build_message(kind: str = "unknown-type") -> dict:
    """Return SendMessage kwargs (minus QueueUrl). Its own group keeps other customers flowing."""
    if kind == "unknown-type":
        body = json.dumps({"type": "POISON_DEMO", "orderId": str(uuid.uuid4())})
    elif kind == "malformed":
        body = "{not json"
    else:
        raise ValueError(f"kind must be one of {KINDS}")
    return {
        "MessageBody": body,
        "MessageGroupId": f"poison-{uuid.uuid4().hex[:8]}",
        "MessageDeduplicationId": str(uuid.uuid4()),
    }


def inject(sqs, queue_url: str, kind: str = "unknown-type") -> str:
    return sqs.send_message(QueueUrl=queue_url, **build_message(kind))["MessageId"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue-url", help="default: look up chopee-orders.fifo")
    ap.add_argument("--region", default="ap-southeast-1")
    ap.add_argument("--kind", choices=KINDS, default="unknown-type")
    args = ap.parse_args(argv)
    import boto3

    sqs = boto3.client("sqs", region_name=args.region)
    url = args.queue_url or sqs.get_queue_url(QueueName="chopee-orders.fifo")["QueueUrl"]
    print("sent", inject(sqs, url, args.kind), "- expect it in the DLQ after 3 receives and the DLQ alarm within ~2 minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
