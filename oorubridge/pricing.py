"""
Landed-cost quote: what a customer in San Jose or Denver pays, all in, for items from Bengaluru.

    subtotal     item prices in INR, converted to USD at the current rate
    shipping     air courier rate card by parcel weight (items + packaging), plus a destination surcharge
    duty         estimated US import duty per product category, on the USD item value
    service fee  OoruBridge's margin, a percentage of the subtotal

All money is Decimal and rounded to cents only at the end of each line, so totals always add up.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
PACKAGING_BASE_G = 200          # box and padding
PACKAGING_PER_ITEM_G = 30       # bubble wrap / pouch per unit
MAX_PARCEL_G = 20_000           # courier limit per parcel
SERVICE_FEE_PCT = Decimal("5")
PERISHABLE_BUFFER_DAYS = 7      # food must still be good a week after the latest delivery day


@dataclass(frozen=True)
class Product:
    product_id: int
    name: str
    category: str
    price_inr: Decimal
    weight_g: int
    shelf_life_days: int | None = None


@dataclass(frozen=True)
class Destination:
    code: str
    city: str
    min_days: int
    max_days: int
    surcharge_pct: Decimal = Decimal("0")


@dataclass
class Quote:
    destination: str
    fx_inr_per_usd: Decimal
    parcel_weight_g: int
    subtotal_inr: Decimal
    subtotal_usd: Decimal
    shipping_usd: Decimal
    duty_usd: Decimal
    service_fee_usd: Decimal
    total_usd: Decimal
    delivery_days: tuple[int, int]
    lines: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class QuoteError(ValueError):
    """The cart can't be shipped as requested (too heavy, empty, bad quantity)."""


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def parcel_weight(items: list[tuple[Product, int]]) -> int:
    units = sum(q for _, q in items)
    return PACKAGING_BASE_G + sum(p.weight_g * q for p, q in items) + PACKAGING_PER_ITEM_G * units


def shipping_price(weight_g: int, rate_card: dict[int, Decimal], dest: Destination) -> Decimal:
    """Cheapest tier that fits the parcel, plus the destination surcharge."""
    for max_g in sorted(rate_card):
        if weight_g <= max_g:
            return money(rate_card[max_g] * (1 + dest.surcharge_pct / 100))
    raise QuoteError(f"parcel weighs {weight_g / 1000:.1f} kg; the limit is {MAX_PARCEL_G / 1000:.0f} kg")


def quote(items: list[tuple[Product, int]], dest: Destination, fx_inr_per_usd: Decimal,
          rate_card: dict[int, Decimal], duty_rates: dict[str, Decimal]) -> Quote:
    if not items:
        raise QuoteError("the cart is empty")
    if any(q < 1 or q > 20 for _, q in items):
        raise QuoteError("quantities must be between 1 and 20")
    weight = parcel_weight(items)
    if weight > MAX_PARCEL_G:
        raise QuoteError(f"parcel weighs {weight / 1000:.1f} kg; the limit is {MAX_PARCEL_G / 1000:.0f} kg")

    lines, warnings = [], []
    subtotal_inr = subtotal_usd = duty = Decimal("0")
    for p, q in items:
        line_inr = p.price_inr * q
        line_usd = money(line_inr / fx_inr_per_usd)
        line_duty = money(line_usd * duty_rates.get(p.category, Decimal("0")))
        subtotal_inr += line_inr
        subtotal_usd += line_usd
        duty += line_duty
        lines.append(dict(product_id=p.product_id, name=p.name, quantity=q, price_inr=p.price_inr,
                          line_usd=line_usd, duty_usd=line_duty))
        if p.shelf_life_days is not None and p.shelf_life_days < dest.max_days + PERISHABLE_BUFFER_DAYS:
            warnings.append(f"{p.name} keeps {p.shelf_life_days} days; delivery to {dest.city} takes up to "
                            f"{dest.max_days} days, so it may arrive close to or past its best-before date")

    shipping = shipping_price(weight, rate_card, dest)
    fee = money(subtotal_usd * SERVICE_FEE_PCT / 100)
    total = subtotal_usd + shipping + duty + fee
    return Quote(destination=dest.code, fx_inr_per_usd=fx_inr_per_usd, parcel_weight_g=weight,
                 subtotal_inr=subtotal_inr, subtotal_usd=subtotal_usd, shipping_usd=shipping, duty_usd=duty,
                 service_fee_usd=fee, total_usd=total, delivery_days=(dest.min_days, dest.max_days),
                 lines=lines, warnings=warnings)
