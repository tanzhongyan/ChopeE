#!/usr/bin/env python3
"""Seed the catalog: 24 products x 2,000 stock plus LIMITED-01 with stock 50 (plan 06 Section 6.4)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared" / "python"))

from chopee import keys  # noqa: E402

NORMAL_STOCK = 2000
LIMITED_SKU = "LIMITED-01"
LIMITED_STOCK = 50

# (name, price in cents, emoji, description); SKUs are SKU-01..SKU-24 in this order.
PRODUCTS = [
    ("Wireless Earbuds", 5900, "🎧", "Bluetooth 5.3 earbuds with charging case."),
    ("Smartphone Case", 1290, "📱", "Shockproof clear case."),
    ("Fast Charger 65W", 3500, "🔌", "USB-C GaN wall charger."),
    ("Power Bank 20000mAh", 4500, "🔋", "Dual-port portable charger."),
    ("Mechanical Keyboard", 8900, "⌨️", "Hot-swappable 75% keyboard."),
    ("Gaming Mouse", 3900, "🖱️", "Lightweight wireless mouse, 16000 DPI."),
    ("Smartwatch", 12900, "⌚", "Heart-rate and sleep tracking, 7-day battery."),
    ("Bluetooth Speaker", 4900, "🔊", "Waterproof portable speaker."),
    ("Basic Cotton Tee", 1590, "👕", "Unisex crew-neck t-shirt."),
    ("Denim Jacket", 6900, "🧥", "Classic fit washed denim."),
    ("Slim Fit Jeans", 4900, "👖", "Stretch denim, mid rise."),
    ("Summer Dress", 3900, "👗", "Light floral midi dress."),
    ("Running Shoes", 8900, "👟", "Breathable mesh trainers."),
    ("Canvas Sneakers", 4500, "👟", "Low-top everyday sneakers."),
    ("Baseball Cap", 1290, "🧢", "Adjustable cotton cap."),
    ("Backpack 20L", 5900, "🎒", "Water-resistant laptop backpack."),
    ("Sunglasses", 2500, "🕶️", "UV400 polarised lenses."),
    ("Stainless Water Bottle", 2200, "🧴", "750 ml insulated bottle."),
    ("LED Desk Lamp", 3200, "💡", "Dimmable lamp with USB port."),
    ("Yoga Mat", 2800, "🧘", "6 mm non-slip mat."),
    ("Skincare Set", 4200, "🧴", "Cleanser, toner and moisturiser trio."),
    ("Ceramic Mug Set", 1800, "☕", "Set of four 350 ml mugs."),
    ("Board Game", 3600, "🎲", "Family strategy game for 2-5 players."),
    ("Notebook Pack", 1200, "📓", "Three A5 dotted notebooks."),
]
NORMAL_SKUS = [f"SKU-{i:02d}" for i in range(1, len(PRODUCTS) + 1)]


def build_items() -> list[dict]:
    """Return every DynamoDB item (product META + STOCK) to write; pure, no AWS."""
    rows = [(sku, *p, NORMAL_STOCK) for sku, p in zip(NORMAL_SKUS, PRODUCTS)]
    rows.append(
        (LIMITED_SKU, "Limited Edition Sneakers", 19900, "👟", "Flash-sale drop, 50 pairs only.", LIMITED_STOCK)
    )
    items: list[dict] = []
    for sku, name, price, emoji, desc, stock in rows:
        items.append(
            {
                **keys.product_key(sku),
                "name": name,
                "price": price,
                "currency": "SGD",
                "description": desc,
                "emoji": emoji,
                "GSI1PK": keys.CATALOG_GSI1PK,
                "GSI1SK": sku,
            }
        )
        items.append({**keys.stock_key(sku), "available": stock, "initial": stock})
    return items


def seed(table) -> int:
    items = build_items()
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
    return len(items)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", default=keys.TABLE_NAME)
    ap.add_argument("--region", default="ap-southeast-1")
    ap.add_argument("--dry-run", action="store_true", help="print the item count and exit")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"would write {len(build_items())} items to {args.table}")
        return 0
    import boto3

    n = seed(boto3.resource("dynamodb", region_name=args.region).Table(args.table))
    print(f"seeded {n} items into {args.table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
