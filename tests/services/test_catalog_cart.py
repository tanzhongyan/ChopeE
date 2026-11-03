
import threading
import time

from tests.services.conftest import GUEST


def test_healthz_and_catalog(catalog_client):
    assert catalog_client.get("/api/healthz").json() == {"ok": True}
    products = catalog_client.get("/api/catalog").json()
    assert [p["sku"] for p in products] == ["LIMITED-01", "MUG-01", "TEE-01"]
    assert products[0]["inStock"] is True and products[0]["price"] == 9900
    assert [p["available"] for p in products] == [1, 50, 50]
    assert all(isinstance(p["available"], int) for p in products)
    assert catalog_client.get("/api/catalog/TEE-01").json()["name"] == "Tee"
    assert catalog_client.get("/api/catalog/TEE-01").json()["available"] == 50
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


def test_merge_sums_caps_reprices_and_is_idempotent(seeded, verifier, auth):
    from fastapi.testclient import TestClient
    from services.catalog_cart.app import create_app

    now = [1_000_000.0]
    catalog_client = TestClient(create_app(ddb=seeded.ddb, verifier=verifier, table_name="chopee", clock=lambda: now[0]))
    g = {"X-Guest-Id": GUEST}
    catalog_client.put("/api/cart/items/TEE-01", json={"quantity": 3}, headers=g)
    catalog_client.put("/api/cart/items/MUG-01", json={"quantity": 1}, headers=g)
    catalog_client.put("/api/cart/items/TEE-01", json={"quantity": 4}, headers=auth())  # user already has 4
    # tamper: stale price must not survive the merge
    seeded.table.update_item(Key={"PK": "PRODUCT#MUG-01", "SK": "META"}, UpdateExpression="SET price = :p",
                             ExpressionAttributeValues={":p": 900})
    now[0] += 31  # price comes from the 30 s catalog cache, so let it expire
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


# ---- API-2: JWT verification off the event loop ------------------------------------------------
class SlowVerifier:
    def __init__(self, delay=0.3, fail_warm=False):
        self.delay, self.fail_warm, self.warmed = delay, fail_warm, 0

    def _keys(self, kid=None):
        self.warmed += 1
        if self.fail_warm:
            raise RuntimeError("jwks down")
        return {}

    def subject(self, auth):
        time.sleep(self.delay)
        return "user-1"


def test_concurrent_puts_do_not_block_event_loop(seeded):
    import asyncio

    import httpx
    from services.catalog_cart.app import create_app

    app = create_app(ddb=seeded.ddb, verifier=SlowVerifier(0.3), table_name="chopee")

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            t0 = time.perf_counter()
            rs = await asyncio.gather(*[
                c.put("/api/cart/items/TEE-01", json={"quantity": 1}, headers={"Authorization": "Bearer x"})
                for _ in range(2)
            ])
            return rs, time.perf_counter() - t0

    rs, elapsed = asyncio.run(run())
    assert [r.status_code for r in rs] == [200, 200]
    assert elapsed < 0.55  # serial would be >= 0.6


def test_jwks_warmup_at_startup_and_tolerates_failure(seeded):
    from fastapi.testclient import TestClient
    from services.catalog_cart.app import create_app

    ok = SlowVerifier()
    with TestClient(create_app(ddb=seeded.ddb, verifier=ok, table_name="chopee")) as c:
        assert c.get("/api/healthz").status_code == 200
    assert ok.warmed == 1
    bad = SlowVerifier(fail_warm=True)
    with TestClient(create_app(ddb=seeded.ddb, verifier=bad, table_name="chopee")) as c:  # must not crash
        assert c.get("/api/healthz").status_code == 200
    assert bad.warmed == 1


# ---- API-8: no per-line GetItem, single-flight refresh ----------------------------------------
class SpyDdb:
    def __init__(self, inner):
        self._inner, self.calls = inner, {}
        self._lock = threading.Lock()

    def __getattr__(self, name):
        fn = getattr(self._inner, name)
        if not callable(fn):
            return fn

        def wrapper(*a, **kw):
            with self._lock:
                self.calls[name] = self.calls.get(name, 0) + 1
            return fn(*a, **kw)

        return wrapper


def test_cart_get_and_merge_issue_no_get_item(seeded, verifier, auth):
    from fastapi.testclient import TestClient
    from services.catalog_cart.app import create_app

    spy = SpyDdb(seeded.ddb)
    c = TestClient(create_app(ddb=spy, verifier=verifier, table_name="chopee"))
    g = {"X-Guest-Id": GUEST}
    c.get("/api/catalog")  # warm the cache
    for sku in ("TEE-01", "MUG-01", "LIMITED-01"):
        assert c.put(f"/api/cart/items/{sku}", json={"quantity": 1}, headers=g).status_code == 200
    spy.calls.clear()
    body = c.get("/api/cart", headers=g).json()
    assert len(body["items"]) == 3 and body["total"] == 1500 + 800 + 9900
    assert spy.calls.get("get_item", 0) == 0
    r = c.post("/api/cart/merge", json={"guestId": GUEST}, headers=auth())
    assert r.status_code == 200 and len(r.json()["items"]) == 3
    assert spy.calls.get("get_item", 0) == 0


def test_cold_catalog_concurrent_requests_query_gsi_once(seeded, verifier):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient
    from services.catalog_cart.app import create_app

    spy = SpyDdb(seeded.ddb)
    real_query = spy._inner.query

    def slow_query(**kw):  # widen the race window
        time.sleep(0.2)
        return real_query(**kw)

    spy._inner = type("W", (), {"__getattr__": lambda _s, n: getattr(seeded.ddb, n), "query": staticmethod(slow_query)})()
    c = TestClient(create_app(ddb=spy, verifier=verifier, table_name="chopee"))
    with ThreadPoolExecutor(8) as ex:
        rs = list(ex.map(lambda _: c.get("/api/catalog"), range(8)))
    assert all(r.status_code == 200 and len(r.json()) == 3 for r in rs)
    assert spy.calls["query"] == 1
