"""report: Logs Insights aggregates over the last 24 h -> S3 JSON + CSV (plan 06 Section 5.7).

Only aggregates and customerRef pseudonyms leave this function: result rows are reduced to an
allow-list of field names, so an email or Cognito sub cannot reach the report even if logged.
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
from datetime import datetime, timezone

import boto3

from chopee.logging import get_logger

log = get_logger("report")
ALLOWED_FIELDS = {"status", "reason", "message", "count", "customerRef", "path"}
POLL_SECONDS = 1.0
TIMEOUT_SECONDS = 60

# (report section, Logs Insights query); every query runs over LOG_GROUPS and filters by message
QUERIES = [
    ("orders_by_terminal_status", 'fields status | filter message = "order_transition" and status != "PENDING_PAYMENT" | stats count(*) as count by status'),
    ("rejected_and_late_payments", 'fields message | filter message = "late_payment" or reason = "OUT_OF_STOCK" | stats count(*) as count by message, reason'),
    ("webhook_signature_failures", 'fields message | filter message = "webhook_signature_failure" | stats count(*) as count'),
    ("checkout_5xx", 'fields status | filter message = "http_request" and status >= 500 | stats count(*) as count by status'),
]


def sanitise(rows: list[list[dict]]) -> list[dict]:
    """Logs Insights rows -> dicts limited to ALLOWED_FIELDS (drops @ptr and anything else)."""
    return [{c["field"]: c["value"] for c in row if c["field"] in ALLOWED_FIELDS} for row in rows]


def run_query(logs, groups: list[str], query: str, start: int, end: int, sleep=time.sleep) -> list[dict]:
    qid = logs.start_query(logGroupNames=groups, startTime=start, endTime=end, queryString=query)["queryId"]
    deadline = time.time() + TIMEOUT_SECONDS
    while True:
        resp = logs.get_query_results(queryId=qid)
        if resp["status"] == "Complete":
            return sanitise(resp.get("results", []))
        if resp["status"] in ("Failed", "Cancelled", "Timeout") or time.time() > deadline:
            raise RuntimeError(f"query {qid} ended with status {resp['status']}")
        sleep(POLL_SECONDS)


def to_csv(sections: dict[str, list[dict]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["section", "field", "value", "count"])
    for name, rows in sections.items():
        for row in rows:
            dims = {k: v for k, v in row.items() if k != "count"}
            writer.writerow([name, ";".join(dims), ";".join(dims.values()), row.get("count", "")])
    return out.getvalue()


def lambda_handler(event, context, logs=None, s3=None, now=None, sleep=time.sleep):
    logs = logs or boto3.client("logs")
    s3 = s3 or boto3.client("s3")
    now = int(now if now is not None else time.time())
    start = now - 24 * 3600
    sections = {}
    groups = [g for g in os.environ.get("LOG_GROUPS", "").split(",") if g]
    for name, query in QUERIES:
        sections[name] = run_query(logs, groups, query, start, now, sleep) if groups else []
    stamp = datetime.fromtimestamp(now, timezone.utc)
    report = {"generatedAt": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), "windowHours": 24, "sections": sections}
    prefix = f"reports/{stamp:%Y/%m/%d/%H%M}"
    bucket = os.environ["REPORTS_BUCKET"]
    s3.put_object(Bucket=bucket, Key=f"{prefix}.json", Body=json.dumps(report, indent=2), ContentType="application/json")
    s3.put_object(Bucket=bucket, Key=f"{prefix}.csv", Body=to_csv(sections), ContentType="text/csv")
    log.info("report_written", extra={"fields": {"key": prefix}})
    return {"bucket": bucket, "keys": [f"{prefix}.json", f"{prefix}.csv"]}


handler = lambda_handler  # Terraform entry point: handler.handler
