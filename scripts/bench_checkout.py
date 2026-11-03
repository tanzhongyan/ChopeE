#!/usr/bin/env python3
"""In-process micro-benchmark of POST /api/checkout (plan 05c API-10).

Builds the checkout app with in-memory stub table / SQS / JWT verifier (no AWS,
no network, no sockets) and drives it through httpx ASGITransport with fresh
UUID4 Idempotency-Keys. Prints p50/p95/p99 request latency (ms) and requests/s
as JSON.

This is an in-process floor for handler cost: it excludes the ALB, TLS, the
network, real DynamoDB/SQS round trips and Uvicorn's HTTP parsing. It is NOT a
substitute for ALB TargetResponseTime in the M7 burst run; compare against that
metric, never replace it.

Usage: python scripts/bench_checkout.py [--requests 2000] [--concurrency 50] [--json-out FILE]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "shared" / "python"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class StubVerifier:
    def subject(self, authorization):
        return "bench-user"


class StubTable:
    """Just enough of a boto3 Table for checkout: get_item, put_item (conditions accepted), query."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def get_item(self, Key, **kwargs):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, **kwargs):  # ConditionExpression et al. are accepted and ignored
        self.items[(Item["PK"], Item["SK"])] = dict(Item)
        return {}

    def query(self, **kwargs):
        return {"Items": []}


class StubSqs:
    def __init__(self):
        self.sent = 0

    def send_message(self, **kwargs):
        self.sent += 1
        return {"MessageId": str(self.sent)}


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round(pct / 100 * len(sorted_values) + 0.5)) - 1))
    return sorted_values[idx]


async def run_bench(requests: int = 2000, concurrency: int = 50) -> dict:
    import httpx

    from services.checkout.app import create_app

    sqs = StubSqs()
    app = create_app(table=StubTable(), sqs=sqs, queue_url="http://stub/queue", verifier=StubVerifier(),
                     webhook_secret="bench-secret", demo_gateway=False, log_salt="bench-salt")
    body = {"items": [{"sku": "TEE-01", "quantity": 1}]}
    headers = {"Authorization": "Bearer stub"}
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bench") as client:

        async def one():
            async with sem:
                started = time.perf_counter()
                resp = await client.post("/api/checkout", json=body,
                                         headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
                latencies.append((time.perf_counter() - started) * 1000)
                statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1

        await one()  # warm-up (imports, threadpool) excluded from the stats
        latencies.clear()
        statuses.clear()
        t0 = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(requests)))
        elapsed = time.perf_counter() - t0

    ordered = sorted(latencies)
    return {
        "requests": requests,
        "concurrency": concurrency,
        "status_counts": {str(k): v for k, v in sorted(statuses.items())},
        "p50_ms": round(percentile(ordered, 50), 3),
        "p95_ms": round(percentile(ordered, 95), 3),
        "p99_ms": round(percentile(ordered, 99), 3),
        "mean_ms": round(statistics.fmean(ordered), 3) if ordered else 0.0,
        "requests_per_s": round(requests / elapsed, 1) if elapsed > 0 else 0.0,
        "note": "in-process floor, no network; not a substitute for ALB TargetResponseTime",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="In-process checkout latency floor (no AWS, no network).")
    ap.add_argument("--requests", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--json-out", help="also write the JSON result to this file")
    args = ap.parse_args(argv)
    if args.requests < 1 or args.concurrency < 1:
        ap.error("--requests and --concurrency must be >= 1")
    logging.disable(logging.CRITICAL)  # per-request JSON access logs would drown the result
    try:
        result = asyncio.run(run_bench(args.requests, args.concurrency))
    finally:
        logging.disable(logging.NOTSET)
    text = json.dumps(result, indent=2)
    print(text)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    return 0 if result["status_counts"] == {"202": args.requests} else 1


if __name__ == "__main__":
    sys.exit(main())
