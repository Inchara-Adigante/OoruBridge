"""Database access: connection settings and the queries the API needs."""
import os
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from oorubridge.pricing import Destination, Product, quote

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql:///oorubridge")
# Sample exchange rate for development; production would refresh it from a rates API.
FX_INR_PER_USD = Decimal(os.getenv("OORU_FX_INR_PER_USD", "84.00"))


def connect() -> psycopg.Connection:
    # autocommit: each statement commits on its own; multi-step work uses an explicit con.transaction()
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


def list_products(con, category=None, area=None, search=None, max_price_inr=None) -> list[dict]:
    return con.execute("""
        SELECT p.product_id, p.name, p.category, p.description, p.price_inr, p.weight_g, p.shelf_life_days,
               p.stock, s.name AS seller, s.area, s.verified
          FROM shop.products p JOIN shop.sellers s USING (seller_id)
         WHERE p.active
           AND (%(category)s::text IS NULL OR p.category = %(category)s)
           AND (%(area)s::text IS NULL OR s.area ILIKE %(area)s)
           AND (%(search)s::text IS NULL OR p.name ILIKE '%%' || %(search)s || '%%'
                                         OR p.description ILIKE '%%' || %(search)s || '%%')
           AND (%(max_price)s::numeric IS NULL OR p.price_inr <= %(max_price)s)
         ORDER BY s.area, p.name""",
        dict(category=category, area=area, search=search, max_price=max_price_inr)).fetchall()


def products_by_id(con, ids: list[int]) -> dict[int, Product]:
    rows = con.execute("""SELECT product_id, name, category, price_inr, weight_g, shelf_life_days
                            FROM shop.products WHERE active AND product_id = ANY(%s)""", (ids,)).fetchall()
    return {r["product_id"]: Product(**r) for r in rows}


def destinations(con) -> dict[str, Destination]:
    rows = con.execute("SELECT code, city, min_days, max_days, surcharge_pct FROM shop.destinations").fetchall()
    return {r["code"]: Destination(**r) for r in rows}


def rate_card(con) -> dict[int, Decimal]:
    return {r["max_weight_g"]: r["price_usd"] for r in con.execute("SELECT * FROM shop.shipping_rates")}


def duty_rates(con) -> dict[str, Decimal]:
    return {r["category"]: r["duty_rate"] for r in con.execute("SELECT category, duty_rate FROM shop.duty_categories")}


def create_customer(con, email: str, full_name: str, destination: str, zip_code: str) -> dict:
    return con.execute("""
        INSERT INTO shop.customers (email, full_name, destination, zip) VALUES (%s, %s, %s, %s)
        RETURNING customer_id, email, full_name, destination, zip, created_at""",
        (email, full_name, destination, zip_code)).fetchone()


def get_customer(con, customer_id: int) -> dict | None:
    return con.execute("SELECT customer_id, email, full_name, destination, zip, created_at "
                       "FROM shop.customers WHERE customer_id = %s", (customer_id,)).fetchone()


class NotFound(LookupError):
    pass


class OutOfStock(Exception):
    def __init__(self, short: list[dict]):
        super().__init__(short)
        self.short = short


def find_order_by_key(con, customer_id: int, key: str | None) -> int | None:
    if key is None:
        return None
    row = con.execute("SELECT order_id FROM shop.orders WHERE customer_id = %s AND idempotency_key = %s",
                      (customer_id, key)).fetchone()
    return row["order_id"] if row else None


