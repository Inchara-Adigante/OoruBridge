"""Payment webhooks: signed, idempotent, and strict about amounts."""
import json

import psycopg
import pytest

from conftest import TEST_URL
from oorubridge.payments import SIGNATURE_HEADER, sign


@pytest.fixture(scope="module")
def customer(client):
    return client.post("/customers", json={"email": "pay@example.com", "full_name": "Priya Nair",
                                           "destination": "SJC", "zip": "95134"}).json()["customer_id"]


def new_order(client, customer, product_id=4):
    return client.post("/orders", json={"customer_id": customer,
                                        "items": [{"product_id": product_id, "quantity": 1}]}).json()


def webhook(client, payload, secret=None, signature=None):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json", SIGNATURE_HEADER: signature or sign(body, secret)}
    return client.post("/webhooks/payments", content=body, headers=headers)


def event(order, ref, status="succeeded", amount=None):
    return {"provider_ref": ref, "order_id": order["order_id"], "status": status,
            "amount_usd": amount if amount is not None else order["total_usd"]}


def test_successful_payment_marks_the_order_paid(client, customer):
    o = new_order(client, customer)
    r = webhook(client, event(o, "pi_1001"))
    assert r.json() == {"result": "paid"}
    after = client.get(f"/orders/{o['order_id']}").json()
    assert after["status"] == "paid"
    assert [e["status"] for e in after["timeline"]] == ["placed", "paid"]


def test_the_same_event_twice_counts_once(client, customer):
    o = new_order(client, customer)
    assert webhook(client, event(o, "pi_2001")).json() == {"result": "paid"}
    assert webhook(client, event(o, "pi_2001")).json() == {"result": "duplicate"}
    assert len(client.get(f"/orders/{o['order_id']}").json()["timeline"]) == 2


def test_forged_or_unsigned_requests_are_rejected(client, customer):
    o = new_order(client, customer)
    assert webhook(client, event(o, "pi_3001"), secret="attacker-guess").status_code == 401
    assert webhook(client, event(o, "pi_3001"), signature="sha256=").status_code == 401
    assert client.get(f"/orders/{o['order_id']}").json()["status"] == "placed"


def test_wrong_amount_is_refused(client, customer):
    o = new_order(client, customer)
    r = webhook(client, event(o, "pi_4001", amount="1.00"))
    assert r.status_code == 422 and "does not match the order total" in r.json()["detail"]
    assert client.get(f"/orders/{o['order_id']}").json()["status"] == "placed"


def test_failed_payment_leaves_the_order_unpaid(client, customer):
    o = new_order(client, customer)
    assert webhook(client, event(o, "pi_5001", status="failed")).json() == {"result": "failed"}
    assert client.get(f"/orders/{o['order_id']}").json()["status"] == "placed"
    assert webhook(client, event(o, "pi_5002")).json() == {"result": "paid"}      # customer retries the card


def test_money_for_a_cancelled_order_is_flagged_for_refund(client, customer):
    o = new_order(client, customer)
    client.post(f"/orders/{o['order_id']}/cancel")
    assert webhook(client, event(o, "pi_6001")).json() == {"result": "needs_refund"}
    assert client.get(f"/orders/{o['order_id']}").json()["status"] == "cancelled"


def test_bad_payloads(client, customer):
    o = new_order(client, customer)
    assert webhook(client, {**event(o, "pi_7001"), "status": "maybe"}).status_code == 422
    assert webhook(client, {**event(o, "pi_7002"), "order_id": 9999}).status_code == 404


def test_cancelling_a_paid_order_flags_the_payment_for_refund(client, customer):
    o = new_order(client, customer)
    webhook(client, event(o, "pi_8001"))
    assert client.post(f"/orders/{o['order_id']}/cancel").json()["status"] == "cancelled"
    with psycopg.connect(TEST_URL) as con:
        assert con.execute("SELECT needs_refund FROM shop.payments WHERE provider_ref = 'pi_8001'").fetchone()[0]
