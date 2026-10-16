"""Shared fixtures: moto resources built exactly as plan 06 Section 5 specifies."""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws

REGION = "ap-southeast-1"
POOL_ID = f"{REGION}_TestPool1"
CLIENT_ID = "test-client-id"

for _k, _v in {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": REGION,
}.items():
    os.environ[_k] = _v
os.environ.pop("AWS_CA_BUNDLE", None)


def create_table(ddb):
    ddb.create_table(
        TableName="chopee",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in ("PK", "SK", "GSI1PK", "GSI1SK")
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        StreamSpecification={"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"},
    )
    ddb.update_time_to_live(
        TableName="chopee", TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"}
    )
    ddb.update_continuous_backups(
        TableName="chopee", PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True}
    )


def create_queues(sqs):
    dlq_url = sqs.create_queue(
        QueueName="chopee-orders-dlq.fifo",
        Attributes={
            "FifoQueue": "true",
            "MessageRetentionPeriod": str(14 * 24 * 3600),
            "SqsManagedSseEnabled": "true",
        },
    )["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    url = sqs.create_queue(
        QueueName="chopee-orders.fifo",
        Attributes={
            "FifoQueue": "true",
            "ContentBasedDeduplication": "true",
            "DeduplicationScope": "messageGroup",
            "FifoThroughputLimit": "perMessageGroupId",
            "VisibilityTimeout": "180",
            "SqsManagedSseEnabled": "true",
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 3}),
        },
    )["QueueUrl"]
    notify_dlq_url = sqs.create_queue(QueueName="chopee-notify-dlq")["QueueUrl"]
    return url, dlq_url, notify_dlq_url


@pytest.fixture
def aws():
    """All Section 5 resources: table, FIFO queue + DLQ, notify DLQ, SNS topics."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        sqs = boto3.client("sqs", region_name=REGION)
        sns = boto3.client("sns", region_name=REGION)
        create_table(ddb)
        queue_url, dlq_url, notify_dlq_url = create_queues(sqs)
        events_arn = sns.create_topic(Name="chopee-order-events")["TopicArn"]
        ops_arn = sns.create_topic(Name="chopee-ops-alerts")["TopicArn"]
        yield SimpleNamespace(
            region=REGION,
            ddb=ddb,
            table=boto3.resource("dynamodb", region_name=REGION).Table("chopee"),
            sqs=sqs,
            sns=sns,
            queue_url=queue_url,
            dlq_url=dlq_url,
            notify_dlq_url=notify_dlq_url,
            events_topic_arn=events_arn,
            ops_topic_arn=ops_arn,
        )


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def jwks(rsa_key):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update(kid="test-kid", alg="RS256", use="sig")
    return {"keys": [jwk]}


@pytest.fixture
def verifier(jwks):
    from chopee.auth import JwtVerifier

    return JwtVerifier(REGION, POOL_ID, CLIENT_ID, jwks=jwks)


@pytest.fixture
def make_token(rsa_key):
    """Mint a Cognito-style access token signed with the fixture key."""

    def _make(sub="user-1", token_use="access", client_id=CLIENT_ID, exp_in=3600, issuer=None, kid="test-kid"):
        now = int(time.time())
        claims = {
            "sub": sub,
            "iss": issuer or f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}",
            "token_use": token_use,
            "client_id": client_id,
            "iat": now,
            "exp": now + exp_in,
        }
        return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": kid})

    return _make