def place_order(con, customer_id: int, qty: dict[int, int], idempotency_key: str | None = None) -> tuple[int, bool]:
    """
    Checkout in one transaction. Returns (order_id, created).

    Product rows are locked FOR UPDATE in id order: two shoppers buying the last jar of sambar powder queue
    on that row, the second one sees stock 0 and gets OutOfStock, and nobody can deadlock. Prices and the
    exchange rate are copied into the order, so later price or rate changes never alter an order.
    """
    existing = find_order_by_key(con, customer_id, idempotency_key)
    if existing:
        return existing, False
    try:
        with con.transaction():
            customer = get_customer(con, customer_id)
            if customer is None:
                raise NotFound("customer not found")
            rows = con.execute("""
                SELECT product_id, name, category, price_inr, weight_g, shelf_life_days, stock
                  FROM shop.products WHERE active AND product_id = ANY(%s)
                 ORDER BY product_id FOR UPDATE""", (list(qty),)).fetchall()
            found = {r["product_id"]: r for r in rows}
            missing = sorted(set(qty) - set(found))
            if missing:
                raise NotFound(f"unknown product(s): {missing}")
            short = [dict(product_id=pid, name=found[pid]["name"], requested=n, available=found[pid]["stock"])
                     for pid, n in sorted(qty.items()) if found[pid]["stock"] < n]
            if short:
                raise OutOfStock(short)

            dest = destinations(con)[customer["destination"]]
            products = {pid: Product(**{k: v for k, v in r.items() if k != "stock"}) for pid, r in found.items()}
            q = quote([(products[pid], n) for pid, n in sorted(qty.items())], dest, FX_INR_PER_USD,
                      rate_card(con), duty_rates(con))
            order_id = con.execute("""
                INSERT INTO shop.orders (customer_id, destination, fx_inr_per_usd, subtotal_usd, shipping_usd,
                                         duty_usd, service_fee_usd, total_usd, idempotency_key)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING order_id""",
                (customer_id, dest.code, q.fx_inr_per_usd, q.subtotal_usd, q.shipping_usd, q.duty_usd,
                 q.service_fee_usd, q.total_usd, idempotency_key)).fetchone()["order_id"]
            for pid, n in sorted(qty.items()):
                con.execute("INSERT INTO shop.order_items (order_id, product_id, quantity, price_inr) "
                            "VALUES (%s, %s, %s, %s)", (order_id, pid, n, found[pid]["price_inr"]))
                con.execute("UPDATE shop.products SET stock = stock - %s WHERE product_id = %s", (n, pid))
            con.execute("INSERT INTO shop.shipment_events (order_id, status, location) VALUES (%s, 'placed', %s)",
                        (order_id, "OoruBridge checkout"))
            return order_id, True
    except psycopg.errors.UniqueViolation:
        # The same idempotency key arrived twice at the same moment: the other request won; return its order.
        return find_order_by_key(con, customer_id, idempotency_key), False


def get_order(con, order_id: int) -> dict | None:
    order = con.execute("""
        SELECT o.order_id, o.customer_id, o.destination, o.status, o.fx_inr_per_usd, o.subtotal_usd,
               o.shipping_usd, o.duty_usd, o.service_fee_usd, o.total_usd, o.created_at
          FROM shop.orders o WHERE o.order_id = %s""", (order_id,)).fetchone()
    if order is None:
        return None
    order["items"] = con.execute("""
        SELECT oi.product_id, p.name, s.name AS seller, oi.quantity, oi.price_inr
          FROM shop.order_items oi JOIN shop.products p USING (product_id) JOIN shop.sellers s USING (seller_id)
         WHERE oi.order_id = %s ORDER BY oi.product_id""", (order_id,)).fetchall()
    order["timeline"] = con.execute("""
        SELECT status, location, happened_at FROM shop.shipment_events
         WHERE order_id = %s ORDER BY happened_at, status""", (order_id,)).fetchall()
    return order


class CannotCancel(Exception):
    pass


def cancel_order(con, order_id: int) -> None:
    """Cancel before the parcel leaves the shop: stock goes back and the timeline records it."""
    with con.transaction():
        row = con.execute("SELECT status FROM shop.orders WHERE order_id = %s FOR UPDATE", (order_id,)).fetchone()
        if row is None:
            raise NotFound("order not found")
        if row["status"] not in ("placed", "paid"):
            raise CannotCancel(f"order is {row['status']}; it can only be cancelled before it is packed")
        items = con.execute("SELECT product_id, quantity FROM shop.order_items WHERE order_id = %s "
                            "ORDER BY product_id", (order_id,)).fetchall()
        for it in items:                                   # same lock order as checkout: no deadlocks
            con.execute("UPDATE shop.products SET stock = stock + %s WHERE product_id = %s",
                        (it["quantity"], it["product_id"]))
        con.execute("UPDATE shop.orders SET status = 'cancelled' WHERE order_id = %s", (order_id,))
        con.execute("INSERT INTO shop.shipment_events (order_id, status, location) VALUES (%s, 'cancelled', %s)",
                    (order_id, "Cancelled by customer"))


def customer_orders(con, customer_id: int) -> list[dict]:
    return con.execute("""
        SELECT o.order_id, o.status, o.destination, o.total_usd, o.created_at,
               sum(oi.quantity)::int AS items
          FROM shop.orders o JOIN shop.order_items oi USING (order_id)
         WHERE o.customer_id = %s
         GROUP BY o.order_id ORDER BY o.created_at DESC, o.order_id DESC""", (customer_id,)).fetchall()
