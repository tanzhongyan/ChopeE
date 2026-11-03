"""checkout service: idempotent checkout, order reads and the payment webhook (plan 06 Section 5.2)."""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from chopee import keys, signing
from chopee.auth import AuthError, JwtVerifier
from chopee.logging import get_logger, pseudonymise
from chopee.models import is_uuid4, order_placed, payment_result, validate_lines
from chopee.tracing import XRayMiddleware, annotate_order, current_trace_header, init_tracing

OUTCOMES = ("succeeded", "declined")
log = get_logger("checkout")


def _plain(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _err(status: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers=headers)


def emit_metric(name: str, value: int = 1) -> None:
    """CloudWatch Embedded Metric Format line on stdout (no API call)."""
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {"Namespace": "chopee", "Dimensions": [["service"]], "Metrics": [{"Name": name, "Unit": "Count"}]}
                    ],
                },
                "service": "checkout",
                name: value,
            }
        ),
        flush=True,
    )


def _public_order(order: dict) -> dict:
    return {
        "orderId": order["PK"].split("#", 1)[1],
        "status": order["status"],
        "reason": order.get("reason"),
        "items": order.get("items", []),
        "total": order.get("total"),
        "createdAt": order.get("createdAt"),
        "expiresAt": order.get("expiresAt"),
    }


