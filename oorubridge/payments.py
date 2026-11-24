"""
Payment webhooks. The payment provider calls POST /webhooks/payments when a card payment succeeds or fails.

Three things can go wrong with webhooks, and each is handled:
    forged requests   every request is signed with HMAC-SHA256 using a shared secret; unsigned or badly
                      signed requests are rejected (401)
    duplicates        providers retry; provider_ref is unique, so a repeated event is acknowledged but
                      changes nothing
    wrong money       a payment must match the order total exactly; money for a cancelled or already-paid
                      order is recorded and flagged for refund instead of being lost
"""
import hashlib
import hmac
import os

import psycopg

from oorubridge.db import NotFound

WEBHOOK_SECRET = os.getenv("OORU_WEBHOOK_SECRET", "dev-only-secret")
SIGNATURE_HEADER = "X-OoruBridge-Signature"


def sign(body: bytes, secret: str | None = None) -> str:
    return "sha256=" + hmac.new((secret or WEBHOOK_SECRET).encode(), body, hashlib.sha256).hexdigest()


def signature_ok(body: bytes, header: str | None) -> bool:
    return header is not None and hmac.compare_digest(sign(body), header)   # constant-time comparison


class AmountMismatch(ValueError):
    pass


def record_payment(con, order_id: int, provider_ref: str, amount_usd, status: str) -> str:
    """Store one provider event; returns what happened: paid, failed, duplicate or needs_refund."""
    with con.transaction():
        order = con.execute("SELECT status, total_usd FROM shop.orders WHERE order_id = %s FOR UPDATE",
                            (order_id,)).fetchone()
        if order is None:
            raise NotFound("order not found")
        if con.execute("SELECT 1 FROM shop.payments WHERE provider_ref = %s", (provider_ref,)).fetchone():
            return "duplicate"
        if status == "succeeded" and amount_usd != order["total_usd"]:
            raise AmountMismatch(f"payment of {amount_usd} does not match the order total {order['total_usd']}")
        refund = status == "succeeded" and order["status"] != "placed"
        try:
            con.execute("""INSERT INTO shop.payments (order_id, provider_ref, amount_usd, status, needs_refund)
                           VALUES (%s, %s, %s, %s, %s)""", (order_id, provider_ref, amount_usd, status, refund))
        except psycopg.errors.UniqueViolation:
            return "duplicate"                 # the same event raced in on another connection
        if status != "succeeded":
            return "failed"
        if refund:
            return "needs_refund"
        con.execute("UPDATE shop.orders SET status = 'paid' WHERE order_id = %s", (order_id,))
        con.execute("INSERT INTO shop.shipment_events (order_id, status, location) VALUES (%s, 'paid', %s)",
                    (order_id, "Payment confirmed"))
        return "paid"
