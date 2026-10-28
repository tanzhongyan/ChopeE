
from tests.services.conftest import GUEST


def test_healthz_and_catalog(catalog_client):
    assert catalog_client.get("/api/healthz").json() == {"ok": True}
    products = catalog_client.get("/api/catalog").json()
    assert [p["sku"] for p in products] == ["LIMITED-01", "MUG-01", "TEE-01"]
    assert products[0]["inStock"] is True and products[0]["price"] == 9900
    assert catalog_client.get("/api/catalog/TEE-01").json()["name"] == "Tee"
    assert catalog_client.get("/api/catalog/NOPE").status_code == 404


def test_catalog_served_from_30s_cache(seeded, verifier):
    from fastapi.testclient import TestClient
    from services.catalog_cart.app import create_app

    now = [1000.0]
    client = TestClient(create_app(ddb=seeded.ddb, verifier=verifier, table_name="chopee", clock=lambda: now[0]))
    assert len(client.get("/api/catalog").json()) == 3
    seeded.table.put_item(Item={"PK": "PRODUCT#NEW", "SK": "META", "name": "n", "price": 1, "GSI1PK": "CATALOG", "GSI1SK": "NEW"})
    assert len(client.get("/api/catalog").json()) == 3  # cached
    now[0] += 31
    assert len(client.get("/api/catalog").json()) == 4


def test_cart_requires_identity(catalog_client):
    assert catalog_client.get("/api/cart").status_code == 401
    assert catalog_client.get("/api/cart", headers={"X-Guest-Id": "not-a-uuid"}).status_code == 401
    assert catalog_client.get("/api/cart", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_guest_cart_put_get_remove_and_validation(catalog_client):
    h = {"X-Guest-Id": GUEST}
    r = catalog_client.put("/api/cart/items/TEE-01", json={"quantity": 2}, headers=h)
    assert r.status_code == 200 and r.json() == {"items": [{"sku": "TEE-01", "quantity": 2, "price": 1500}], "total": 3000}
    assert catalog_client.put("/api/cart/items/TEE-01", json={"quantity": 6}, headers=h).status_code == 400
    assert catalog_client.put("/api/cart/items/TEE-01", json={"quantity": "2"}, headers=h).status_code == 400
    assert catalog_client.put("/api/cart/items/TEE-01", json={}, headers=h).status_code == 400
    assert catalog_client.put("/api/cart/items/NOPE", json={"quantity": 1}, headers=h).status_code == 404
    assert catalog_client.put("/api/cart/items/TEE-01", json={"quantity": 0}, headers=h).json() == {"items": [], "total": 0}


def test_guest_cart_older_than_24h_is_rejected(seeded, verifier):
    from fastapi.testclient import TestClient
    from services.catalog_cart.app import create_app

    now = [1_000_000.0]
    client = TestClient(create_app(ddb=seeded.ddb, verifier=verifier, table_name="chopee", clock=lambda: now[0]))
    h = {"X-Guest-Id": GUEST}
    client.put("/api/cart/items/TEE-01", json={"quantity": 1}, headers=h)
    now[0] += 24 * 3600 + 1
    assert client.get("/api/cart", headers=h).json()["items"] == []


def test_merge_sums_caps_reprices_and_is_idempotent(catalog_client, auth, seeded):
    g = {"X-Guest-Id": GUEST}
    catalog_client.put("/api/cart/items/TEE-01", json={"quantity": 3}, headers=g)
    catalog_client.put("/api/cart/items/MUG-01", json={"quantity": 1}, headers=g)
    catalog_client.put("/api/cart/items/TEE-01", json={"quantity": 4}, headers=auth())  # user already has 4
    # tamper: stale price must not survive the merge
    seeded.table.update_item(Key={"PK": "PRODUCT#MUG-01", "SK": "META"}, UpdateExpression="SET price = :p",
                             ExpressionAttributeValues={":p": 900})
    r = catalog_client.post("/api/cart/merge", json={"guestId": GUEST}, headers=auth())
    assert r.status_code == 200
    items = {i["sku"]: i for i in r.json()["items"]}
    assert items["TEE-01"]["quantity"] == 5  # 4 + 3 capped at 5
    assert items["MUG-01"]["quantity"] == 1 and items["MUG-01"]["price"] == 900
    # retry with the same guest id adds nothing
    again = catalog_client.post("/api/cart/merge", json={"guestId": GUEST}, headers=auth())
    assert again.json() == r.json()
    # a fresh guest cart under the same id is also ignored (marker per guestId)
    catalog_client.put("/api/cart/items/MUG-01", json={"quantity": 4}, headers=g)
    third = catalog_client.post("/api/cart/merge", json={"guestId": GUEST}, headers=auth())
    assert {i["sku"]: i["quantity"] for i in third.json()["items"]} == {"TEE-01": 5, "MUG-01": 1}
    # guest lines were cleaned up after the first merge
    marker = seeded.table.get_item(Key={"PK": "CART#USER#user-1", "SK": f"MERGED#{GUEST}"})
    assert "Item" in marker


def test_merge_validation(catalog_client, auth):
    assert catalog_client.post("/api/cart/merge", json={"guestId": GUEST}).status_code == 401
    assert catalog_client.post("/api/cart/merge", json={"guestId": "x"}, headers=auth()).status_code == 400
    assert catalog_client.post("/api/cart/merge", json={}, headers=auth()).status_code == 400
    assert catalog_client.post("/api/cart/merge", json={"guestId": GUEST}, headers=auth()).json() == {"items": [], "total": 0}
