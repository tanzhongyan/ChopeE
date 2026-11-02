"""Owner 5 security checks (plan 05b): JWKS caching, HMAC drift and fail-closed secrets, PDPA log fields."""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import jwt
import pytest
from chopee import signing
from chopee.auth import (
    JWKS_MIN_REFRESH_SECONDS,
    JWKS_TTL_SECONDS,
    AuthError,
    JwtVerifier,
)

from tests.conftest import CLIENT_ID, POOL_ID, REGION

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sim_gateway

BODY = json.dumps({"eventId": "e1", "orderId": "o1", "amount": 100}, separators=(",", ":"))


# ---------------------------------------------------------------- SEC-1 JWKS cache


class Clock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def fetching(jwks, monkeypatch):
    """A verifier with no injected keys whose fetches are counted and scriptable."""
    clock = Clock()
    calls = []
    responses = []

    def fake_fetch(self):
        calls.append(clock.t)
        result = responses.pop(0) if responses else jwks
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(JwtVerifier, "_fetch", fake_fetch)
    v = JwtVerifier(REGION, POOL_ID, CLIENT_ID, clock=clock)
    return v, clock, calls, responses


def test_jwks_fetched_once_within_ttl(fetching, make_token):
    v, clock, calls, _ = fetching
    token = make_token()
    for _ in range(50):
        v.verify(token)
        clock.t += 10
    assert len(calls) == 1


def test_jwks_refetched_after_ttl(fetching, make_token):
    v, clock, calls, _ = fetching
    v.verify(make_token())
    clock.t += JWKS_TTL_SECONDS + 1
    v.verify(make_token())
    assert len(calls) == 2


def test_jwks_failed_refresh_keeps_serving_cached_keys(fetching, make_token):
    v, clock, calls, responses = fetching
    v.verify(make_token())
    clock.t += JWKS_TTL_SECONDS + 1
    responses.append(OSError("cognito unreachable"))
    assert v.verify(make_token())["sub"] == "user-1"  # fail-static, not a 401 storm
    clock.t += 1
    v.verify(make_token())
    assert len(calls) == 2  # failed refresh is not retried on every request


def test_jwks_unavailable_on_cold_start_is_an_auth_error(fetching, make_token):
    v, _, _, responses = fetching
    responses.append(OSError("down"))
    with pytest.raises(AuthError):
        v.verify(make_token())


def test_jwks_empty_key_set_is_ignored(fetching, make_token):
    v, clock, _, responses = fetching
    v.verify(make_token())
    clock.t += JWKS_TTL_SECONDS + 1
    responses.append({"keys": []})
    assert v.verify(make_token())["sub"] == "user-1"


def test_jwks_rotation_picks_up_new_kid(fetching, jwks, make_token):
    v, clock, calls, responses = fetching
    v.verify(make_token())
    rotated = {"keys": [{**jwks["keys"][0], "kid": "rotated"}]}
    clock.t += JWKS_MIN_REFRESH_SECONDS + 1
    responses.append(rotated)
    assert v.verify(make_token(kid="rotated"))["sub"] == "user-1"
    assert len(calls) == 2


def test_jwks_unknown_kid_refresh_is_rate_limited(fetching, make_token):
    v, clock, calls, _ = fetching
    v.verify(make_token())
    clock.t += JWKS_MIN_REFRESH_SECONDS + 1
    for i in range(20):
        with pytest.raises(AuthError):
            v.verify(make_token(kid=f"forged-{i}"))
    assert len(calls) == 2  # one forced refresh, then rate-limited


def test_rejects_alg_none_and_hs256_confusion(verifier, jwks, rsa_key):
    now = int(time.time())
    claims = {"sub": "x", "iss": verifier.issuer, "token_use": "access", "client_id": CLIENT_ID,
              "iat": now, "exp": now + 600}
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": "test-kid"})
    with pytest.raises(AuthError):
        verifier.verify(unsigned)
    # HS256 keyed with the public key: the classic RS256/HS256 confusion attack.
    from cryptography.hazmat.primitives import serialization

    pem = rsa_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    header = jwt.utils.base64url_encode(json.dumps({"alg": "HS256", "kid": "test-kid", "typ": "JWT"}).encode())
    payload = jwt.utils.base64url_encode(json.dumps(claims).encode())
    sig = jwt.utils.base64url_encode(hmac.new(pem, header + b"." + payload, hashlib.sha256).digest())
    with pytest.raises(AuthError):
        verifier.verify((header + b"." + payload + b"." + sig).decode())


def test_verifier_requires_bearer_scheme(verifier, make_token):
    with pytest.raises(AuthError):
        verifier.subject("Basic " + make_token())
    with pytest.raises(AuthError):
        verifier.subject(make_token())


# ---------------------------------------------------------------- SEC-2 HMAC webhook


