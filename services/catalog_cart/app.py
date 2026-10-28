"""catalog-cart service: catalog reads, guest/user carts and guest-cart merge (plan 06 Section 5.2).

Cart and merge logic is ported from aws-samples/aws-serverless-shopping-cart (MIT-0): anonymous cart keyed
by a UUID, quantities summed on login. Here the merge is made idempotent with a marker item.
"""
from __future__ import annotations

import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from chopee import keys
from chopee.auth import AuthError, JwtVerifier
from chopee.logging import get_logger
from chopee.models import MAX_QTY, is_uuid4

CATALOG_TTL_SECONDS = 30
_SER, _DES = TypeSerializer(), TypeDeserializer()
log = get_logger("catalog-cart")


def _plain(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _item(raw: dict) -> dict:
    return {k: _DES.deserialize(v) for k, v in raw.items()}


def _ddb_item(item: dict) -> dict:
    return {k: _SER.serialize(v) for k, v in item.items()}


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def create_app(
    ddb=None,
    verifier: JwtVerifier | None = None,
    table_name: str | None = None,
    clock=time.time,
) -> FastAPI:
    table = table_name or os.environ.get("TABLE_NAME", keys.TABLE_NAME)
    if ddb is None:
        ddb = boto3.client(
            "dynamodb",
            config=Config(max_pool_connections=64, retries={"mode": "standard"}),
        )
    if verifier is None:
        verifier = JwtVerifier(
            os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1")),
            os.environ["USER_POOL_ID"],
            os.environ["COGNITO_CLIENT_ID"],
        )
    app = FastAPI(title="chopee catalog-cart", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if request.url.path != "/api/healthz":
            log.info("http_request", extra={"fields": {
                "method": request.method, "path": request.url.path, "status": response.status_code,
                "durationMs": round((time.perf_counter() - started) * 1000, 1)}})
        return response
    cache: dict = {"at": 0.0, "items": None}

    # ---- data access -------------------------------------------------------------------------
    def get_product(sku: str) -> dict | None:
        raw = ddb.get_item(TableName=table, Key=_ddb_item(keys.product_key(sku)))
        return _plain(_item(raw["Item"])) if "Item" in raw else None

    def load_catalog() -> list[dict]:
        now = clock()
        if cache["items"] is not None and now - cache["at"] < CATALOG_TTL_SECONDS:
            return cache["items"]
        products: list[dict] = []
        kwargs = {
            "TableName": table,
            "IndexName": keys.GSI1,
            "KeyConditionExpression": "GSI1PK = :p",
            "ExpressionAttributeValues": {":p": {"S": keys.CATALOG_GSI1PK}},
        }
        while True:
            page = ddb.query(**kwargs)
            products += [_plain(_item(i)) for i in page["Items"]]
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        stock: dict[str, int] = {}
        for i in range(0, len(products), 100):
            chunk = products[i : i + 100]
            resp = ddb.batch_get_item(
                RequestItems={table: {"Keys": [_ddb_item(keys.stock_key(p["PK"].split("#", 1)[1])) for p in chunk]}}
            )
            for raw in resp["Responses"].get(table, []):
                s = _plain(_item(raw))
                stock[s["PK"]] = s.get("available", 0)
        items = [
            {
                "sku": p["PK"].split("#", 1)[1],
                "name": p.get("name"),
                "price": p.get("price"),
                "currency": p.get("currency", "SGD"),
                "description": p.get("description", ""),
                "emoji": p.get("emoji", ""),
                "inStock": stock.get(p["PK"], 0) > 0,
            }
            for p in products
        ]
        items.sort(key=lambda p: p["sku"])
        cache.update(at=now, items=items)
        return items

    def cart_lines(owner: str) -> list[dict]:
        resp = ddb.query(
            TableName=table,
            KeyConditionExpression="PK = :p AND begins_with(SK, :s)",
            ExpressionAttributeValues={":p": {"S": keys.cart_pk(owner)}, ":s": {"S": "ITEM#"}},
        )
        lines = [_plain(_item(i)) for i in resp["Items"]]
        if owner.startswith("GUEST#"):  # application rejects guest lines older than 24 h
            cutoff = clock() - keys.GUEST_CART_TTL_SECONDS
            lines = [ln for ln in lines if ln.get("updatedAt", 0) >= cutoff]
        return lines

    def render_cart(owner: str) -> dict:
        items, total = [], 0
        for ln in sorted(cart_lines(owner), key=lambda x: x["SK"]):
            sku = ln["SK"].split("#", 1)[1]
            product = get_product(sku)
            if product is None:
                continue
            items.append({"sku": sku, "quantity": ln["quantity"], "price": product["price"]})
            total += product["price"] * ln["quantity"]
        return {"items": items, "total": total}

    def resolve_owner(request: Request) -> tuple[str | None, JSONResponse | None]:
        auth = request.headers.get("authorization")
        if auth:
            try:
                return keys.user_owner(verifier.subject(auth)), None
            except AuthError:
                return None, _err(401, "unauthorized")
        guest = request.headers.get("x-guest-id")
        if guest and is_uuid4(guest):
            return keys.guest_owner(guest.lower()), None
        return None, _err(401, "JWT or X-Guest-Id required")

    # ---- routes ------------------------------------------------------------------------------
    @app.get("/api/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/catalog")
    def catalog():
        return load_catalog()

    @app.get("/api/catalog/{sku}")
    def catalog_item(sku: str):
        for p in load_catalog():
            if p["sku"] == sku:
                return p
        return _err(404, "unknown sku")

    @app.get("/api/cart")
    def get_cart(request: Request):
        owner, error = resolve_owner(request)
        return error or render_cart(owner)

    @app.put("/api/cart/items/{sku}")
    async def put_item(sku: str, request: Request):
        owner, error = resolve_owner(request)
        if error:
            return error
        try:
            body = await request.json()
            qty = body["quantity"]
        except Exception:
            return _err(400, "body must be {quantity: 0..5}")
        if isinstance(qty, bool) or not isinstance(qty, int) or not 0 <= qty <= MAX_QTY:
            return _err(400, "quantity must be 0..5")
        return await run_in_threadpool(store_item, owner, sku, qty)

    def store_item(owner: str, sku: str, qty: int):
        if get_product(sku) is None:
            return _err(404, "unknown sku")
        key = _ddb_item(keys.cart_item_key(owner, sku))
        if qty == 0:
            ddb.delete_item(TableName=table, Key=key)
        else:
            now = int(clock())
            item = {**keys.cart_item_key(owner, sku), "quantity": qty, "updatedAt": now}
            if owner.startswith("GUEST#"):
                item["ttl"] = now + keys.GUEST_CART_TTL_SECONDS
            ddb.put_item(TableName=table, Item=_ddb_item(item))
        return render_cart(owner)

    @app.post("/api/cart/merge")
    async def merge(request: Request):
        auth = request.headers.get("authorization")
        try:
            sub = verifier.subject(auth)
        except AuthError:
            return _err(401, "unauthorized")
        try:
            guest_id = (await request.json())["guestId"]
        except Exception:
            return _err(400, "body must be {guestId}")
        if not isinstance(guest_id, str) or not is_uuid4(guest_id):
            return _err(400, "guestId must be a UUID")
        return await run_in_threadpool(merge_carts, sub, guest_id.lower())

    def merge_carts(sub: str, guest_id: str):
        user_owner, guest_owner = keys.user_owner(sub), keys.guest_owner(guest_id)
        user_qty = {ln["SK"]: ln["quantity"] for ln in cart_lines(user_owner)}
        merged = dict(user_qty)
        for ln in cart_lines(guest_owner):
            merged[ln["SK"]] = min(MAX_QTY, merged.get(ln["SK"], 0) + ln["quantity"])
        now = int(clock())
        ops = [
            {
                "Put": {
                    "TableName": table,
                    "Item": _ddb_item({**keys.merge_marker_key(sub, guest_id), "mergedAt": now}),
                    "ConditionExpression": "attribute_not_exists(PK)",
                }
            }
        ]
        for sk, qty in merged.items():
            sku = sk.split("#", 1)[1]
            if get_product(sku) is None:  # drop lines whose product has gone
                continue
            ops.append(
                {
                    "Put": {
                        "TableName": table,
                        "Item": _ddb_item(
                            {"PK": keys.cart_pk(user_owner), "SK": sk, "quantity": qty, "updatedAt": now}
                        ),
                    }
                }
            )
        try:
            ddb.transact_write_items(TransactItems=ops)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            reasons = exc.response.get("CancellationReasons", [])
            if not reasons or reasons[0].get("Code") != "ConditionalCheckFailed":
                raise
            # marker already exists: this merge already ran, so add nothing
        else:
            for ln in cart_lines(guest_owner):  # best-effort cleanup; TTL covers failures
                ddb.delete_item(TableName=table, Key=_ddb_item({"PK": keys.cart_pk(guest_owner), "SK": ln["SK"]}))
            log.info("cart_merged", extra={"fields": {"lines": len(ops) - 1}})
        return render_cart(user_owner)

    return app


def build_app() -> FastAPI:  # uvicorn --factory services.catalog_cart.app:build_app
    return create_app()
