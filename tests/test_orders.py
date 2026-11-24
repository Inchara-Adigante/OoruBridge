"""Checkout: stock never oversold, prices and exchange rate frozen at order time, safe retries."""
import threading
from decimal import Decimal

import psycopg
import pytest

from conftest import TEST_URL
from oorubridge import db


@pytest.fixture(scope="module")
def customer(client):
    return client.post("/customers", json={"email": "meera@example.com", "full_name": "Meera Iyer",
                                           "destination": "DEN", "zip": "80202"}).json()["customer_id"]


def stock(product_id):
    with psycopg.connect(TEST_URL) as con:
        return con.execute("SELECT stock FROM shop.products WHERE product_id = %s", (product_id,)).fetchone()[0]


def set_stock(product_id, n):
    with psycopg.connect(TEST_URL) as con:
        con.execute("UPDATE shop.products SET stock = %s WHERE product_id = %s", (n, product_id))


def order(client, customer, items, key=None):
    return client.post("/orders", json={"customer_id": customer, "idempotency_key": key,
                                        "items": [{"product_id": p, "quantity": q} for p, q in items]})


def test_order_reserves_stock_and_matches_the_quote(client, customer):
    before = stock(1)
    quote = client.post("/quotes", json={"destination": "DEN", "items": [{"product_id": 1, "quantity": 2}]}).json()
    r = order(client, customer, [(1, 2)])
    assert r.status_code == 201
    o = r.json()
    assert o["status"] == "placed" and o["destination"] == "DEN"          # ships to the customer's city
    assert o["total_usd"] == quote["total_usd"]
    assert [(i["name"], i["quantity"]) for i in o["items"]] == [("Mysore Pak (500 g)", 2)]
    assert [e["status"] for e in o["timeline"]] == ["placed"]
    assert stock(1) == before - 2


def test_exchange_rate_and_prices_are_frozen(client, customer):
    o = order(client, customer, [(9, 1)]).json()
    old_fx, db.FX_INR_PER_USD = db.FX_INR_PER_USD, Decimal("90")
    try:
        with psycopg.connect(TEST_URL) as con:
            con.execute("UPDATE shop.products SET price_inr = price_inr * 2 WHERE product_id = 9")
        again = client.get(f"/orders/{o['order_id']}").json()
        assert again["fx_inr_per_usd"] == o["fx_inr_per_usd"] == "84.0000"
        assert again["items"][0]["price_inr"] == "380.00" and again["total_usd"] == o["total_usd"]
    finally:
        db.FX_INR_PER_USD = old_fx
        with psycopg.connect(TEST_URL) as con:
            con.execute("UPDATE shop.products SET price_inr = price_inr / 2 WHERE product_id = 9")


def test_out_of_stock_changes_nothing(client, customer):
    set_stock(2, 1)
    before_4 = stock(4)
    r = order(client, customer, [(4, 1), (2, 3)])
    assert r.status_code == 409
    assert r.json()["detail"]["items"] == [{"product_id": 2, "name": "Chiroti (12 pieces)", "requested": 3, "available": 1}]
    assert (stock(2), stock(4)) == (1, before_4)


def test_retry_with_the_same_key_returns_the_same_order(client, customer):
    before = stock(5)
    first = order(client, customer, [(5, 1)], key="checkout-7f3a9c")
    retry = order(client, customer, [(5, 1)], key="checkout-7f3a9c")
    assert (first.status_code, retry.status_code) == (201, 200)
    assert first.json()["order_id"] == retry.json()["order_id"]
    assert stock(5) == before - 1


def test_twenty_shoppers_for_five_jars_never_oversell(client, customer):
    set_stock(6, 5)
    barrier, results, lock = threading.Barrier(20), [], threading.Lock()

    def shop():
        with db.connect() as con:
            barrier.wait()
            try:
                db.place_order(con, customer, {6: 1})
                outcome = "ok"
            except db.OutOfStock:
                outcome = "sold out"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=shop) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 5 and results.count("sold out") == 15
    assert stock(6) == 0


def test_unknown_customer_or_product(client, customer):
    assert order(client, 9999, [(1, 1)]).status_code == 404
    assert order(client, customer, [(999, 1)]).status_code == 404
    assert client.get("/orders/9999").status_code == 404
