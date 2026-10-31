"""M3 acceptance checks: outbox_relay, notify_logistics, notify_customer, report."""
from __future__ import annotations

import json

import boto3
import pytest
from boto3.dynamodb.types import TypeSerializer
from moto import mock_aws

from chopee import events
from tests.functions.conftest import load_handler

ser = TypeSerializer()


def stream_record(item: dict, name="INSERT", seq="1"):
    return {
        "eventName": name,
        "dynamodb": {
            "Keys": {"PK": ser.serialize(item["PK"]), "SK": ser.serialize(item["SK"])},
            "NewImage": {k: ser.serialize(v) for k, v in item.items()},
            "SequenceNumber": seq,
        },
    }


def outbox(event_type="OrderPaid", order="o1"):
    return events.outbox_item(event_type, order, "abc123def456", "PAID", "2026-10-16T10:00:00Z")


@pytest.fixture
def relay(aws, monkeypatch):
    q = aws.sqs.create_queue(QueueName="sink")["QueueUrl"]
    arn = aws.sqs.get_queue_attributes(QueueUrl=q, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    aws.sns.subscribe(TopicArn=aws.events_topic_arn, Protocol="sqs", Endpoint=arn,
                      Attributes={"RawMessageDelivery": "false"})
    monkeypatch.setenv("TOPIC_ARN", aws.events_topic_arn)
    aws.sink = q
    return load_handler("outbox_relay")


def sink_messages(aws):
    msgs = aws.sqs.receive_message(QueueUrl=aws.sink, MaxNumberOfMessages=10, MessageAttributeNames=["All"]).get("Messages", [])
    return [json.loads(json.loads(m["Body"])["Message"]) for m in msgs]


def test_only_event_inserts_publish(relay, aws):
    order_item = {"PK": "ORDER#o1", "SK": "META", "status": "PAID"}
    records = [
        stream_record(order_item),                                   # not an outbox item
        stream_record(outbox("OrderPaid", "o2"), name="MODIFY"),      # not an INSERT
        stream_record(outbox("OrderPaid", "o3"), name="REMOVE"),
        stream_record(outbox("OrderCancelled", "o4"), seq="4"),       # the only valid one
    ]
    assert relay.lambda_handler({"Records": records}, None) == {"batchItemFailures": []}
    published = sink_messages(aws)
    assert [m["orderId"] for m in published] == ["o4"]
    assert published[0]["type"] == "OrderCancelled" and "ttl" not in published[0]


def test_relay_reports_first_failure_sequence(relay, monkeypatch):
    monkeypatch.setenv("TOPIC_ARN", "arn:aws:sns:ap-southeast-1:123456789012:missing")
    result = relay.lambda_handler({"Records": [stream_record(outbox(), seq="42"), stream_record(outbox(), seq="43")]}, None)
    assert result == {"batchItemFailures": [{"itemIdentifier": "42"}]}


def test_stream_filter_matches_outbox_only():
    assert events.OUTBOX_STREAM_FILTER["dynamodb"]["Keys"]["PK"]["S"] == [{"prefix": "EVENT#"}]
    assert events.OUTBOX_STREAM_FILTER["eventName"] == ["INSERT"]


def sns_event(message: dict):
    return {"Records": [{"Sns": {"Message": json.dumps(message), "MessageAttributes": {}}}]}


def msg(event_type="OrderPaid", event_id="ev1"):
    return {"eventId": event_id, "type": event_type, "orderId": "o1", "customerRef": "abc123def456",
            "status": "PAID", "occurredAt": "2026-10-16T10:00:00Z"}


@pytest.mark.parametrize(
    "fn,expected_log,types",
    [
        ("notify_logistics", "fulfilment_requested", ["OrderPaid"]),
        ("notify_customer", "customer_notified", ["OrderPendingPayment", "OrderPaid", "OrderCancelled", "OrderRejected"]),
    ],
)
def test_consumer_logs_once_and_ignores_repeat(aws, fn, expected_log, types, capsys):
    h = load_handler(fn)
    h.lambda_handler(sns_event(msg(types[0])), None)
    h.lambda_handler(sns_event(msg(types[0])), None)  # same event id redelivered
    h.lambda_handler(sns_event(msg(types[-1], event_id="ev2")), None)
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert [entry["message"] for entry in logs] == [expected_log, "duplicate_ignored", expected_log]
    consumer = h.CONSUMER
    assert aws.table.get_item(Key={"PK": f"CONSUMED#{consumer}#ev1", "SK": "CONSUMED"})["Item"]["ttl"]


def test_logistics_ignores_other_event_types(aws, capsys):
    h = load_handler("notify_logistics")
    h.lambda_handler(sns_event(msg("OrderCancelled")), None)
    assert capsys.readouterr().out == ""


def test_consumers_dedupe_independently(aws):
    load_handler("notify_logistics").lambda_handler(sns_event(msg()), None)
    load_handler("notify_customer").lambda_handler(sns_event(msg()), None)
    keys_ = {i["PK"] for i in aws.table.scan()["Items"]}
    assert keys_ == {"CONSUMED#logistics#ev1", "CONSUMED#customer#ev1"}


# ---------------------------------------------------------------------------- report
class FakeLogs:
    def __init__(self, rows_by_query):
        self.rows_by_query = rows_by_query
        self.started = []

    def start_query(self, logGroupNames, startTime, endTime, queryString):
        self.started.append((tuple(logGroupNames), startTime, endTime))
        return {"queryId": str(len(self.started))}

    def get_query_results(self, queryId):
        return {"status": "Complete", "results": self.rows_by_query[int(queryId) - 1]}


def cell(field, value):
    return {"field": field, "value": value}


def test_report_has_aggregates_and_no_pii(monkeypatch):
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-southeast-1")
        s3.create_bucket(Bucket="reports", CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"})
        worker_rows = [
                [cell("status", "PAID"), cell("count", "7"), cell("@ptr", "xyz"),
                 cell("email", "alice@example.com"), cell("sub", "0b8a1c2e-1111-2222-3333-444455556666")],
                [cell("status", "CANCELLED"), cell("count", "2")],
        ]
        rows = [worker_rows, [], [[cell("count", "0")]], []]
        h = load_handler("report")
        for k, v in dict(LOG_GROUPS="/aws/lambda/worker,/ecs/checkout", REPORTS_BUCKET="reports").items():
            monkeypatch.setenv(k, v)
        out = h.lambda_handler({}, None, logs=FakeLogs(rows), s3=s3, now=1792152000)  # 2026-10-16 12:00Z
        json_key, csv_key = out["keys"]
        assert json_key.startswith("reports/2026/10/16/") and json_key.endswith(".json") and csv_key.endswith(".csv")
        body = s3.get_object(Bucket="reports", Key=out["keys"][0])["Body"].read().decode()
        csv_body = s3.get_object(Bucket="reports", Key=out["keys"][1])["Body"].read().decode()
        report = json.loads(body)
        assert report["sections"]["orders_by_terminal_status"][0] == {"status": "PAID", "count": "7"}
        for text in (body, csv_body):
            assert "alice@example.com" not in text and "@" not in text and "0b8a1c2e" not in text
        assert "PAID" in csv_body


@pytest.mark.parametrize("fn", ["order_worker", "outbox_relay", "notify_logistics", "notify_customer", "report"])
def test_terraform_entry_point_is_handler(fn):
    assert callable(load_handler(fn).handler)
