#!/usr/bin/env python3
"""Create N Cognito test users and write their access tokens to loadtest/tokens.json (plan 06 Section 6.4)."""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

PASSWORD = "ChopeE-Demo-1!"


def username(i: int) -> str:
    return f"loadtest{i:04d}@example.test"


class RateLimiter:
    """Allow at most `rate` calls per second."""

    def __init__(self, rate: float, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep, self._next = 1.0 / rate, clock, sleep, 0.0

    def wait(self) -> None:
        now = self.clock()
        if now < self._next:
            self.sleep(self._next - now)
            now = self._next
        self._next = now + self.interval


def with_backoff(fn, is_retryable, attempts: int = 6, base: float = 0.5, sleep=time.sleep):
    """Call fn(); on a retryable error wait base*2^n (+jitter) and retry."""
    for n in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if n == attempts - 1 or not is_retryable(exc):
                raise
            sleep(base * 2**n + random.uniform(0, base))


def _code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def retryable(exc: Exception) -> bool:
    return _code(exc) in ("TooManyRequestsException", "ThrottlingException", "LimitExceededException")


def ensure_user(cognito, pool_id: str, name: str, password: str) -> None:
    try:
        cognito.admin_create_user(UserPoolId=pool_id, Username=name, MessageAction="SUPPRESS",
                                  UserAttributes=[{"Name": "email", "Value": name},
                                                  {"Name": "email_verified", "Value": "true"}])
    except Exception as exc:  # noqa: BLE001
        if _code(exc) != "UsernameExistsException":
            raise
    cognito.admin_set_user_password(UserPoolId=pool_id, Username=name, Password=password, Permanent=True)


def get_token(cognito, pool_id: str, client_id: str, name: str, password: str) -> str:
    res = cognito.admin_initiate_auth(
        UserPoolId=pool_id, ClientId=client_id, AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": name, "PASSWORD": password})
    return res["AuthenticationResult"]["AccessToken"]


def create_users(cognito, pool_id, client_id, count, password=PASSWORD, rate=20.0,
                 limiter: RateLimiter | None = None, sleep=time.sleep) -> list[dict]:
    limiter = limiter or RateLimiter(rate)
    out = []
    for i in range(1, count + 1):
        name = username(i)
        limiter.wait()
        with_backoff(lambda: ensure_user(cognito, pool_id, name, password), retryable, sleep=sleep)
        limiter.wait()
        token = with_backoff(lambda: get_token(cognito, pool_id, client_id, name, password), retryable, sleep=sleep)
        out.append({"username": name, "token": token})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user-pool-id", required=True)
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--rate", type=float, default=20.0, help="max Cognito admin calls per second")
    ap.add_argument("--password", default=PASSWORD)
    ap.add_argument("--region", default="ap-southeast-1")
    ap.add_argument("--out", default="loadtest/tokens.json")
    args = ap.parse_args(argv)
    import boto3

    cognito = boto3.client("cognito-idp", region_name=args.region)
    tokens = create_users(cognito, args.user_pool_id, args.client_id, args.count, args.password, args.rate)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(tokens))
    print(f"wrote {len(tokens)} tokens to {args.out} (git-ignored; access tokens are valid 3 h)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
