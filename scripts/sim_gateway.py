#!/usr/bin/env python3
"""Simulated payment gateway: sends a signed payment webhook (plan 06 Section 5.2, plan 05b SEC-2)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "python"))

from chopee import signing  # noqa: E402


def build_body(order_id: str, outcome: str, amount: int, currency: str = "SGD",
               event_id: str | None = None, now: int | None = None) -> str:
    if outcome not in ("succeeded", "declined"):
        raise ValueError("outcome must be succeeded or declined")
    occurred = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time()))
    return json.dumps(
        {"eventId": event_id or str(uuid.uuid4()), "orderId": order_id, "outcome": outcome,
         "amount": amount, "currency": currency, "occurredAt": occurred},
        separators=(",", ":"),
    )


def signed_request(secret: str, body: str, now: int | None = None) -> dict:
    """Headers for a webhook call; the signature covers exactly the bytes sent."""
    return {"Content-Type": "application/json", signing.HEADER: signing.sign(secret, body, now)}


def stale_now(now: float | None = None) -> int:
    """A signing time one second outside the receiver's replay window."""
    return int(time.time() if now is None else now) - signing.TOLERANCE_SECONDS - 1


def tamper(body: str) -> str:
    """The body an attacker would send after changing the amount of a signed event."""
    event = json.loads(body)
    event["amount"] = event["amount"] + 1
    return json.dumps(event, separators=(",", ":"))


def send(base_url: str, body: str, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(base_url.rstrip("/") + "/api/webhooks/payment",
                                 data=body.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", required=True, help="ALB or CloudFront URL")
    ap.add_argument("--order-id", required=True)
    ap.add_argument("--outcome", choices=["succeeded", "declined"], default="succeeded")
    ap.add_argument("--amount", type=int, required=True, help="order total in cents")
    ap.add_argument("--currency", default="SGD")
    ap.add_argument("--event-id", help="reuse to demonstrate gateway retries")
    ap.add_argument("--secret", default=os.environ.get("WEBHOOK_SECRET"), help="or env WEBHOOK_SECRET")
    attack = ap.add_mutually_exclusive_group()
    attack.add_argument("--bad-signature", action="store_true", help="sign with a wrong secret (expect 401)")
    attack.add_argument("--stale", action="store_true",
                        help=f"sign {signing.TOLERANCE_SECONDS + 1}s in the past, a replay (expect 401)")
    attack.add_argument("--tamper", action="store_true", help="change the amount after signing (expect 401)")
    args = ap.parse_args(argv)
    if not args.secret:
        ap.error("--secret or WEBHOOK_SECRET is required")
    body = build_body(args.order_id, args.outcome, args.amount, args.currency, args.event_id)
    secret = "wrong-secret" if args.bad_signature else args.secret
    headers = signed_request(secret, body, stale_now() if args.stale else None)
    status, text = send(args.base_url, tamper(body) if args.tamper else body, headers)
    print(status, text)
    expected = 401 if (args.bad_signature or args.stale or args.tamper) else 200
    return 0 if status == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
