#!/usr/bin/env python3
"""Reconcile orders against stock and queues after a load run (plan 06 M7).

Checks: every order is in a known status; no duplicate payments; no negative stock; stock is
conserved (initial - available == units held by PENDING_PAYMENT and PAID orders); and every
accepted checkout is an order or in the DLQ. Exit 0 when clean, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "python"))

from chopee import keys  # noqa: E402

HOLDING = (keys.ORDER_PENDING_PAYMENT, keys.ORDER_PAID)


def _n(v) -> int:
    return int(v)


def reconcile(items: list[dict], accepted: int | None = None, dlq_depth: int = 0,
              queue_backlog: int = 0) -> dict:
    """Pure check over a full table scan; returns a report dict with `ok` and `issues`."""
    issues: list[str] = []
    orders = [i for i in items if str(i.get("PK", "")).startswith("ORDER#") and i.get("SK") == "META"]
    stock = {i["PK"].split("#", 1)[1]: i for i in items if i.get("SK") == "STOCK"}
    status = Counter(o.get("status") for o in orders)

    for s in status:
        if s not in keys.ORDER_STATUSES:
            issues.append(f"unknown order status {s!r} ({status[s]} orders)")

    ids = Counter(o["PK"] for o in orders)
    for pk, c in ids.items():
        if c > 1:
            issues.append(f"duplicate order {pk}")

    paid_events = defaultdict(int)
    for i in items:
        if str(i.get("SK", "")).startswith("PAYMENT#") and i.get("outcome") == "succeeded":
            paid_events[i["PK"]] += 1
    for pk, c in paid_events.items():
        if c > 1:
            issues.append(f"{pk} has {c} successful payments")

    held: dict[str, int] = defaultdict(int)
    for o in orders:
        if o.get("status") in HOLDING:
            for line in o.get("items", []):
                held[line["sku"]] += _n(line["quantity"])

    for sku, s in stock.items():
        avail, initial = _n(s["available"]), _n(s["initial"])
        if avail < 0:
            issues.append(f"negative stock for {sku}: {avail}")
        if initial - avail != held.get(sku, 0):
            issues.append(f"stock mismatch for {sku}: initial {initial} - available {avail} "
                          f"!= {held.get(sku, 0)} units held by orders")
    for sku in held:
        if sku not in stock:
            issues.append(f"order references unknown SKU {sku}")

    if queue_backlog:
        issues.append(f"{queue_backlog} messages still in the orders queue; wait and re-run")
    if accepted is not None and len(orders) + dlq_depth < accepted:
        issues.append(f"{accepted} accepted but only {len(orders)} orders + {dlq_depth} in DLQ: "
                      f"{accepted - len(orders) - dlq_depth} unaccounted for")

    return {"ok": not issues, "orders": len(orders), "by_status": dict(status), "dlq_depth": dlq_depth,
            "accepted": accepted, "stock_held": dict(held), "issues": issues}


def scan_table(table) -> list[dict]:
    items, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def queue_depth(sqs, url: str) -> int:
    a = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=[
        "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    return int(a["ApproximateNumberOfMessages"]) + int(a["ApproximateNumberOfMessagesNotVisible"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", default=keys.TABLE_NAME)
    ap.add_argument("--queue-url", help="orders FIFO URL, to require an empty backlog")
    ap.add_argument("--dlq-url", help="orders DLQ URL, to count parked messages")
    ap.add_argument("--accepted", type=int, help="checkouts answered 202 (k6 summary)")
    ap.add_argument("--region", default="ap-southeast-1")
    ap.add_argument("--out", help="write the report JSON here")
    args = ap.parse_args(argv)
    import boto3

    sqs = boto3.client("sqs", region_name=args.region)
    items = scan_table(boto3.resource("dynamodb", region_name=args.region).Table(args.table))
    report = reconcile(items, args.accepted,
                       queue_depth(sqs, args.dlq_url) if args.dlq_url else 0,
                       queue_depth(sqs, args.queue_url) if args.queue_url else 0)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