def create_app(
    table=None,
    sqs=None,
    queue_url: str | None = None,
    verifier: JwtVerifier | None = None,
    webhook_secret: str | None = None,
    demo_gateway: bool | None = None,
    log_salt: str | None = None,
) -> FastAPI:
    cfg = Config(max_pool_connections=64, retries={"mode": "standard"})
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1"))
    if table is None:
        table = boto3.resource("dynamodb", config=cfg).Table(os.environ.get("TABLE_NAME", keys.TABLE_NAME))
    if sqs is None:
        sqs = boto3.client("sqs", config=cfg)
    queue_url = queue_url or os.environ.get("QUEUE_URL", "")
    if verifier is None:
        verifier = JwtVerifier(region, os.environ["USER_POOL_ID"], os.environ["COGNITO_CLIENT_ID"])
    secret = webhook_secret if webhook_secret is not None else os.environ.get("WEBHOOK_SECRET", "")
    demo = demo_gateway if demo_gateway is not None else os.environ.get("DEMO_GATEWAY", "").lower() == "true"
    salt = log_salt if log_salt is not None else os.environ.get("LOG_SALT", "")
    if not secret or not salt:  # fail closed: an empty HMAC key is forgeable (plan 05b SEC-2)
        raise RuntimeError("WEBHOOK_SECRET and LOG_SALT must be set")

    @asynccontextmanager
    async def lifespan(_app):
        # Warm the JWKS cache so the first request never fetches on the loop; fail-static.
        try:
            await run_in_threadpool(verifier._keys)
        except Exception:
            log.warning("jwks_warmup_failed")
        yield

    app = FastAPI(title="chopee checkout", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    init_tracing("checkout", async_context=True)
    app.add_middleware(XRayMiddleware)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if request.url.path != "/api/healthz":
            log.info("http_request", extra={"fields": {
                "method": request.method, "path": request.url.path, "status": response.status_code,
                "durationMs": round((time.perf_counter() - started) * 1000, 1)}})
        return response

    def customer_ref(sub: str) -> str:
        return pseudonymise(salt, sub)

    def get_order(order_id: str) -> dict | None:
        item = table.get_item(Key=keys.order_key(order_id), ConsistentRead=True).get("Item")
        return _plain(item) if item else None

    def authenticate(request: Request) -> tuple[str | None, JSONResponse | None]:
        try:
            return verifier.subject(request.headers.get("authorization")), None
        except AuthError:
            return None, _err(401, "unauthorized")

    def check_signature(raw_body: str, signature: str | None) -> JSONResponse | None:
        """Verify the HMAC once; returns the 401 response on failure, else None."""
        try:
            signing.verify(secret, signature, raw_body)
        except signing.SignatureError:
            emit_metric("WebhookSignatureFailures")
            log.warning("webhook_signature_failure")
            return _err(401, "invalid signature")
        return None

    def parse_event(raw_body: str):
        try:
            return json.loads(raw_body)
        except (ValueError, RecursionError):
            return None

    def enqueue_payment(event) -> JSONResponse:
        """Validate an already-authenticated payment event and enqueue it."""
        try:
            event_id, order_id = event["eventId"], event["orderId"]
            outcome, amount, currency = event["outcome"], event["amount"], event["currency"]
        except (KeyError, TypeError):
            return _err(400, "invalid payload")
        if (
            not isinstance(event_id, str) or not event_id or not isinstance(order_id, str)
            or outcome not in OUTCOMES or isinstance(amount, bool) or not isinstance(amount, int)
            or not isinstance(currency, str)
        ):
            return _err(400, "invalid payload")
        order = get_order(order_id)
        if order is None:
            return _err(404, "unknown order")
        if amount != order["total"] or currency != order.get("currency", "SGD"):
            return _err(422, "amount or currency mismatch")
        msg = payment_result(order_id, order["customerId"], event_id, outcome, amount, currency)
        try:
            sqs.send_message(**msg.to_send_kwargs(queue_url))
        except Exception:
            log.error("enqueue_failed", extra={"fields": {"orderId": order_id, "customerRef": customer_ref(order["customerId"])}})
            return _err(503, "queue unavailable, retry", headers={"Retry-After": "1"})
        log.info(
            "payment_event_accepted",
            extra={"fields": {"orderId": order_id, "outcome": outcome, "customerRef": customer_ref(order["customerId"])}},
        )
        return JSONResponse({"received": True})

    def verify_and_enqueue(raw_body: str, signature: str | None) -> JSONResponse:
        """Used by demo pay: the same verify step as the public webhook, then the shared enqueue."""
        failure = check_signature(raw_body, signature)
        if failure:
            return failure
        return enqueue_payment(parse_event(raw_body))

    def claim_order(order_id: str, sub: str) -> JSONResponse | None:
        """Reserve the idempotency key before SendMessage (API-5). Returns an error response or None."""
        try:
            table.put_item(
                Item={**keys.claim_key(order_id), "customerId": sub, "ttl": int(time.time()) + keys.CLAIM_TTL_SECONDS},
                ConditionExpression="attribute_not_exists(PK)",
            )
            return None
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                log.error("claim_failed", extra={"fields": {"orderId": order_id, "customerRef": customer_ref(sub)}})
                return _err(503, "retry", headers={"Retry-After": "1"})
        except Exception:
            log.error("claim_failed", extra={"fields": {"orderId": order_id, "customerRef": customer_ref(sub)}})
            return _err(503, "retry", headers={"Retry-After": "1"})
        try:
            claim = table.get_item(Key=keys.claim_key(order_id), ConsistentRead=True).get("Item")
        except Exception:
            return _err(503, "retry", headers={"Retry-After": "1"})
        if claim is not None and claim.get("customerId") != sub:
            return _err(409, "idempotency key belongs to another customer")
        return None  # same customer retry: re-send is deduplicated by SQS

    @app.get("/api/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/api/checkout")
    async def checkout(request: Request):
        sub, error = await run_in_threadpool(authenticate, request)
        if error:
            return error
        order_id = request.headers.get("idempotency-key", "")
        if not is_uuid4(order_id):
            return _err(400, "Idempotency-Key must be a UUID v4")
        order_id = order_id.lower()
        annotate_order(order_id)
        try:
            lines = validate_lines((await request.json())["items"])
        except (ValueError, KeyError, TypeError) as exc:
            return _err(400, f"invalid items: {exc}")
        existing = await run_in_threadpool(get_order, order_id)
        if existing is not None:
            if existing["customerId"] != sub:
                return _err(409, "idempotency key belongs to another customer")
            return JSONResponse({"orderId": order_id, "status": existing["status"]}, status_code=200)
        rejected = await run_in_threadpool(claim_order, order_id, sub)
        if rejected is not None:
            return rejected
        accepted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        trace_id = current_trace_header() or request.headers.get("x-amzn-trace-id", "")
        msg = order_placed(order_id, sub, lines, accepted_at, trace_id)
        try:
            await run_in_threadpool(lambda: sqs.send_message(**msg.to_send_kwargs(queue_url)))
        except Exception:
            log.error("enqueue_failed", extra={"fields": {"orderId": order_id, "customerRef": customer_ref(sub)}})
            return _err(503, "queue unavailable, retry", headers={"Retry-After": "1"})
        log.info("order_transition", extra={"fields": {"orderId": order_id, "toStatus": keys.ORDER_QUEUED, "customerRef": customer_ref(sub)}})
        return JSONResponse({"orderId": order_id, "status": keys.ORDER_QUEUED}, status_code=202)

    @app.get("/api/orders")
    def list_orders(request: Request):
        sub, error = authenticate(request)
        if error:
            return error
        resp = table.query(
            IndexName=keys.GSI1,
            KeyConditionExpression=Key("GSI1PK").eq(f"CUSTOMER#{sub}") & Key("GSI1SK").begins_with("ORDER#"),
            ScanIndexForward=False,
            Limit=20,
        )
        return [_public_order(_plain(i)) for i in resp["Items"]]

    @app.get("/api/orders/{order_id}")
    async def read_order(order_id: str, request: Request):
        sub, error = await run_in_threadpool(authenticate, request)
        if error:
            return error
        annotate_order(order_id)
        order = await run_in_threadpool(get_order, order_id)
        if order is None or order["customerId"] != sub:  # same answer: do not reveal other customers' orders
            return _err(404, "order not found")
        return _public_order(order)

    @app.post("/api/webhooks/payment")
    async def webhook(request: Request):
        raw = (await request.body()).decode("utf-8", errors="replace")
        signature = request.headers.get(signing.HEADER)
        failure = check_signature(raw, signature)  # the only signature check on this path
        if failure:
            return failure
        payload = parse_event(raw)
        if isinstance(payload, dict) and isinstance(payload.get("orderId"), str):
            # Annotate only authenticated payloads, in the async context where the X-Ray segment is active.
            annotate_order(payload["orderId"])
        return await run_in_threadpool(enqueue_payment, payload)

    @app.post("/api/demo/pay/{order_id}")
    async def demo_pay(order_id: str, request: Request):
        if not demo:
            return _err(404, "not found")
        sub, error = await run_in_threadpool(authenticate, request)
        if error:
            return error
        try:
            outcome = (await request.json())["outcome"]
        except Exception:
            return _err(400, "body must be {outcome}")
        if outcome not in OUTCOMES:
            return _err(400, "outcome must be succeeded or declined")
        annotate_order(order_id)
        order = await run_in_threadpool(get_order, order_id)
        if order is None or order["customerId"] != sub:
            return _err(404, "order not found")
        if order["status"] != keys.ORDER_PENDING_PAYMENT:
            return _err(409, "order not pending")
        event = {
            "eventId": f"demo-{uuid.uuid4()}",
            "orderId": order_id,
            "outcome": outcome,
            "amount": order["total"],
            "currency": order.get("currency", "SGD"),
            "occurredAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        raw = json.dumps(event, separators=(",", ":"))
        return await run_in_threadpool(verify_and_enqueue, raw, signing.sign(secret, raw))

    return app


def build_app() -> FastAPI:  # uvicorn --factory services.checkout.app:build_app
    return create_app()
