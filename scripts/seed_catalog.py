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
    ("Kaya Toast Kit", 650, "🍞", "Charcoal-grilled bread with coconut egg jam."),
    ("Chicken Rice Set", 890, "🍗", "Poached chicken, fragrant rice, chilli and ginger."),
    ("Laksa Paste", 520, "🍜", "Spicy coconut curry base for four bowls."),
    ("Teh Tarik Mix", 780, "🧋", "Instant pulled milk tea sachets."),
    ("Pandan Chiffon Cake", 1200, "🍰", "Light pandan sponge, whole cake."),
    ("Bak Kwa Pack", 2800, "🥓", "Sweet grilled pork jerky, 250 g."),
    ("Curry Puff Box", 980, "🥟", "Six frozen curry puffs."),
    ("Ice Kachang Syrup", 450, "🍧", "Rose and palm sugar syrups."),
    ("Satay Skewers", 1500, "🍢", "Twenty skewers with peanut sauce."),
    ("Hainan Coffee", 850, "☕", "Kopi-O roast, ground, 200 g."),
    ("Chilli Crab Sauce", 750, "🦀", "Sweet-spicy sauce, ready to heat."),
    ("Kueh Lapis", 1100, "🍰", "Nine-layer steamed cake."),
    ("Orh Nee", 900, "🍮", "Yam paste dessert."),
    ("Roti Prata Pack", 700, "🫓", "Ten frozen prata with curry dip."),
    ("Mee Siam Kit", 600, "🍝", "Rice vermicelli in tangy gravy."),
    ("Soy Milk Bottle", 300, "🥛", "Fresh-style soy milk, 1 L."),
    ("Ginger Tea Cubes", 540, "🫚", "Instant ginger and brown sugar."),
    ("Sambal Belacan", 480, "🌶️", "Fried chilli shrimp paste jar."),
    ("Ondeh Ondeh Box", 800, "🟢", "Pandan rice cakes with palm sugar."),
    ("Prawn Crackers", 400, "🍤", "Keropok, family size."),
    ("Barley Drink", 350, "🥤", "Lemon barley, 1 L."),
    ("Nasi Lemak Set", 950, "🍚", "Coconut rice, anchovies, peanuts, sambal."),
    ("Egg Tart Box", 1050, "🥧", "Six flaky egg tarts."),
    ("Milo Dinosaur Pack", 680, "🥛", "Chocolate malt drink mix."),
]
NORMAL_SKUS = [f"SKU-{i:02d}" for i in range(1, len(PRODUCTS) + 1)]


def build_items() -> list[dict]:
    """Return every DynamoDB item (product META + STOCK) to write; pure, no AWS."""
    rows = [(sku, *p, NORMAL_STOCK) for sku, p in zip(NORMAL_SKUS, PRODUCTS)]
    rows.append(
        (LIMITED_SKU, "Limited Edition Durian Cake", 3900, "🎂", "Flash-sale item, 50 only.", LIMITED_STOCK)
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
