"""Tracking: Bengaluru shop -> air cargo -> US customs -> doorstep, one step at a time."""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from conftest import TEST_URL


@pytest.fixture(scope="module")
def customer(client):
    return client.post("/customers", json={"email": "track@example.com", "full_name": "Anil Kumar",
                                           "destination": "DEN", "zip": "80014"}).json()["customer_id"]


def new_order(client, customer):
    return client.post("/orders", json={"customer_id": customer,
                                        "items": [{"product_id": 10, "quantity": 1}]}).json()["order_id"]


def step(client, order_id, status, location="Bengaluru"):
    return client.post(f"/orders/{order_id}/events", json={"status": status, "location": location})


def test_full_journey_to_denver(client, customer):
    oid = new_order(client, customer)
    t = client.get(f"/orders/{oid}/tracking").json()
    assert (t["progress_pct"], t["next_step"]) == (0, "paid") and "Denver" in t["estimated_delivery"]["note"]

    for status, where in [("paid", "Payment confirmed"), ("packed", "Gandhi Bazaar Coffee Works"),
                          ("shipped_from_blr", "Kempegowda airport cargo"), ("in_us_customs", "Chicago ORD"),
                          ("out_for_delivery", "Denver"), ("delivered", "Front door")]:
        t = step(client, oid, status, where).json()
        if status == "shipped_from_blr":
            today = datetime.now(timezone.utc).date()
            assert t["estimated_delivery"] == {"earliest": str(today + timedelta(days=7)),
                                               "latest": str(today + timedelta(days=10))}
    assert (t["status"], t["progress_pct"], t["next_step"]) == ("delivered", 100, None)
    assert t["estimated_delivery"] == {"delivered_on": str(datetime.now(timezone.utc).date())}
    assert [e["location"] for e in t["timeline"]][-1] == "Front door"
    assert len(t["timeline"]) == 7


def test_steps_cannot_be_skipped_or_reversed(client, customer):
    oid = new_order(client, customer)
    r = step(client, oid, "shipped_from_blr")
    assert r.status_code == 409 and "cannot go from placed to shipped_from_blr" in r.json()["detail"]
    step(client, oid, "paid")
    step(client, oid, "packed")
    assert step(client, oid, "paid").status_code == 409
    assert client.post(f"/orders/{oid}/cancel").status_code == 409           # too late once packed


def test_the_database_enforces_the_rules_too(client, customer):
    oid = new_order(client, customer)
    with psycopg.connect(TEST_URL) as con, pytest.raises(psycopg.errors.CheckViolation, match="cannot go from"):
        con.execute("UPDATE shop.orders SET status = 'delivered' WHERE order_id = %s", (oid,))


def test_cancelled_orders_stop_moving(client, customer):
    oid = new_order(client, customer)
    client.post(f"/orders/{oid}/cancel")
    t = client.get(f"/orders/{oid}/tracking").json()
    assert (t["progress_pct"], t["estimated_delivery"]) == (None, None)
    assert step(client, oid, "paid").status_code == 409


def test_bad_requests(client, customer):
    assert step(client, new_order(client, customer), "teleported").status_code == 422
    assert step(client, 9999, "paid").status_code == 404
    assert client.get("/orders/9999/tracking").status_code == 404
