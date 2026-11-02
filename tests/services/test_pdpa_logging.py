"""PDPA (plan 05b SEC-3): a full checkout flow logs customerRef, never the token, sub or webhook payload."""
from __future__ import annotations

import json
import logging

from chopee import signing

from tests.services.conftest import KEY, SECRET


def test_checkout_flow_logs_no_token_sub_or_payload(checkout_client, seeded, make_token):
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(json.dumps({"m": record.getMessage(), "f": getattr(record, "fields", {})}, default=str))

    token = make_token(sub="pdpa-sub-7f3a")
    auth = {"Authorization": f"Bearer {token}"}
    logger = logging.getLogger("checkout")
    handler = Capture()
    logger.addHandler(handler)
    try:
        assert checkout_client.post("/api/checkout", json={"items": [{"sku": "TEE-01", "quantity": 1}]},
                                    headers={**auth, "Idempotency-Key": KEY}).status_code == 202
        seeded.table.put_item(Item={"PK": f"ORDER#{KEY}", "SK": "META", "customerId": "pdpa-sub-7f3a",
                                    "status": "PENDING_PAYMENT", "total": 1500, "currency": "SGD"})
        assert checkout_client.get(f"/api/orders/{KEY}", headers=auth).status_code == 200
        raw = json.dumps({"eventId": "evt-pdpa", "orderId": KEY, "outcome": "succeeded", "amount": 1500,
                          "currency": "SGD", "occurredAt": "2026-11-02T00:00:00Z"}, separators=(",", ":"))
        ok = checkout_client.post("/api/webhooks/payment", content=raw,
                                  headers={signing.HEADER: signing.sign(SECRET, raw)})
        bad = checkout_client.post("/api/webhooks/payment", content=raw,
                                   headers={signing.HEADER: signing.sign("forged", raw)})
        assert (ok.status_code, bad.status_code) == (200, 401)
        assert checkout_client.post(f"/api/demo/pay/{KEY}", json={"outcome": "declined"},
                                    headers=auth).status_code == 200
    finally:
        logger.removeHandler(handler)
    text = "\n".join(records)
    assert records and "customerRef" in text
    for secret in (token, "pdpa-sub-7f3a", "evt-pdpa", SECRET, "Bearer"):
        assert secret not in text
