#!/usr/bin/env python3
"""M6 smoke test against a deployed stack (plan 06 Section 7).

Automated: sign-up/sign-in, guest cart merge, checkout -> PENDING_PAYMENT -> pay -> PAID, decline ->
CANCELLED with stock restored, bad webhook signature -> 401, consumer log lines, poison -> DLQ.
Manual (printed, never auto-passed): DLQ alarm email received, one end-to-end X-Ray trace.
Config comes from flags or `terraform output -json` (--tf-outputs FILE). Exit 0 only if nothing FAILED.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inject_poison  # noqa: E402
import sim_gateway  # noqa: E402

PASSWORD = "ChopeE-Smoke-1!"
SKU = "SKU-01"


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append((name, status, detail))
        print(f"[{status}] {name}" + (f" - {detail}" if detail else ""), flush=True)

    @property
    def failed(self) -> bool:
        return any(s == "FAIL" for _, s, _ in self.rows)


def poll(fn: Callable, pred: Callable, timeout: float = 30, interval: float = 1,
         sleep=time.sleep, clock=time.monotonic):
    """Call fn() until pred(result) is true or timeout; returns the last result."""
    end, res = clock() + timeout, fn()
    while not pred(res) and clock() < end:
        sleep(interval)
        res = fn()
    return res


def load_tf_outputs(path: str | None) -> dict:
    """Flatten `terraform output -json` ({name: {value: ...}}) to {name: value}."""
    if not path:
        return {}
    raw = json.loads(Path(path).read_text())
    return {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in raw.items()}


def http(method: str, url: str, headers: dict | None = None, body=None) -> tuple[int, dict | None]:
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, None


class Api:
    def __init__(self, base: str, request=http):
        self.base, self.request = base.rstrip("/"), request

    def __call__(self, method, path, token=None, guest=None, key=None, body=None):
        h = {}
        if token:
            h["Authorization"] = f"Bearer {token}"
        if guest:
            h["X-Guest-Id"] = guest
        if key:
            h["Idempotency-Key"] = key
        return self.request(method, f"{self.base}/api{path}", h, body)


def check_cart_merge(api: Api, token: str, report: Report) -> bool:
    guest = str(uuid.uuid4())
    s, _ = api("PUT", f"/cart/items/{SKU}", guest=guest, body={"quantity": 2})
    ok = s == 200
    s1, c1 = api("POST", "/cart/merge", token=token, body={"guestId": guest})
    s2, c2 = api("POST", "/cart/merge", token=token, body={"guestId": guest})
    qty = lambda c: {i["sku"]: i["quantity"] for i in (c or {}).get("items", [])}.get(SKU)  # noqa: E731
    ok = ok and s1 == 200 and s2 == 200 and qty(c1) == qty(c2) and qty(c1) is not None and qty(c1) >= 2
    report.add("guest cart merges once and a retry adds nothing", "PASS" if ok else "FAIL",
               f"merge statuses {s1}/{s2}, qty {qty(c1)}/{qty(c2)}")
    return ok


def place_order(api: Api, token: str, report: Report, label: str) -> str | None:
    key = str(uuid.uuid4())
    body = {"items": [{"sku": SKU, "quantity": 1}]}
    s, r = api("POST", "/checkout", token=token, key=key, body=body)
    s2, r2 = api("POST", "/checkout", token=token, key=key, body=body)
    ok = s == 202 and (r or {}).get("status") == "QUEUED" and s2 in (200, 202) and (r2 or {}).get("orderId") == key
    report.add(f"{label}: checkout accepted, same key returns same order", "PASS" if ok else "FAIL", f"{s}/{s2}")
    if not ok:
        return None
    st = poll(lambda: api("GET", f"/orders/{key}", token=token),
              lambda x: x[0] == 200 and x[1]["status"] != "QUEUED")
    ok = st[0] == 200 and st[1]["status"] == "PENDING_PAYMENT"
    report.add(f"{label}: worker moves order to PENDING_PAYMENT", "PASS" if ok else "FAIL", str(st[1] and st[1].get("status")))
    return key if ok else None


def settle(api: Api, token: str, report: Report, order_id: str, outcome: str, want: str, label: str) -> bool:
    s, _ = api("POST", f"/demo/pay/{order_id}", token=token, body={"outcome": outcome})
    st = poll(lambda: api("GET", f"/orders/{order_id}", token=token),
              lambda x: x[0] == 200 and x[1]["status"] != "PENDING_PAYMENT")
    ok = s == 200 and st[1] is not None and st[1]["status"] == want
    report.add(f"{label}: {outcome} payment -> {want}", "PASS" if ok else "FAIL",
               f"pay {s}, status {st[1] and st[1].get('status')}")
    return ok


def check_bad_signature(base: str, report: Report, request=sim_gateway.send) -> bool:
    body = sim_gateway.build_body(str(uuid.uuid4()), "succeeded", 100)
    s, _ = request(base, body, sim_gateway.signed_request("not-the-secret", body))
    report.add("webhook with a bad signature is rejected", "PASS" if s == 401 else "FAIL", f"status {s}")
    return s == 401


def stock_available(ddb, table: str, sku: str) -> int:
    item = ddb.get_item(TableName=table, Key={"PK": {"S": f"PRODUCT#{sku}"}, "SK": {"S": "STOCK"}})["Item"]
    return int(item["available"]["N"])


def check_consumer_logs(logs, group: str, needle: str, order_id: str, report: Report, name: str,
                        wait: float = 60) -> bool:
    def probe():
        try:
            ev = logs.filter_log_events(logGroupName=group, filterPattern=f'"{needle}"')["events"]
        except Exception as exc:  # noqa: BLE001
            return str(exc)
        return [e for e in ev if order_id in e["message"]]

    res = poll(probe, lambda r: isinstance(r, str) or bool(r), timeout=wait, interval=3)
    ok = isinstance(res, list) and bool(res)
    report.add(f"{name} logged {needle}", "PASS" if ok else "FAIL", res if isinstance(res, str) else "")
    return ok


def run(args, outputs: dict) -> Report:
    import boto3

    report = Report()
    base = args.base_url or outputs["cloudfront_url"]
    region = args.region
    pool = args.user_pool_id or outputs["user_pool_id"]
    client_id = args.client_id or outputs["client_id"]
    table = args.table or outputs.get("table_name", "chopee")
    api = Api(base)
    idp = boto3.client("cognito-idp", region_name=region)
    ddb = boto3.client("dynamodb", region_name=region)

    email = f"smoke-{uuid.uuid4().hex[:8]}@example.test"
    idp.sign_up(ClientId=client_id, Username=email, Password=PASSWORD,
                UserAttributes=[{"Name": "email", "Value": email}])
    idp.admin_confirm_sign_up(UserPoolId=pool, Username=email)
    token = idp.initiate_auth(ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH",
                              AuthParameters={"USERNAME": email, "PASSWORD": PASSWORD})["AuthenticationResult"]["AccessToken"]
    report.add("sign-up, confirm and sign-in", "PASS")

    check_cart_merge(api, token, report)
    s, cat = api("GET", "/catalog")
    report.add("catalog lists products", "PASS" if s == 200 and len(cat or []) >= 24 else "FAIL", f"{s}, {len(cat or [])} items")

    before = stock_available(ddb, table, SKU)
    paid = place_order(api, token, report, "pay")
    if paid:
        settle(api, token, report, paid, "succeeded", "PAID", "pay")
    declined = place_order(api, token, report, "decline")
    if declined:
        settle(api, token, report, declined, "declined", "CANCELLED", "decline")
        after = poll(lambda: stock_available(ddb, table, SKU), lambda a: a == before - 1, timeout=15)
        report.add("declined order's stock is restored (only the paid unit stays out)",
                   "PASS" if after == before - 1 else "FAIL", f"before {before}, after {after}")

    check_bad_signature(args.webhook_url or base, report)

    if paid and not args.skip_logs:
        check_consumer_logs(boto3.client("logs", region_name=region), args.logistics_log_group,
                            "fulfilment_requested", paid, report, "notify_logistics")
        check_consumer_logs(boto3.client("logs", region_name=region), args.customer_log_group,
                            "customer_notified", paid, report, "notify_customer")

    sqs = boto3.client("sqs", region_name=region)
    queue_url = args.queue_url or outputs.get("queue_url")
    dlq_url = args.dlq_url or outputs.get("dlq_url")
    inject_poison.inject(sqs, queue_url)
    if args.wait_dlq:
        def depth():
            return int(sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["ApproximateNumberOfMessagesVisible"])
                       ["Attributes"]["ApproximateNumberOfMessagesVisible"])
        d = poll(depth, lambda n: n >= 1, timeout=args.wait_dlq, interval=15)
        report.add("poison message reaches the DLQ", "PASS" if d >= 1 else "FAIL", f"visible {d}")
    else:
        report.add("poison message reaches the DLQ", "MANUAL",
                   "injected; needs ~6 min (3 receives x 180 s). Re-run with --wait-dlq 900 to automate")
    report.add("DLQ alarm email received", "MANUAL", "check the ops-alert inbox and note the timestamp")
    report.add("one end-to-end X-Ray trace visible", "MANUAL", "open X-Ray, filter by the checkout service")
    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tf-outputs", help="file from `terraform output -json`")
    ap.add_argument("--base-url", help="CloudFront URL (default: output cloudfront_url)")
    ap.add_argument("--webhook-url", help="webhook base URL (default: the CloudFront URL, which adds the ALB origin header)")
    ap.add_argument("--user-pool-id")
    ap.add_argument("--client-id")
    ap.add_argument("--table")
    ap.add_argument("--queue-url")
    ap.add_argument("--dlq-url")
    ap.add_argument("--region", default="ap-southeast-1")
    ap.add_argument("--logistics-log-group", default="/aws/lambda/chopee-notify-logistics")
    ap.add_argument("--customer-log-group", default="/aws/lambda/chopee-notify-customer")
    ap.add_argument("--skip-logs", action="store_true")
    ap.add_argument("--wait-dlq", type=int, default=0, metavar="SECONDS", help="poll the DLQ this long")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(args, load_tf_outputs(args.tf_outputs))
    print(f"\n{sum(s == 'PASS' for _, s, _ in report.rows)} passed, "
          f"{sum(s == 'FAIL' for _, s, _ in report.rows)} failed, "
          f"{sum(s == 'MANUAL' for _, s, _ in report.rows)} manual")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