def test_drift_boundary_is_300_seconds_both_ways():
    hdr = signing.sign("s3cret", BODY, now=10_000)
    signing.verify("s3cret", hdr, BODY, now=10_000 + 300)
    signing.verify("s3cret", hdr, BODY, now=10_000 - 300)
    for now in (10_000 + 301, 10_000 - 301):
        with pytest.raises(signing.SignatureError, match="stale"):
            signing.verify("s3cret", hdr, BODY, now=now)


def test_empty_secret_fails_closed():
    with pytest.raises(signing.SignatureError, match="not configured"):
        signing.sign("", BODY)
    t = int(time.time())
    empty_key_sig = hmac.new(b"", f"{t}.{BODY}".encode(), hashlib.sha256).hexdigest()
    with pytest.raises(signing.SignatureError):
        signing.verify("", f"t={t},v1={empty_key_sig}", BODY)


def test_non_ascii_signature_is_rejected_not_crashing():
    t = int(time.time())
    with pytest.raises(signing.SignatureError, match="bad"):
        signing.verify("s3cret", f"t={t},v1=café", BODY)


def test_header_with_spaces_parses():
    hdr = signing.sign("s3cret", BODY, now=5000).replace(",", ", ")
    signing.verify("s3cret", hdr, BODY, now=5000)


def test_sim_gateway_stale_and_tamper_are_rejected():
    now = 1_700_000_000
    body = sim_gateway.build_body("o-1", "succeeded", 1200, event_id="e-1", now=now)
    stale = sim_gateway.signed_request("s3cret", body, sim_gateway.stale_now(now))
    with pytest.raises(signing.SignatureError, match="stale"):
        signing.verify("s3cret", stale[signing.HEADER], body, now=now)
    fresh = sim_gateway.signed_request("s3cret", body, now)
    tampered = sim_gateway.tamper(body)
    assert json.loads(tampered)["amount"] == 1201
    with pytest.raises(signing.SignatureError, match="bad"):
        signing.verify("s3cret", fresh[signing.HEADER], tampered, now=now)


@pytest.mark.parametrize("flag, status, code", [
    ([], 200, 0), (["--bad-signature"], 401, 0), (["--stale"], 401, 0), (["--tamper"], 401, 0),
    (["--stale"], 200, 1),
])
def test_sim_gateway_exit_status_matches_expectation(monkeypatch, flag, status, code):
    sent = []
    monkeypatch.setattr(sim_gateway, "send", lambda base, body, headers: sent.append((body, headers)) or (status, ""))
    argv = ["--base-url", "http://x", "--order-id", "o", "--amount", "100", "--secret", "s3cret", *flag]
    assert sim_gateway.main(argv) == code
    body, _headers = sent[0]
    if flag == ["--tamper"]:
        assert json.loads(body)["amount"] == 101


def test_checkout_refuses_to_start_without_secrets(aws, verifier):
    from services.checkout.app import create_app

    for secret, salt in (("", "salt"), ("secret", "")):
        with pytest.raises(RuntimeError):
            create_app(table=aws.table, sqs=aws.sqs, queue_url=aws.queue_url, verifier=verifier,
                       webhook_secret=secret, log_salt=salt)


# ---------------------------------------------------------------- SEC-3 PDPA logging

FORBIDDEN_LOG_FIELDS = {"customerid", "sub", "email", "token", "authorization", "password", "body", "payload",
                        "accesstoken", "idtoken", "refreshtoken"}
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _log_field_keys(tree: ast.AST) -> list[tuple[int, str]]:
    """Keys of every ``fields`` dict passed via ``log.<level>(..., extra={"fields": ...})``."""
    assigned: dict[str, ast.Dict] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = node.value
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS):
            continue
        for kw in node.keywords:
            if kw.arg != "extra" or not isinstance(kw.value, ast.Dict):
                continue
            for k, v in zip(kw.value.keys, kw.value.values):
                if isinstance(k, ast.Constant) and k.value == "fields":
                    fields = assigned.get(v.id) if isinstance(v, ast.Name) else v
                    assert isinstance(fields, ast.Dict), f"line {node.lineno}: fields must be a literal dict"
                    found += [(node.lineno, fk.value) for fk in fields.keys if isinstance(fk, ast.Constant)]
    return found


def test_no_log_call_site_names_a_personal_field():
    sources = sorted((ROOT / "services").rglob("*.py")) + sorted((ROOT / "functions").rglob("*.py"))
    seen = 0
    for path in sources:
        for line, key in _log_field_keys(ast.parse(path.read_text(encoding="utf-8"))):
            seen += 1
            assert key.lower() not in FORBIDDEN_LOG_FIELDS, f"{path.relative_to(ROOT)}:{line} logs '{key}'"
    assert seen >= 15  # the scan really found the structured log calls

