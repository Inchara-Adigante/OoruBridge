"""Landed-cost rules, tested without a database."""
from decimal import Decimal

import pytest

from oorubridge.pricing import Destination, Product, QuoteError, parcel_weight, quote, shipping_price

D = Decimal
RATES = {500: D("18"), 1000: D("28"), 2000: D("42"), 5000: D("78"), 10000: D("135"), 20000: D("240")}
DUTY = {"sweets_snacks": D("0.10"), "spices": D("0.05"), "textiles": D("0.12"), "books": D("0")}
SJC = Destination("SJC", "San Jose", 6, 9, D("0"))
DEN = Destination("DEN", "Denver", 7, 10, D("8"))
FX = D("84")

MYSORE_PAK = Product(1, "Mysore Pak (500 g)", "sweets_snacks", D("420"), 550, 30)
CHIROTI = Product(2, "Chiroti (12 pieces)", "sweets_snacks", D("380"), 400, 7)
SAMBAR = Product(5, "Sambar Powder (500 g)", "spices", D("240"), 520, 180)
SAREE = Product(7, "Mysore Silk Saree", "textiles", D("14500"), 700, None)


def test_total_is_the_sum_of_its_parts():
    q = quote([(MYSORE_PAK, 2), (SAMBAR, 1)], SJC, FX, RATES, DUTY)
    # 2 x 420 + 240 = 1,080 INR = $12.86 at 84
    assert q.subtotal_inr == 1080 and q.subtotal_usd == D("12.86")
    assert q.parcel_weight_g == 200 + 2 * 550 + 520 + 3 * 30          # 1,910 g -> 2 kg tier
    assert q.shipping_usd == D("42.00")
    assert q.duty_usd == D("1.00") + D("0.14")                        # 10% of $10.00 + 5% of $2.86
    assert q.service_fee_usd == D("0.64")                             # 5% of $12.86
    assert q.total_usd == q.subtotal_usd + q.shipping_usd + q.duty_usd + q.service_fee_usd == D("56.64")


def test_denver_pays_the_surcharge_and_waits_longer():
    sjc, den = (quote([(SAREE, 1)], d, FX, RATES, DUTY) for d in (SJC, DEN))
    assert sjc.shipping_usd == D("28.00") and den.shipping_usd == D("30.24")   # +8%
    assert sjc.delivery_days == (6, 9) and den.delivery_days == (7, 10)
    assert sjc.duty_usd == den.duty_usd == D("20.71")                          # 12% of $172.62


def test_parcel_weight_includes_packaging():
    assert parcel_weight([(SAMBAR, 2)]) == 200 + 1040 + 60


def test_cheapest_tier_that_fits():
    assert shipping_price(500, RATES, SJC) == D("18.00")
    assert shipping_price(501, RATES, SJC) == D("28.00")


def test_perishables_that_may_not_survive_the_trip_are_flagged():
    q = quote([(CHIROTI, 1), (MYSORE_PAK, 1)], SJC, FX, RATES, DUTY)
    assert len(q.warnings) == 1 and "Chiroti" in q.warnings[0]


def test_unknown_category_has_no_duty():
    toy = Product(9, "Toy", "unlisted", D("840"), 300)
    assert quote([(toy, 1)], SJC, FX, RATES, DUTY).duty_usd == 0


@pytest.mark.parametrize("items, message", [
    ([], "empty"),
    ([(SAMBAR, 0)], "between 1 and 20"),
    ([(SAREE, 20), (MYSORE_PAK, 20)], "limit is 20 kg"),
])
def test_carts_that_cannot_ship(items, message):
    with pytest.raises(QuoteError, match=message):
        quote(items, SJC, FX, RATES, DUTY)
