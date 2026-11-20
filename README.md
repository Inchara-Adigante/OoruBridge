# OoruBridge

[![CI](https://github.com/Inchara-Adigante/OoruBridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Inchara-Adigante/OoruBridge/actions/workflows/ci.yml)

**Shop from Bengaluru, delivered to San Jose and Denver.**

*Ooru* (ಊರು) means hometown in Kannada. OoruBridge connects Bengaluru's neighbourhood shops (the sweet house in
Malleshwaram, the masala mill in Basavanagudi, the silk centre in Chickpet) with people in the US who miss them.
Customers see one honest, all-in price in dollars before they order: item cost, international shipping, estimated
import duty and fees, plus a delivery window and a warning if something perishable might not survive the trip.

> **Status:** initial setup. The catalog and the landed-cost quote API work end to end; ordering, payments and
> tracking are next (see the [roadmap](#roadmap)).

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
| `GET /health` | Health check |

Interactive docs at `http://localhost:8000/docs`.

## Run it

Requirements: Python 3.11+ and PostgreSQL 16 (local, or `docker compose up -d`).

```bash
make venv            # virtualenv + dependencies
make setup           # create the database, apply migrations, load the sample catalog
make run             # API on http://localhost:8000
make test            # 15 tests: pricing rules + API against a real test database
```

With Docker's database, first run `export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/oorubridge`.

## Project structure

```
OoruBridge/
├── oorubridge/
│   ├── pricing.py        landed-cost rules (pure functions, no database)
│   ├── db.py             queries and settings
│   └── api.py            FastAPI app
├── db/
│   ├── migrations/       schema: sellers, products, destinations, rate cards, orders, tracking
│   └── seed/             sample Bengaluru shops and products
├── scripts/migrate.py    applies migrations once, with checksums; --seed loads sample data
├── tests/                pricing and API tests
└── docker-compose.yml · Makefile · .github/workflows/ci.yml
```

## Roadmap

| Stage | Scope | Status |
|---|---|---|
| **0. Setup** | Schema, sample catalog, landed-cost quote API, tests, CI | ✅ Done |
| **1. Orders** | Customers, checkout with the exchange rate frozen at order time, stock reservation without overselling | Next |
| **2. Payments & tracking** | Payment webhooks (idempotent), shipment timeline: shop → Bengaluru hub → US customs → doorstep | Planned |
| **3. Seller tools** | Seller onboarding and verification, inventory updates, payouts in INR | Planned |
| **4. Data & insights** | Pipeline from orders and tracking into a warehouse: popular items per city, delivery times, festival demand (Diwali, Ugadi) | Planned |
| **5. Frontend** | Web storefront in English and Kannada | Planned |

## Tech

Python, FastAPI, Pydantic, PostgreSQL 16, psycopg 3, pytest, Docker, GitHub Actions.
