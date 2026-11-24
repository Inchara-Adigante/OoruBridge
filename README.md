# OoruBridge

[![CI](https://github.com/Inchara-Adigante/OoruBridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Inchara-Adigante/OoruBridge/actions/workflows/ci.yml)

**Shop from Bengaluru, delivered to San Jose and Denver.**

*Ooru* (ಊರು) means hometown in Kannada. OoruBridge connects Bengaluru's neighbourhood shops (the sweet house in
Malleshwaram, the masala mill in Basavanagudi, the silk centre in Chickpet) with people in the US who miss them.
Customers see one honest, all-in price in dollars before they order: item cost, international shipping, estimated
import duty and fees, plus a delivery window and a warning if something perishable might not survive the trip.

> **Status:** stage 2 done. Customers can browse, get an all-in quote, sign up, order without overselling, pay
> through a signed webhook, and follow their parcel from the Bengaluru shop to their door. Seller tools are next
> (see the [roadmap](#roadmap)).

## How it works

```mermaid
flowchart LR
    S["Bengaluru shops<br/>Malleshwaram · Basavanagudi<br/>Chickpet · Gandhi Bazaar"] -->|catalog in INR| DB[("PostgreSQL<br/>sellers · products<br/>rate cards · orders")]
    C["Customer in<br/>San Jose or Denver"] -->|cart| API["OoruBridge API<br/>(FastAPI)"]
    API --> DB
    API -->|"all-in quote in USD:<br/>items + shipping + duty + fee"| C
    API -.->|next| O["Orders, payments<br/>and tracking<br/>BLR → US customs → door"]
```

## The quote

For each cart the API returns:

| Part | How it's calculated |
|---|---|
| Items | Prices in rupees, converted at the current exchange rate |
| Shipping | Air courier rate card by parcel weight (items + packaging), plus a destination surcharge |
| Duty | Estimated US import duty by product category (sweets, spices, textiles, books...) |
| Service fee | 5% of the item value |
| Delivery | 6–9 days to San Jose, 7–10 days to Denver |
| Warnings | Perishables whose shelf life is too short for the trip; parcels over the 20 kg limit |

Example: one Mysore silk saree and two packs of chiroti to San Jose:

```bash
curl -X POST localhost:8000/quotes -H 'content-type: application/json' \
  -d '{"destination": "SJC", "items": [{"product_id": 7, "quantity": 1}, {"product_id": 2, "quantity": 2}]}'
```
```json
{
  "subtotal_inr": "15260.00", "subtotal_usd": "181.67",
  "shipping_usd": "42.00", "duty_usd": "21.62", "service_fee_usd": "9.08",
  "total_usd": "254.37",
  "delivery_days": {"min": 6, "max": 9},
  "warnings": ["Chiroti (12 pieces) keeps 7 days; delivery to San Jose takes up to 9 days, so it may arrive close to or past its best-before date"]
}
```

All amounts use `Decimal` and are rounded per line, so the parts always add up to the total (also enforced by a
`CHECK` constraint on orders).

> Exchange rate, shipping rates and duty percentages in this repo are **sample values for development**, not
> customs or shipping advice. US import rules for personal shipments change; production would load them from the
> carrier and current customs guidance.

## API

| Endpoint | What it does |
|---|---|
| `GET /products?category=&area=&q=&max_price_inr=` | Browse the catalog by category, Bengaluru area, search text or price |
| `GET /destinations` | Cities we deliver to, with delivery windows |
| `POST /quotes` | All-in landed cost for a cart |
| `POST /customers` · `GET /customers/{id}` | Sign up; the ZIP code must be in the chosen delivery area |
| `POST /orders` | Checkout at today's prices and exchange rate; send an `idempotency_key` to retry safely |
| `GET /orders/{id}` | Order with items, totals and its tracking timeline |
| `POST /orders/{id}/cancel` | Cancel before the parcel is packed; stock goes back to the shop |
| `GET /customers/{id}/orders` | Order history, newest first |
| `POST /webhooks/payments` | Payment provider callback: signed with HMAC-SHA256, safe to deliver twice |
| `POST /orders/{id}/events` | Shop, courier or customs moves the order to its next step |
| `GET /orders/{id}/tracking` | Where the parcel is, progress, and estimated delivery dates |
| `GET /health` | Health check |

Interactive docs at `http://localhost:8000/docs`.

## Checkout guarantees

| Guarantee | How |
|---|---|
| A shop's stock is never oversold, even when many people order the last item at the same moment | Product rows are locked `FOR UPDATE` during checkout; tested with 20 concurrent shoppers for 5 jars: exactly 5 orders |
| No deadlocks between checkouts | Every checkout and cancellation locks products in the same order (by id) |
| An order never changes after it's placed | Prices and the INR/USD rate are copied into the order; totals must add up (`CHECK` constraint) |
| A retried "Place order" never creates a second order | Optional idempotency key, unique per customer; two simultaneous retries also return the same order |
| We only accept orders we can deliver | The customer's ZIP code must start with a prefix of their delivery area (San Jose 950/951, Denver 800–802) |
| A failed checkout leaves nothing behind | Everything happens in one transaction: out of stock means no order, no stock change |

## Payments and tracking

```mermaid
stateDiagram-v2
    direction LR
    [*] --> placed
    placed --> paid : signed payment webhook
    paid --> packed : shop
    packed --> shipped_from_blr : Bengaluru air cargo
    shipped_from_blr --> in_us_customs
    in_us_customs --> out_for_delivery
    out_for_delivery --> delivered
    placed --> cancelled
    paid --> cancelled : payment flagged for refund
```

- **Payments:** the provider's webhook must carry a valid HMAC-SHA256 signature. Each event is stored once (by its
  provider reference), so retries never double-count. The amount must equal the order total. Money that arrives for
  a cancelled or already-paid order is kept and flagged for refund, never silently lost.
- **Tracking:** an order moves forward one step at a time. A database trigger enforces it, so no client can skip or
  reverse a step, and cancelling is only possible before the parcel is packed. Once it leaves Bengaluru, the tracking
  page shows an estimated delivery window (6–9 days to San Jose, 7–10 to Denver).

## Run it

Requirements: Python 3.11+ and PostgreSQL 16 (local, or `docker compose up -d`).

```bash
make venv            # virtualenv + dependencies
make setup           # create the database, apply migrations, load the sample catalog
make run             # API on http://localhost:8000
make test            # 40 tests: pricing, customers, checkout (including a concurrency race), payments, tracking
```

With Docker's database, first run `export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/oorubridge`.

## Project structure

```
OoruBridge/
├── oorubridge/
│   ├── pricing.py        landed-cost rules (pure functions, no database)
│   ├── db.py             queries, checkout, cancellation, tracking
│   ├── payments.py       signed, idempotent payment webhooks
│   └── api.py            FastAPI app
├── db/
│   ├── migrations/       001 schema · 002 ZIP rules · 003 checkout idempotency · 004 payments · 005 status rules
│   └── seed/             sample Bengaluru shops and products
├── scripts/migrate.py    applies migrations once, with checksums; --seed loads sample data
├── tests/                pricing, catalog, customers, checkout, payments and tracking tests
└── docker-compose.yml · Makefile · .github/workflows/ci.yml
```

## Roadmap

| Stage | Scope | Status |
|---|---|---|
| **0. Setup** | Schema, sample catalog, landed-cost quote API, tests, CI | ✅ Done |
| **1. Orders** | Customers with delivery-area checks, checkout with prices and exchange rate frozen, stock that can't be oversold, safe retries, cancellation, order history | ✅ Done |
| **2. Payments & tracking** | Signed, idempotent payment webhooks; refunds flagged; step-by-step tracking enforced by the database, with delivery estimates | ✅ Done |
| **3. Seller tools** | Seller onboarding and verification, inventory updates, payouts in INR | Next |
| **4. Data & insights** | Pipeline from orders and tracking into a warehouse: popular items per city, delivery times, festival demand (Diwali, Ugadi) | Planned |
| **5. Frontend** | Web storefront in English and Kannada | Planned |

## Tech

Python, FastAPI, Pydantic, PostgreSQL 16, psycopg 3, pytest, Docker, GitHub Actions.
