"""API tests against a real PostgreSQL test database built from the migrations and sample catalog."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402
from oorubridge import db  # noqa: E402
from oorubridge.api import app  # noqa: E402

TEST_URL = os.getenv("DATABASE_URL_TEST", "postgresql:///oorubridge_test")


@pytest.fixture(scope="module")
def client():
    migrate.reset_database(TEST_URL)
    migrate.migrate(TEST_URL)
    migrate.seed(TEST_URL)
    db.DATABASE_URL = TEST_URL
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_destinations_are_san_jose_and_denver(client):
    assert {d["city"] for d in client.get("/destinations").json()} == {"San Jose", "Denver"}


def test_browse_and_filter_products(client):
    every = client.get("/products").json()
    assert len(every) == 12
    spices = client.get("/products", params={"category": "spices"}).json()
    assert {p["area"] for p in spices} == {"Basavanagudi"}
    assert [p["name"] for p in client.get("/products", params={"q": "coffee"}).json()] == \
        ["Filter Coffee 80:20 (500 g)", "Steel Coffee Filter Set"]
    assert all(float(p["price_inr"]) <= 300 for p in client.get("/products", params={"max_price_inr": 300}).json())


def test_quote_to_denver(client):
    r = client.post("/quotes", json={"destination": "den", "items": [{"product_id": 1, "quantity": 2},
                                                                    {"product_id": 9, "quantity": 1}]})
    assert r.status_code == 200
    q = r.json()
    assert q["destination"] == "DEN" and q["delivery_days"] == {"min": 7, "max": 10}
    parts = sum(float(q[k]) for k in ("subtotal_usd", "shipping_usd", "duty_usd", "service_fee_usd"))
    assert float(q["total_usd"]) == pytest.approx(parts)
    assert [line["name"] for line in q["lines"]] == ["Mysore Pak (500 g)", "Filter Coffee 80:20 (500 g)"]


def test_same_product_twice_is_merged(client):
    q = client.post("/quotes", json={"destination": "SJC", "items": [{"product_id": 4, "quantity": 1},
                                                                    {"product_id": 4, "quantity": 2}]}).json()
    assert [(line["product_id"], line["quantity"]) for line in q["lines"]] == [(4, 3)]


def test_quote_errors(client):
    assert client.post("/quotes", json={"destination": "NYC", "items": [{"product_id": 1, "quantity": 1}]}).status_code == 400
    assert client.post("/quotes", json={"destination": "SJC", "items": [{"product_id": 999, "quantity": 1}]}).status_code == 404
    assert client.post("/quotes", json={"destination": "SJC", "items": [{"product_id": 1, "quantity": 0}]}).status_code == 422
    too_heavy = client.post("/quotes", json={"destination": "SJC", "items": [{"product_id": 5, "quantity": 20},
                                                                             {"product_id": 1, "quantity": 20}]})
    assert too_heavy.status_code == 422 and "20 kg" in too_heavy.json()["detail"]
