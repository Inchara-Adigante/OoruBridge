"""
OoruBridge API (first slice): browse Bengaluru shops' products and get an all-in price for delivery
to San Jose or Denver.

Run:  uvicorn oorubridge.api:app --reload      then open http://localhost:8000/docs
"""
from collections.abc import Iterator
from decimal import Decimal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, ValidationError

from oorubridge import db, payments
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


class NewCustomer(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: str = Field(min_length=1, max_length=200)
    destination: str = Field(examples=["SJC"])
    zip: str = Field(pattern=r"^[0-9]{5}$", examples=["95112"])


class NewOrder(BaseModel):
    customer_id: int
    items: list[CartItem] = Field(min_length=1)
    idempotency_key: str | None = Field(None, min_length=8, max_length=100,
                                        description="Send the same key when retrying, to avoid a duplicate order")


def merge_quantities(items: list[CartItem]) -> dict[int, int]:
    qty: dict[int, int] = {}
    for item in items:                       # the same product twice in a cart counts once
        qty[item.product_id] = qty.get(item.product_id, 0) + item.quantity
    return qty


class PaymentEvent(BaseModel):
    provider_ref: str = Field(min_length=4, max_length=100)
    order_id: int
    amount_usd: Decimal = Field(ge=0, decimal_places=2)
    status: str = Field(pattern="^(succeeded|failed)$")


class TrackingEvent(BaseModel):
    status: str = Field(examples=["shipped_from_blr"])
    location: str = Field(min_length=2, max_length=200, examples=["Bengaluru air cargo hub"])


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
    qty = merge_quantities(req.items)
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


@app.post("/customers", status_code=201)
def create_customer(req: NewCustomer, con=Depends(get_con)) -> dict:
    dest = req.destination.upper()
    if dest not in db.destinations(con):
        raise HTTPException(400, f"we don't deliver to {req.destination!r} yet")
    try:
        return db.create_customer(con, req.email, req.full_name.strip(), dest, req.zip)
    except psycopg.errors.UniqueViolation as e:
        raise HTTPException(409, "an account with this email already exists") from e
    except psycopg.errors.CheckViolation as e:
        raise HTTPException(422, e.diag.message_primary) from e


@app.get("/customers/{customer_id}")
def get_customer(customer_id: int, con=Depends(get_con)) -> dict:
    customer = db.get_customer(con, customer_id)
    if customer is None:
        raise HTTPException(404, "customer not found")
    return customer


@app.post("/orders", status_code=201)
def place_order(req: NewOrder, response: Response, con=Depends(get_con)) -> dict:
    """Place an order at today's prices and exchange rate. Retrying with the same idempotency_key is safe."""
    try:
        order_id, created = db.place_order(con, req.customer_id, merge_quantities(req.items), req.idempotency_key)
    except db.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except db.OutOfStock as e:
        raise HTTPException(409, {"message": "not enough stock", "items": e.short}) from e
    except QuoteError as e:
        raise HTTPException(422, str(e)) from e
    if not created:
        response.status_code = 200
    return db.get_order(con, order_id)


@app.get("/orders/{order_id}")
def get_order(order_id: int, con=Depends(get_con)) -> dict:
    order = db.get_order(con, order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    return order


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, con=Depends(get_con)) -> dict:
    try:
        db.cancel_order(con, order_id)
    except db.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except db.CannotCancel as e:
        raise HTTPException(409, str(e)) from e
    return db.get_order(con, order_id)


@app.get("/customers/{customer_id}/orders")
def customer_orders(customer_id: int, con=Depends(get_con)) -> list[dict]:
    if db.get_customer(con, customer_id) is None:
        raise HTTPException(404, "customer not found")
    return db.customer_orders(con, customer_id)


@app.post("/webhooks/payments")
async def payment_webhook(request: Request, signature: str | None = Header(None, alias=payments.SIGNATURE_HEADER),
                          con=Depends(get_con)) -> dict:
    """Called by the payment provider. Signed with HMAC-SHA256; safe to deliver more than once."""
    body = await request.body()
    if not payments.signature_ok(body, signature):
        raise HTTPException(401, "invalid signature")
    try:
        event = PaymentEvent.model_validate_json(body)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False)) from e
    try:
        result = payments.record_payment(con, event.order_id, event.provider_ref, event.amount_usd, event.status)
    except db.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except payments.AmountMismatch as e:
        raise HTTPException(422, str(e)) from e
    return {"result": result}


@app.post("/orders/{order_id}/events")
def add_tracking_event(order_id: int, ev: TrackingEvent, con=Depends(get_con)) -> dict:
    """For the shop, the courier and customs updates: move the order to its next step."""
    if ev.status not in db.JOURNEY:
        raise HTTPException(422, f"status must be one of {db.JOURNEY}")
    try:
        db.advance_order(con, order_id, ev.status, ev.location)
    except db.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except db.BadTransition as e:
        raise HTTPException(409, str(e)) from e
    return db.tracking(con, order_id)


@app.get("/orders/{order_id}/tracking")
def get_tracking(order_id: int, con=Depends(get_con)) -> dict:
    t = db.tracking(con, order_id)
    if t is None:
        raise HTTPException(404, "order not found")
    return t
