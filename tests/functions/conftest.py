"""Fixtures for Lambda handler tests: SSM salt, EventBridge Scheduler group, handler loader."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import uuid

import boto3
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG_SALT = "test-log-salt"


def load_handler(name: str):
    """Import functions/<name>/handler.py as a fresh module (function dirs are not packages)."""
    spec = importlib.util.spec_from_file_location(f"fn_{name}_{uuid.uuid4().hex[:6]}", ROOT / "functions" / name / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ssm(aws):
    client = boto3.client("ssm", region_name=aws.region)
    client.put_parameter(Name="/chopee/log-salt", Value=LOG_SALT, Type="SecureString")
    return client


@pytest.fixture
def scheduler(aws):
    client = boto3.client("scheduler", region_name=aws.region)
    client.create_schedule_group(Name="chopee-expiry")
    return client


@pytest.fixture
def worker_env(aws, ssm, scheduler, monkeypatch):
    arn = aws.sqs.get_queue_attributes(QueueUrl=aws.queue_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    monkeypatch.setenv("TABLE_NAME", "chopee")
    monkeypatch.setenv("ORDERS_QUEUE_ARN", arn)
    monkeypatch.setenv("SCHEDULER_ROLE", "arn:aws:iam::123456789012:role/chopee-scheduler")
    monkeypatch.setenv("SCHEDULE_GROUP", "chopee-expiry")
    monkeypatch.setenv("EXPIRY_MINUTES", "15")
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "ChopeE")
    return aws


def seed_product(table, sku: str, price: int = 500, stock: int = 10) -> None:
    table.put_item(Item={"PK": f"PRODUCT#{sku}", "SK": "META", "name": sku, "price": price, "currency": "SGD",
                         "GSI1PK": "CATALOG", "GSI1SK": sku})
    table.put_item(Item={"PK": f"PRODUCT#{sku}", "SK": "STOCK", "available": stock, "initial": stock})


def stock_of(table, sku: str) -> int:
    return int(table.get_item(Key={"PK": f"PRODUCT#{sku}", "SK": "STOCK"})["Item"]["available"])


def sqs_event(*bodies, group="user-1"):
    """Build an SQS FIFO Lambda event from message bodies (dict -> JSON)."""
    return {
        "Records": [
            {
                "messageId": f"m{i}",
                "receiptHandle": f"r{i}",
                "body": b if isinstance(b, str) else json.dumps(b),
                "attributes": {"MessageGroupId": group, "ApproximateReceiveCount": "1"},
                "messageAttributes": {},
                "md5OfBody": "x",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:ap-southeast-1:123456789012:chopee-orders.fifo",
                "awsRegion": "ap-southeast-1",
            }
            for i, b in enumerate(bodies)
        ]
    }
