import json

import pytest

from chopee import events, keys, models, signing
from chopee.auth import AuthError
from chopee.logging import get_logger, pseudonymise


def test_keys():
    assert keys.stock_key("A1") == {"PK": "PRODUCT#A1", "SK": "STOCK"}
    assert keys.cart_item_key(keys.guest_owner("g"), "A1") == {"PK": "CART#GUEST#g", "SK": "ITEM#A1"}
    assert keys.merge_marker_key("u", "g") == {"PK": "CART#USER#u", "SK": "MERGED#g"}
    assert keys.order_gsi1("u", "t") == {"GSI1PK": "CUSTOMER#u", "GSI1SK": "ORDER#t"}
    assert keys.consumed_key("notify_customer", "e1")["PK"] == "CONSUMED#notify_customer#e1"


def test_validate_lines():
    assert models.validate_lines([{"sku": "A", "quantity": 5}]) == [models.OrderLine("A", 5)]
    for bad in ([], [{"sku": "A", "quantity": 6}], [{"sku": "A", "quantity": 0}],
                [{"sku": "A", "quantity": 1}, {"sku": "A", "quantity": 1}],
                [{"sku": "A", "quantity": True}], [{"sku": "S%d" % i, "quantity": 1} for i in range(11)],
                [1], ["x"]):
        with pytest.raises(models.InvalidMessage):
            models.validate_lines(bad)


def test_uuid4():
    assert models.is_uuid4("3f2b8c1e-5a4d-4e6f-9b0a-1c2d3e4f5a6b")
    assert not models.is_uuid4("3f2b8c1e-5a4d-1e6f-9b0a-1c2d3e4f5a6b")
    assert not models.is_uuid4("nope")


def test_message_roundtrip_and_poison(aws):
    msg = models.order_placed("o1", "u1", [models.OrderLine("A", 1)], "2026-01-01T00:00:00Z")
    aws.sqs.send_message(**msg.to_send_kwargs(aws.queue_url))
    body = aws.sqs.receive_message(QueueUrl=aws.queue_url)["Messages"][0]["Body"]
    mtype, parsed = models.parse_message(body)
    assert mtype == models.ORDER_PLACED and parsed["items"] == [{"sku": "A", "quantity": 1}]
    for bad in ("not json", "[]", '{"type":"WAT"}', '{"type":"ORDER_PLACED"}'):
        with pytest.raises(models.InvalidMessage):
            models.parse_message(bad)


def test_outbox_item():
    item = events.outbox_item(events.ORDER_PAID, "o1", "ref", "PAID", "t", now=1000, event_id="e1")
    assert item["PK"] == "EVENT#e1" and item["ttl"] == 1000 + 86400
    with pytest.raises(ValueError):
        events.outbox_item("Nope", "o", "r", "s", "t")


def test_signing():
    body = json.dumps({"eventId": "e"})
    hdr = signing.sign("s3cret", body, now=1000)
    signing.verify("s3cret", hdr, body, now=1100)
    for args in (("wrong", hdr, body, 1100), ("s3cret", hdr, body + " ", 1100),
                 ("s3cret", hdr, body, 1301), ("s3cret", None, body, 1100),
                 ("s3cret", "garbage", body, 1100)):
        with pytest.raises(signing.SignatureError):
            signing.verify(*args)


def test_jwt_verifier(verifier, make_token):
    assert verifier.subject("Bearer " + make_token(sub="abc")) == "abc"
    bad = [make_token(token_use="id"), make_token(client_id="other"), make_token(exp_in=-10),
           make_token(issuer="https://evil.example/x"), make_token(kid="unknown")]
    for tok in bad:
        with pytest.raises(AuthError):
            verifier.verify(tok)
    with pytest.raises(AuthError):
        verifier.subject(None)
    with pytest.raises(AuthError):
        verifier.verify(make_token()[:-4] + "AAAA")


def test_pseudonym_and_logger(capsys):
    ref = pseudonymise("salt", "sub-1")
    assert len(ref) == 12 and ref == pseudonymise("salt", "sub-1") and ref != pseudonymise("salt2", "sub-1")
    get_logger("t").info("hello", extra={"fields": {"customerRef": ref}})
    line = json.loads(capsys.readouterr().out)
    assert line["message"] == "hello" and line["customerRef"] == ref
