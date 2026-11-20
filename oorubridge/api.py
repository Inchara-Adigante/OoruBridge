"""
OoruBridge API (first slice): browse Bengaluru shops' products and get an all-in price for delivery
to San Jose or Denver.

Run:  uvicorn oorubridge.api:app --reload      then open http://localhost:8000/docs
"""
from collections.abc import Iterator
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from oorubridge import db
from oorubridge.pricing import QuoteError, quote

app = FastAPI(title="OoruBridge", version="0.1.0",
              description="Shop from Bengaluru, delivered to San Jose and Denver.")


def get_con() -> Iterator:
    with db.connect() as con:
        yield con


class CartItem(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=20)


class QuoteRequest(BaseModel):
    destination: str = Field(examples=["SJC"], description="SJC (San Jose) or DEN (Denver)")
    items: list[CartItem] = Field(min_length=1)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/destinations")
def list_destinations(con=Depends(get_con)) -> list[dict]:
    return [d.__dict__ for d in db.destinations(con).values()]


@app.get("/products")
def list_products(category: str | None = None, area: str | None = None,
                  q: str | None = Query(None, description="Search name and description"),
                  max_price_inr: Decimal | None = None, con=Depends(get_con)) -> list[dict]:
    return db.list_products(con, category, area, q, max_price_inr)


@app.post("/quotes")
def create_quote(req: QuoteRequest, con=Depends(get_con)) -> dict:
    dests = db.destinations(con)
    dest = dests.get(req.destination.upper())
    if dest is None:
        raise HTTPException(400, f"we deliver to {', '.join(sorted(dests))}; got {req.destination!r}")
    qty: dict[int, int] = {}
    for item in req.items:                       # the same product twice in a cart counts once
        qty[item.product_id] = qty.get(item.product_id, 0) + item.quantity
    products = db.products_by_id(con, list(qty))
    missing = sorted(set(qty) - set(products))
    if missing:
        raise HTTPException(404, f"unknown product(s): {missing}")
    try:
        q = quote([(products[pid], n) for pid, n in qty.items()], dest, db.FX_INR_PER_USD,
                  db.rate_card(con), db.duty_rates(con))
    except QuoteError as e:
        raise HTTPException(422, str(e)) from e
    return {**q.__dict__, "delivery_days": {"min": q.delivery_days[0], "max": q.delivery_days[1]}}
