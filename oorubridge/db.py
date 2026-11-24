"""Database access: connection settings and the queries the API needs."""
import os
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from oorubridge.pricing import Destination, Product

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql:///oorubridge")
# Sample exchange rate for development; production would refresh it from a rates API.
FX_INR_PER_USD = Decimal(os.getenv("OORU_FX_INR_PER_USD", "84.00"))


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


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
