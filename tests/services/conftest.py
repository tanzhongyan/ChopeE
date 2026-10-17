"""Fixtures for the FastAPI service tests (moto-backed, no AWS)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.catalog_cart.app import create_app as create_catalog_app
from services.checkout.app import create_app as create_checkout_app

SECRET = "test-webhook-secret"
SALT = "test-salt"
GUEST = "11111111-1111-4111-8111-111111111111"
KEY = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def seeded(aws):
    """Three products with stock; LIMITED-01 has a single unit."""
    for sku, name, price, stock in [("TEE-01", "Tee", 1500, 50), ("MUG-01", "Mug", 800, 50), ("LIMITED-01", "Limited", 9900, 1)]:
        aws.table.put_item(Item={"PK": f"PRODUCT#{sku}", "SK": "META", "name": name, "price": price, "currency": "SGD",
                                 "description": "d", "emoji": "x", "GSI1PK": "CATALOG", "GSI1SK": sku})
        aws.table.put_item(Item={"PK": f"PRODUCT#{sku}", "SK": "STOCK", "available": stock, "initial": stock})
    return aws


@pytest.fixture
def auth(make_token):
    return lambda sub="user-1": {"Authorization": f"Bearer {make_token(sub=sub)}"}


@pytest.fixture
def catalog_client(seeded, verifier):
    return TestClient(create_catalog_app(ddb=seeded.ddb, verifier=verifier, table_name="chopee"))


@pytest.fixture
def checkout_app(seeded, verifier):
    return create_checkout_app(
        table=seeded.table, sqs=seeded.sqs, queue_url=seeded.queue_url, verifier=verifier,
        webhook_secret=SECRET, demo_gateway=True, log_salt=SALT,
    )


@pytest.fixture
def checkout_client(checkout_app):
    return TestClient(checkout_app)


def queued(aws):
    """Drain visible messages from the order queue as parsed bodies."""
    import json

    out = []
    while True:
        msgs = aws.sqs.receive_message(QueueUrl=aws.queue_url, MaxNumberOfMessages=10, VisibilityTimeout=0).get("Messages", [])
        if not msgs:
            return out
        for m in msgs:
            out.append(json.loads(m["Body"]))
            aws.sqs.delete_message(QueueUrl=aws.queue_url, ReceiptHandle=m["ReceiptHandle"])
