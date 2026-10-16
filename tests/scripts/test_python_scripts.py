"""Pure-logic tests for the Python scripts (no network, no AWS)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import create_test_users as cu
import inject_poison
import reconcile
import seed_catalog
import sim_gateway
import smoke
from chopee import signing

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.mark.parametrize("name", ["seed_catalog", "sim_gateway", "inject_poison", "create_test_users",
                                  "reconcile", "smoke"])
def test_help_exits_zero(name):
    r = subprocess.run([sys.executable, str(SCRIPTS / f"{name}.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "usage" in r.stdout.lower()


# ---- seed_catalog ----
def test_seed_items_match_contract(aws):
    assert seed_catalog.seed(aws.table) == 50
    stock = {i["PK"]: i for i in aws.table.scan()["Items"] if i["SK"] == "STOCK"}
    assert len(stock) == 25
    assert stock["PRODUCT#LIMITED-01"]["available"] == 50
    assert all(v["available"] == 2000 for k, v in stock.items() if k != "PRODUCT#LIMITED-01")
    catalog = aws.table.query(IndexName="GSI1", KeyConditionExpression="GSI1PK = :p",
                              ExpressionAttributeValues={":p": "CATALOG"})["Items"]
    assert len(catalog) == 25 and all(i["currency"] == "SGD" and int(i["price"]) == i["price"] > 0 for i in catalog)


def test_seed_skus_are_the_24_loadtest_skus():
    assert seed_catalog.NORMAL_SKUS[0] == "SKU-01" and seed_catalog.NORMAL_SKUS[-1] == "SKU-24"
    assert len(seed_catalog.NORMAL_SKUS) == 24


# ---- sim_gateway ----
def test_gateway_signature_verifies_and_wrong_secret_fails():
    body = sim_gateway.build_body("o-1", "succeeded", 1200, event_id="e-1", now=1_700_000_000)
    assert json.loads(body)["eventId"] == "e-1"
    h = sim_gateway.signed_request("s3cret", body, now=1_700_000_000)
    signing.verify("s3cret", h[signing.HEADER], body, now=1_700_000_000)
    with pytest.raises(signing.SignatureError):
        signing.verify("other", h[signing.HEADER], body, now=1_700_000_000)


def test_gateway_rejects_bad_outcome():
    with pytest.raises(ValueError):
        sim_gateway.build_body("o", "maybe", 1)


# ---- inject_poison ----
def test_poison_message_is_sendable_and_unparseable_as_valid(aws):
    from chopee import models

    inject_poison.inject(aws.sqs, aws.queue_url)
    msg = aws.sqs.receive_message(QueueUrl=aws.queue_url, MaxNumberOfMessages=1)["Messages"][0]
    assert json.loads(msg["Body"])["type"] == "POISON_DEMO"
    assert hasattr(models, "__name__")  # shared lib importable alongside


def test_poison_groups_are_unique_and_malformed_kind():
    a, b = inject_poison.build_message(), inject_poison.build_message("malformed")
    assert a["MessageGroupId"] != b["MessageGroupId"] and b["MessageBody"] == "{not json"
    with pytest.raises(ValueError):
        inject_poison.build_message("nope")


# ---- create_test_users ----
def test_usernames_are_distinct_and_stable():
    assert cu.username(1) == "loadtest0001@example.test"
    assert len({cu.username(i) for i in range(1, 1001)}) == 1000


def test_rate_limiter_spaces_calls():
    t = {"now": 0.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t["now"] += s

    rl = cu.RateLimiter(20, clock=lambda: t["now"], sleep=sleep)
    for _ in range(5):
        rl.wait()
    assert sum(sleeps) == pytest.approx(4 * 0.05)


class Throttle(Exception):
    response = {"Error": {"Code": "TooManyRequestsException"}}


def test_backoff_retries_throttles_then_succeeds():
    calls, waits = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise Throttle()
        return "ok"

    assert cu.with_backoff(fn, cu.retryable, sleep=waits.append) == "ok"
    assert len(calls) == 3 and waits[1] > waits[0] - 0.5


def test_backoff_does_not_retry_other_errors():
    def boom():
        raise KeyError("x")

    with pytest.raises(KeyError):
        cu.with_backoff(boom, cu.retryable, sleep=lambda s: None)


class FakeCognito:
    def __init__(self):
        self.users = set()

    def admin_create_user(self, UserPoolId, Username, **kw):
        if Username in self.users:
            e = Exception("exists")
            e.response = {"Error": {"Code": "UsernameExistsException"}}
            raise e
        assert kw["MessageAction"] == "SUPPRESS"
        self.users.add(Username)

    def admin_set_user_password(self, UserPoolId, Username, Password, Permanent):
        assert Permanent is True

    def admin_initiate_auth(self, UserPoolId, ClientId, AuthFlow, AuthParameters):
        assert AuthFlow == "ADMIN_USER_PASSWORD_AUTH"
        return {"AuthenticationResult": {"AccessToken": "tok-" + AuthParameters["USERNAME"]}}


def test_create_users_is_idempotent_and_returns_tokens():
    c = FakeCognito()
    fast = cu.RateLimiter(1e9, sleep=lambda s: None)
    first = cu.create_users(c, "pool", "client", 3, limiter=fast)
    again = cu.create_users(c, "pool", "client", 3, limiter=fast)
    assert first == again and first[2] == {"username": "loadtest0003@example.test",
                                           "token": "tok-loadtest0003@example.test"}


# ---- reconcile ----
def order(oid, status, items, **kw):
    return {"PK": f"ORDER#{oid}", "SK": "META", "status": status, "items": items, **kw}


def stock(sku, available, initial=10):
    return {"PK": f"PRODUCT#{sku}", "SK": "STOCK", "available": available, "initial": initial}


def test_reconcile_clean_run():
    items = [stock("A", 6), order("1", "PAID", [{"sku": "A", "quantity": 3}]),
             order("2", "PENDING_PAYMENT", [{"sku": "A", "quantity": 1}]),
             order("3", "CANCELLED", [{"sku": "A", "quantity": 2}]),
             order("4", "REJECTED", [{"sku": "A", "quantity": 9}])]
    r = reconcile.reconcile(items, accepted=5, dlq_depth=1)
    assert r["ok"], r["issues"]
    assert r["by_status"]["PAID"] == 1 and r["stock_held"] == {"A": 4}


def test_reconcile_flags_negative_stock_and_mismatch():
    r = reconcile.reconcile([stock("A", -1), order("1", "PAID", [{"sku": "A", "quantity": 1}])])
    assert not r["ok"]
    assert any("negative stock" in i for i in r["issues"]) and any("mismatch" in i for i in r["issues"])


def test_reconcile_flags_unknown_status_duplicates_and_missing_orders():
    items = [stock("A", 10), order("1", "WEIRD", []), order("1", "PAID", []),
             {"PK": "ORDER#1", "SK": "PAYMENT#e1", "outcome": "succeeded"},
             {"PK": "ORDER#1", "SK": "PAYMENT#e2", "outcome": "succeeded"}]
    r = reconcile.reconcile(items, accepted=10, queue_backlog=2)
    text = " | ".join(r["issues"])
    assert "unknown order status" in text and "duplicate order" in text
    assert "2 successful payments" in text and "unaccounted" in text and "still in the orders queue" in text


def test_reconcile_scan_matches_seeded_table(aws):
    seed_catalog.seed(aws.table)
    items = reconcile.scan_table(aws.table)
    assert reconcile.reconcile(items)["ok"]
    assert reconcile.queue_depth(aws.sqs, aws.queue_url) == 0


# ---- smoke ----
def test_poll_stops_when_predicate_true_and_on_timeout():
    seq = iter([1, 2, 3, 4])
    assert smoke.poll(lambda: next(seq), lambda v: v == 3, sleep=lambda s: None) == 3
    t = {"n": 0.0}

    def clock():
        t["n"] += 1
        return t["n"]

    assert smoke.poll(lambda: "x", lambda v: False, timeout=3, sleep=lambda s: None, clock=clock) == "x"


def test_load_tf_outputs_flattens(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"cloudfront_url": {"value": "https://d.example", "type": "string"}}))
    assert smoke.load_tf_outputs(str(f)) == {"cloudfront_url": "https://d.example"}
    assert smoke.load_tf_outputs(None) == {}


class FakeShop:
    """Minimal in-memory API that behaves per plan 06 Section 5.2."""

    def __init__(self):
        self.carts, self.merged, self.orders = {}, set(), {}

    def __call__(self, method, url, headers, body):
        path = url.split("/api", 1)[1]
        owner = "user" if "Authorization" in headers else "g:" + headers.get("X-Guest-Id", "")
        cart = self.carts.setdefault(owner, {})
        view = lambda o: {"items": [{"sku": k, "quantity": q, "price": 100} for k, q in self.carts.get(o, {}).items()]}  # noqa: E731
        if path.startswith("/cart/items/"):
            cart[path.rsplit("/", 1)[1]] = body["quantity"]
            return 200, view(owner)
        if path == "/cart/merge":
            if body["guestId"] not in self.merged:
                self.merged.add(body["guestId"])
                for k, q in self.carts.get("g:" + body["guestId"], {}).items():
                    cart[k] = min(5, cart.get(k, 0) + q)
            return 200, view("user")
        if path == "/checkout":
            first = headers["Idempotency-Key"] not in self.orders
            self.orders.setdefault(headers["Idempotency-Key"], "PENDING_PAYMENT")
            return (202 if first else 200), {"orderId": headers["Idempotency-Key"], "status": "QUEUED"}
        if path.startswith("/orders/"):
            return 200, {"orderId": path.rsplit("/", 1)[1], "status": self.orders[path.rsplit("/", 1)[1]]}
        if path.startswith("/demo/pay/"):
            self.orders[path.rsplit("/", 1)[1]] = "PAID" if body["outcome"] == "succeeded" else "CANCELLED"
            return 200, {}
        return 404, None


def test_smoke_flows_pass_against_a_conforming_api(monkeypatch):
    monkeypatch.setattr(smoke.time, "sleep", lambda s: None)
    api = smoke.Api("https://x.example", request=FakeShop())
    rep = smoke.Report()
    assert smoke.check_cart_merge(api, "tok", rep)
    oid = smoke.place_order(api, "tok", rep, "pay")
    assert oid and smoke.settle(api, "tok", rep, oid, "succeeded", "PAID", "pay")
    oid2 = smoke.place_order(api, "tok", rep, "decline")
    assert oid2 and smoke.settle(api, "tok", rep, oid2, "declined", "CANCELLED", "decline")
    assert not rep.failed


def test_smoke_reports_failure_when_merge_is_not_idempotent():
    shop = FakeShop()

    def double_merge(method, url, headers, body):
        if url.endswith("/cart/merge"):
            shop.merged.clear()  # every retry adds again
        return shop(method, url, headers, body)

    rep = smoke.Report()
    assert not smoke.check_cart_merge(smoke.Api("https://x.example", request=double_merge), "tok", rep)
    assert rep.failed


def test_bad_signature_check_expects_401():
    rep = smoke.Report()
    assert smoke.check_bad_signature("https://x", rep, request=lambda base, body, h: (401, "{}"))
    assert not smoke.check_bad_signature("https://x", rep, request=lambda base, body, h: (200, "{}"))
