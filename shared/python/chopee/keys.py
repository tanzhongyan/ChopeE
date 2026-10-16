"""DynamoDB key builders and constants for the single table (plan 06 Section 5.1)."""
from __future__ import annotations

TABLE_NAME = "chopee"
GSI1 = "GSI1"
CATALOG_GSI1PK = "CATALOG"

ORDER_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_PAID = "PAID"
ORDER_CANCELLED = "CANCELLED"
ORDER_REJECTED = "REJECTED"
ORDER_QUEUED = "QUEUED"  # API-only: no order item exists yet
ORDER_STATUSES = (ORDER_PENDING_PAYMENT, ORDER_PAID, ORDER_CANCELLED, ORDER_REJECTED)

GUEST_CART_TTL_SECONDS = 24 * 3600
EVENT_TTL_SECONDS = 24 * 3600


def product_pk(sku: str) -> str:
    return f"PRODUCT#{sku}"


def product_key(sku: str) -> dict:
    return {"PK": product_pk(sku), "SK": "META"}


def stock_key(sku: str) -> dict:
    return {"PK": product_pk(sku), "SK": "STOCK"}


def user_owner(sub: str) -> str:
    return f"USER#{sub}"


def guest_owner(guest_id: str) -> str:
    return f"GUEST#{guest_id}"


def cart_pk(owner: str) -> str:
    return f"CART#{owner}"


def cart_item_key(owner: str, sku: str) -> dict:
    return {"PK": cart_pk(owner), "SK": f"ITEM#{sku}"}


def merge_marker_key(sub: str, guest_id: str) -> dict:
    return {"PK": cart_pk(user_owner(sub)), "SK": f"MERGED#{guest_id}"}


def order_pk(order_id: str) -> str:
    return f"ORDER#{order_id}"


def order_key(order_id: str) -> dict:
    return {"PK": order_pk(order_id), "SK": "META"}


def order_gsi1(sub: str, created_at: str) -> dict:
    return {"GSI1PK": f"CUSTOMER#{sub}", "GSI1SK": f"ORDER#{created_at}"}


def payment_key(order_id: str, gateway_event_id: str) -> dict:
    return {"PK": order_pk(order_id), "SK": f"PAYMENT#{gateway_event_id}"}


def recon_key(order_id: str, gateway_event_id: str) -> dict:
    return {"PK": order_pk(order_id), "SK": f"RECON#{gateway_event_id}"}


def event_key(event_id: str) -> dict:
    return {"PK": f"EVENT#{event_id}", "SK": "EVENT"}


def consumed_key(consumer: str, event_id: str) -> dict:
    return {"PK": f"CONSUMED#{consumer}#{event_id}", "SK": "CONSUMED"}
