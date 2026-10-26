"""Money tests: exactness and explicit half-up rounding.

The two scenarios from the pricing spec that this file proves:

* half-up rounding is applied explicitly
* accumulated totals are exact

Plus the guard that no float can enter the money path at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from paperlane.money import (
    Money,
    format_baht,
    percent_of,
    round_half_up,
    to_baht,
    to_satang,
)


class TestHalfUpRounding:
    def test_exact_half_rounds_away_from_zero(self):
        # The case where half-to-even and half-up disagree. Python's round()
        # gives 2.68 for 2.675 (via float) and 2.68 for half-even; half-up on
        # the exact Decimal gives 2.68 too, so use a value where they differ:
        # 0.125 -> half-even 0.12, half-up 0.13.
        assert round_half_up(Decimal("0.125")) == Decimal("0.13")

    def test_half_up_differs_from_python_default(self):
        value = Decimal("0.125")
        assert round(value, 2) == Decimal("0.12")          # half-to-even
        assert round_half_up(value) == Decimal("0.13")     # half-up
        assert round_half_up(value) != round(value, 2)

    def test_half_up_on_negative_half(self):
        # "Away from zero" means -0.125 -> -0.13, not -0.12.
        assert round_half_up(Decimal("-0.125")) == Decimal("-0.13")

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2.675", "2.68"),
            ("1.005", "1.01"),
            ("0.004", "0.00"),
            ("0.005", "0.01"),
            ("10.505", "10.51"),
        ],
    )
    def test_known_values(self, raw, expected):
        assert round_half_up(Decimal(raw)) == Decimal(expected)

    def test_requires_decimal(self):
        with pytest.raises(TypeError, match="requires Decimal"):
            round_half_up(2.675)  # float is refused, not silently converted


class TestSatangConversion:
    def test_round_trip(self):
        assert to_satang("129.00") == 12900
        assert to_baht(12900) == Decimal("129.00")

    def test_accepts_str_decimal_int(self):
        assert to_satang("233.20") == 23320
        assert to_satang(Decimal("233.20")) == 23320
        assert to_satang(5) == 500

    def test_rejects_float(self):
        with pytest.raises(TypeError, match="refusing float"):
            to_satang(129.00)

    def test_float_would_have_been_wrong(self):
        # Why the guard exists: float(233.20) is not exactly 233.20.
        assert Decimal(233.20) != Decimal("233.20")
        assert to_satang("233.20") == 23320  # the str path is exact


class TestAccumulationIsExact:
    def test_many_small_amounts_do_not_drift(self):
        # 0.01 added 1000 times is exactly 10.00. In float this accumulates error.
        total = Money.zero()
        one = Money.from_baht("0.01")
        for _ in range(1000):
            total = total + one
        assert total.satang == 1000
        assert total.format() == "10.00"

    def test_float_accumulation_would_drift(self):
        # Demonstrates the failure mode being avoided.
        acc = 0.0
        for _ in range(10):
            acc += 0.1
        assert acc != 1.0                      # drift is real
        exact = Money.zero()
        for _ in range(10):
            exact = exact + Money.from_baht("0.10")
        assert exact.satang == 100         # exact path is not


class TestMoneyArithmetic:
    def test_multiply_by_quantity(self):
        unit = Money.from_baht("233.20")
        assert (unit * 20).satang == 466400
        assert (unit * 20).format() == "4,664.00"

    def test_multiply_rejects_non_int(self):
        with pytest.raises(TypeError, match="int quantity"):
            Money.from_baht("1.00") * Decimal("2")

    def test_add_and_subtract(self):
        a = Money.from_baht("4664.00")
        b = Money.from_baht("326.48")
        assert (a + b).format() == "4,990.48"
        assert (a - b).format() == "4,337.52"

    def test_no_float_in_construction(self):
        with pytest.raises(TypeError, match="int satang"):
            Money(129.0)

    def test_ordering(self):
        assert Money.from_baht("1.00") < Money.from_baht("2.00")
        assert sorted([Money.from_baht("3"), Money.from_baht("1")])[0].satang == 100


class TestVat:
    def test_vat_on_subtotal_plus_delivery(self):
        # The A5 copy 3-ream case: 216.00 + 150.00 delivery, VAT 7% = 25.62.
        taxable = Money.from_baht("216.00") + Money.from_baht("150.00")
        vat = percent_of(taxable, Decimal("7"))
        assert vat.satang == 2562
        assert vat.format() == "25.62"

    def test_vat_rounds_half_up(self):
        # 0.50 * 7% = 0.035 -> half-up 0.04
        vat = percent_of(Money.from_baht("0.50"), Decimal("7"))
        assert vat.satang == 4

    def test_vat_on_large_subtotal(self):
        # 4664.00 * 7% = 326.48
        vat = percent_of(Money.from_baht("4664.00"), Decimal("7"))
        assert vat.format() == "326.48"


class TestFormatting:
    def test_grouping(self):
        assert format_baht(621135) == "6,211.35"
        assert format_baht(72_00) == "72.00"
        assert format_baht(0) == "0.00"

    def test_no_currency_symbol(self):
        assert "฿" not in format_baht(12900)
        assert "THB" not in format_baht(12900)
