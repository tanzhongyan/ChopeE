"""Stage 1 gate: fixtures build every plan 06 Section 5 resource."""
import json


def test_table_matches_contract(aws):
    t = aws.ddb.describe_table(TableName="chopee")["Table"]
    assert t["BillingModeSummary"]["BillingMode"] == "PAY_PER_REQUEST"
    assert [k["AttributeName"] for k in t["KeySchema"]] == ["PK", "SK"]
    assert t["GlobalSecondaryIndexes"][0]["IndexName"] == "GSI1"
    assert t["GlobalSecondaryIndexes"][0]["Projection"]["ProjectionType"] == "ALL"
    assert t["StreamSpecification"] == {"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"}
    ttl = aws.ddb.describe_time_to_live(TableName="chopee")["TimeToLiveDescription"]
    assert ttl["AttributeName"] == "ttl" and ttl["TimeToLiveStatus"] in ("ENABLED", "ENABLING")


def test_fifo_queue_settings(aws):
    a = aws.sqs.get_queue_attributes(QueueUrl=aws.queue_url, AttributeNames=["All"])["Attributes"]
    assert a["FifoQueue"] == "true"
    assert a["ContentBasedDeduplication"] == "true"
    assert a["DeduplicationScope"] == "messageGroup"
    assert a["FifoThroughputLimit"] == "perMessageGroupId"
    assert a["VisibilityTimeout"] == "180"
    redrive = json.loads(a["RedrivePolicy"])
    assert redrive["maxReceiveCount"] == 3
    assert redrive["deadLetterTargetArn"].endswith(":chopee-orders-dlq.fifo")


def test_dlqs(aws):
    d = aws.sqs.get_queue_attributes(QueueUrl=aws.dlq_url, AttributeNames=["All"])["Attributes"]
    assert d["FifoQueue"] == "true"
    assert d["MessageRetentionPeriod"] == str(14 * 24 * 3600)
    assert aws.notify_dlq_url.endswith("chopee-notify-dlq")


def test_sns_topics(aws):
    arns = {t["TopicArn"].rsplit(":", 1)[1] for t in aws.sns.list_topics()["Topics"]}
    assert {"chopee-order-events", "chopee-ops-alerts"} <= arns


def test_dlq_redrive_after_three_receives(aws):
    aws.sqs.send_message(QueueUrl=aws.queue_url, MessageBody="{}", MessageGroupId="g", MessageDeduplicationId="d1")
    for _ in range(3):
        msgs = aws.sqs.receive_message(QueueUrl=aws.queue_url, VisibilityTimeout=0).get("Messages", [])
        assert msgs
    aws.sqs.receive_message(QueueUrl=aws.queue_url, VisibilityTimeout=0)
    dlq = aws.sqs.get_queue_attributes(QueueUrl=aws.dlq_url, AttributeNames=["ApproximateNumberOfMessages"])
    assert dlq["Attributes"]["ApproximateNumberOfMessages"] == "1"
