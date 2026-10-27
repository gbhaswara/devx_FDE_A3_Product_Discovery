"""Pricing engine tests.

Every expected total here was recomputed from the live catalog with Decimal and
explicit half-up (ANALYZE_01.md §5 and §12), never transcribed. The catalog
facts used are the real ones:

    PL-CP-A4-80          list 129.00   tiers 10+ 122.55, 50+ 116.10
    PL-CP-A5-80          list  72.00   tier  10+  68.40
    PL-PR-A5-MT-100-10   list  79.00   tiers  5+  74.26, 20+ 69.52
    PL-PR-LTR-GL-130-40  list 265.00   tiers  5+ 249.10, 20+ 233.20
    PL-PR-LTR-GL-170-40  list 299.00   sale  259.00, volume suppressed
    PL-CP-A4-80-ECO      list 125.00   tier  10+ 120.00
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from paperlane.money import Money
from paperlane.pricing import (
    FLAT_DELIVERY_FEE,
    FREE_DELIVERY_THRESHOLD,
    LineRequest,
    PriceFacts,
    PriceTier,
    applied_tier,
    check_budget,
    quote,
    unit_price,
)


def baht(s: str) -> Money:
    return Money.from_baht(s)


# --- the real catalog facts, as fixtures -----------------------------------

A4_COPY = PriceFacts(
    sku="PL-CP-A4-80",
    list_price=baht("129.00"),
    tiers=(PriceTier(10, baht("122.55")), PriceTier(50, baht("116.10"))),
)

A5_COPY = PriceFacts(
    sku="PL-CP-A5-80",
    list_price=baht("72.00"),
    tiers=(PriceTier(10, baht("68.40")),),
)

A5_FLYER = PriceFacts(
    sku="PL-PR-A5-MT-100-10",
    list_price=baht("79.00"),
    tiers=(PriceTier(5, baht("74.26")), PriceTier(20, baht("69.52"))),
)

LTR_FLYER_130 = PriceFacts(
    sku="PL-PR-LTR-GL-130-40",
    list_price=baht("265.00"),
    tiers=(PriceTier(5, baht("249.10")), PriceTier(20, baht("233.20"))),
)

SALE_FLYER = PriceFacts(
    sku="PL-PR-LTR-GL-170-40",
    list_price=baht("299.00"),
    sale_price=baht("259.00"),
)

ECO = PriceFacts(
    sku="PL-CP-A4-80-ECO",
    list_price=baht("125.00"),
    tiers=(PriceTier(10, baht("120.00")),),
)


# ---------------------------------------------------------------------------
# 2.3 Unit price selection
# ---------------------------------------------------------------------------


class TestTierMet:
    """Test 1 of 3: the highest qualifying tier wins."""

    def test_tier_at_exact_boundary(self):
        assert unit_price(A4_COPY, 10) == baht("122.55")

    def test_higher_tier_wins(self):
        assert unit_price(A4_COPY, 50) == baht("116.10")
        assert unit_price(A4_COPY, 99) == baht("116.10")

    def test_between_tiers_uses_lower(self):
        assert unit_price(A4_COPY, 20) == baht("122.55")

    def test_applied_tier_reported(self):
        tier = applied_tier(A4_COPY, 20)
        assert tier is not None and tier.min_qty == 10


class TestNoTierMet:
    """Test 2 of 3: the list price is used, and nothing crashes.

    This is BUG.md A8 — the real defect found when a recompute script raised
    ``TypeError: NoneType * int`` at quantity 1.
    """

    def test_quantity_one_uses_list_price(self):
        # Most SKUs' lowest tier is 5+ or 10+, so qty 1 matches no tier.
        assert unit_price(A4_COPY, 1) == baht("129.00")

    def test_just_below_lowest_tier(self):
        assert unit_price(A4_COPY, 9) == baht("129.00")
        assert unit_price(A5_FLYER, 4) == baht("79.00")

    def test_no_tier_at_all_returns_list(self):
        plain = PriceFacts(sku="X", list_price=baht("152.00"))
        assert unit_price(plain, 1) == baht("152.00")
        assert unit_price(plain, 500) == baht("152.00")

    def test_does_not_return_none(self):
        # The exact failure mode: a min()-over-tiers bug returns nothing here.
        result = unit_price(A4_COPY, 1)
        assert result is not None
        assert isinstance(result, Money)

    def test_applied_tier_is_none(self):
        assert applied_tier(A4_COPY, 1) is None


class TestSalePrecedence:
    """Test 3 of 3: sale overrides both list and every tier (PR3)."""

    def test_sale_overrides_list(self):
        assert unit_price(SALE_FLYER, 1) == baht("259.00")

    def test_sale_overrides_what_would_be_a_tier(self):
        # 20 packs would normally attract a discount; on sale it does not.
        assert unit_price(SALE_FLYER, 20) == baht("259.00")
        assert unit_price(SALE_FLYER, 500) == baht("259.00")

    def test_sale_and_tiers_cannot_combine(self):
        with_tiers = PriceFacts(
            sku="S",
            list_price=baht("299.00"),
            tiers=(PriceTier(20, baht("233.20")),),
            sale_price=baht("259.00"),
        )
        # Not 233.20: the sale price replaces the tier.
        assert unit_price(with_tiers, 20) == baht("259.00")

    def test_applied_tier_none_when_on_sale(self):
        assert applied_tier(SALE_FLYER, 20) is None


class TestTiersArePerSku:
    """PR2: similar items do not pool their quantities."""

    def test_two_variants_do_not_pool(self):
        single = PriceFacts(
            sku="PL-PR-A4-GL-100-40",
            list_price=baht("215.00"),
            tiers=(PriceTier(5, baht("202.10")), PriceTier(20, baht("189.20"))),
        )
        double = PriceFacts(
            sku="PL-PR-A4-GL-100-44",
            list_price=baht("299.00"),
            tiers=(PriceTier(5, baht("281.06")), PriceTier(20, baht("263.12"))),
        )
        # 10 of each: each is priced from its own tiers, neither reaches 20+.
        assert unit_price(single, 10) == baht("202.10")
        assert unit_price(double, 10) == baht("281.06")

    def test_a_split_line_is_priced_on_the_total_quantity(self):
        # BUG.md A26. The tier belongs to the item, not to the way the caller
        # sliced the order: 10 + 10 of one SKU is 20 of that SKU.
        single = PriceFacts(
            sku="PL-PR-A4-GL-100-40",
            list_price=baht("215.00"),
            tiers=(PriceTier(5, baht("202.10")), PriceTier(20, baht("189.20"))),
        )
        q = quote([
            LineRequest("PL-PR-A4-GL-100-40", 10, single),
            LineRequest("PL-PR-A4-GL-100-40", 10, single),
        ])
        # 20 x 189.20, not 20 x 202.10.
        assert q.subtotal == baht("3784.00")
        # The caller's two lines survive; only the price is shared.
        assert [line.quantity for line in q.lines] == [10, 10]
        assert [line.unit_price for line in q.lines] == [baht("189.20")] * 2
        assert all(line.tier_applied.min_qty == 20 for line in q.lines)


class TestQuantityValidation:
    @pytest.mark.parametrize("bad", [0, -1])
    def test_non_positive_quantity_rejected(self, bad):
        with pytest.raises(ValueError, match="quantity must be"):
            unit_price(A4_COPY, bad)


# ---------------------------------------------------------------------------
# 2.4 Order assembly — the six published totals
# ---------------------------------------------------------------------------


class TestSmallOrder:
    """Delivery charged, and VAT on subtotal PLUS delivery."""

    def test_a5_copy_3_reams(self):
        # 216.00 + 150.00 delivery + 25.62 VAT = 391.62
        q = quote([LineRequest("PL-CP-A5-80", 3, A5_COPY)])
        assert q.subtotal == baht("216.00")
        assert q.delivery == baht("150.00")
        assert q.vat == baht("25.62")
        assert q.total == baht("391.62")

    def test_a5_copy_1_ream(self):
        # 72.00 + 150.00 + 15.54 = 237.54
        q = quote([LineRequest("PL-CP-A5-80", 1, A5_COPY)])
        assert q.total == baht("237.54")

    def test_vat_on_subtotal_only_would_be_wrong(self):
        # The detectable error: 7% of 216.00 = 15.12, not 25.62.
        q = quote([LineRequest("PL-CP-A5-80", 3, A5_COPY)])
        assert q.vat != baht("15.12")
        assert q.total != baht("381.12")
        assert q.total - baht("381.12") == baht("10.50")

    def test_a5_flyer_1_pack(self):
        # 79.00 + 150.00 + 16.03 = 245.03
        q = quote([LineRequest("PL-PR-A5-MT-100-10", 1, A5_FLYER)])
        assert q.total == baht("245.03")

    def test_a5_flyer_3_packs(self):
        q = quote([LineRequest("PL-PR-A5-MT-100-10", 3, A5_FLYER)])
        assert q.total == baht("414.09")

    def test_no_tier_met_at_quantity_one(self):
        # A4 copy at qty 1: list 129.00, not the 10+ tier.
        q = quote([LineRequest("PL-CP-A4-80", 1, A4_COPY)])
        assert q.subtotal == baht("129.00")
        assert q.total == baht("298.53")


class TestAboveThreshold:
    """Delivery is zero at or above 3000.00."""

    def test_a4_copy_50_reams(self):
        # 5805.00 + 0.00 + 406.35 = 6211.35
        q = quote([LineRequest("PL-CP-A4-80", 50, A4_COPY)])
        assert q.subtotal == baht("5805.00")
        assert q.delivery == baht("0.00")
        assert q.vat == baht("406.35")
        assert q.total == baht("6211.35")

    def test_a4_copy_10_reams(self):
        # 1225.50 + 150.00 + 96.29 = 1471.79
        q = quote([LineRequest("PL-CP-A4-80", 10, A4_COPY)])
        assert q.subtotal == baht("1225.50")
        assert q.total == baht("1471.79")

    def test_delivery_boundary_is_inclusive(self):
        # PL-CP-A4-80-ECO 25 x 120.00 = exactly 3000.00.
        # PR4 says free "from THB 3,000 or more", so delivery must be zero.
        q = quote([LineRequest("PL-CP-A4-80-ECO", 25, ECO)])
        assert q.subtotal == FREE_DELIVERY_THRESHOLD
        assert q.delivery == baht("0.00")

    def test_one_satang_below_threshold_pays_delivery(self):
        just_under = PriceFacts(sku="U", list_price=baht("2999.99"))
        q = quote([LineRequest("U", 1, just_under)])
        assert q.delivery == FLAT_DELIVERY_FEE


class TestMixedOrder:
    """Neither line crosses alone; the order does. Delivery once, not per line."""

    def test_mixed_basket(self):
        # 20 x 122.55 = 2451.00 ; 5 x 111.86 = 559.30 ; subtotal 3010.30
        a4_matte = PriceFacts(
            sku="PL-PR-A4-MT-100-10",
            list_price=baht("119.00"),
            tiers=(PriceTier(5, baht("111.86")), PriceTier(20, baht("104.72"))),
        )
        q = quote(
            [
                LineRequest("PL-CP-A4-80", 20, A4_COPY),
                LineRequest("PL-PR-A4-MT-100-10", 5, a4_matte),
            ]
        )
        assert q.lines[0].line_total == baht("2451.00")
        assert q.lines[1].line_total == baht("559.30")
        assert q.subtotal == baht("3010.30")
        assert q.delivery == baht("0.00")
        assert q.vat == baht("210.72")
        assert q.total == baht("3221.02")

    def test_per_line_delivery_would_be_visible(self):
        # The bug this case exists to catch: charging 150 per line.
        a4_matte = PriceFacts(
            sku="PL-PR-A4-MT-100-10",
            list_price=baht("119.00"),
            tiers=(PriceTier(5, baht("111.86")),),
        )
        q = quote(
            [
                LineRequest("PL-CP-A4-80", 20, A4_COPY),
                LineRequest("PL-PR-A4-MT-100-10", 5, a4_matte),
            ]
        )
        assert q.delivery != baht("300.00")
        # A per-line implementation would total 3542.02.
        assert q.total != baht("3542.02")
        assert q.total == baht("3221.02")

    def test_each_line_below_threshold_individually(self):
        a4_matte = PriceFacts(
            sku="PL-PR-A4-MT-100-10",
            list_price=baht("119.00"),
            tiers=(PriceTier(5, baht("111.86")),),
        )
        q = quote(
            [
                LineRequest("PL-CP-A4-80", 20, A4_COPY),
                LineRequest("PL-PR-A4-MT-100-10", 5, a4_matte),
            ]
        )
        for line in q.lines:
            assert line.line_total < FREE_DELIVERY_THRESHOLD


class TestOrderIntegrity:
    def test_total_is_sum_of_stated_parts(self):
        q = quote([LineRequest("PL-CP-A5-80", 3, A5_COPY)])
        assert q.total == q.subtotal + q.delivery + q.vat

    def test_subtotal_is_sum_of_lines(self):
        q = quote(
            [
                LineRequest("PL-CP-A4-80", 20, A4_COPY),
                LineRequest("PL-CP-A5-80", 3, A5_COPY),
            ]
        )
        total = Money.zero()
        for line in q.lines:
            total = total + line.line_total
        assert q.subtotal == total

    def test_empty_order_rejected(self):
        with pytest.raises(ValueError, match="empty order"):
            quote([])


class TestDiscountProvenance:
    """The reply must be able to say where a discount came from."""

    def test_tier_provenance(self):
        q = quote([LineRequest("PL-PR-LTR-GL-130-40", 20, LTR_FLYER_130)])
        assert "20+ tier" in q.lines[0].discount_source
        assert "265.00" in q.lines[0].discount_source

    def test_list_price_provenance(self):
        q = quote([LineRequest("PL-CP-A4-80", 1, A4_COPY)])
        assert q.lines[0].discount_source == "list price"

    def test_sale_provenance(self):
        q = quote([LineRequest("PL-PR-LTR-GL-170-40", 20, SALE_FLYER)])
        assert "sale" in q.lines[0].discount_source
        assert "no volume discount" in q.lines[0].discount_source


# ---------------------------------------------------------------------------
# 2.5 Budget comparison at the requested quantity
# ---------------------------------------------------------------------------


class TestBudget:
    """PR6/PR7 — the assignment's central trap."""

    def test_brief_example_passes_at_20(self):
        check = check_budget(LTR_FLYER_130, 20, baht("250.00"))
        assert check.unit_price == baht("233.20")
        assert check.within_budget is True

    def test_same_product_fails_at_quantity_1(self):
        check = check_budget(LTR_FLYER_130, 1, baht("250.00"))
        assert check.unit_price == baht("265.00")
        assert check.within_budget is False

    def test_verdict_flips_with_quantity(self):
        low = check_budget(LTR_FLYER_130, 1, baht("250.00"))
        high = check_budget(LTR_FLYER_130, 20, baht("250.00"))
        assert low.within_budget != high.within_budget

    def test_list_price_comparison_would_be_wrong(self):
        # What a naive implementation does: compare the list price to the
        # budget and conclude "no match" for the brief's own example.
        naive = LTR_FLYER_130.list_price <= baht("250.00")
        correct = check_budget(LTR_FLYER_130, 20, baht("250.00")).within_budget
        assert naive is False
        assert correct is True

    def test_inclusive_boundary(self):
        # PR6 says "maximum price per pack", so equality is within budget.
        exactly = PriceFacts(sku="E", list_price=baht("250.00"))
        assert check_budget(exactly, 1, baht("250.00")).within_budget is True

    def test_one_satang_over_fails(self):
        over = PriceFacts(sku="O", list_price=baht("250.01"))
        assert check_budget(over, 1, baht("250.00")).within_budget is False

    def test_basis_is_stated(self):
        check = check_budget(LTR_FLYER_130, 20, baht("250.00"))
        assert "before VAT" in check.basis
        assert "before VAT" in check.describe()

    def test_custom_basis_can_be_stated(self):
        check = check_budget(
            LTR_FLYER_130, 20, baht("250.00"), basis="per pack, including VAT"
        )
        assert "including VAT" in check.describe()

    def test_inclusive_basis_compares_the_gross_price(self):
        # BUG.md A21. The 20+ tier is 233.20 *before* VAT; the same pack is
        # 249.52 including it, which is over a 240.00 inclusive ceiling. Carrying
        # the basis as a label while comparing ex-VAT quoted the item anyway.
        check = check_budget(
            LTR_FLYER_130, 20, baht("240.00"), basis="per pack, including VAT"
        )
        assert check.unit_price == baht("249.52")
        assert check.within_budget is False

    def test_inclusive_basis_still_passes_under_the_ceiling(self):
        check = check_budget(
            LTR_FLYER_130, 20, baht("250.00"), basis="per pack, including VAT"
        )
        assert check.within_budget is True

    def test_difference_is_quantified(self):
        check = check_budget(A5_FLYER, 1, baht("60.00"))
        assert check.within_budget is False
        assert check.difference == baht("19.00")
        assert "19.00 over" in check.describe()


# ---------------------------------------------------------------------------
# 2.6 Purity
# ---------------------------------------------------------------------------


class TestPurity:
    def test_repeated_evaluation_is_identical(self):
        first = quote([LineRequest("PL-CP-A4-80", 20, A4_COPY)])
        second = quote([LineRequest("PL-CP-A4-80", 20, A4_COPY)])
        assert first.total == second.total
        assert first.subtotal == second.subtotal
        assert first.vat == second.vat
        assert first.delivery == second.delivery

    def test_ten_runs_identical(self):
        results = {
            quote([LineRequest("PL-PR-A5-MT-100-10", 20, A5_FLYER)]).total.satang
            for _ in range(10)
        }
        assert len(results) == 1

    def test_no_model_needed(self):
        # pricing.py imports no network or model client; a full quote is
        # produced from catalog facts alone.
        q = quote([LineRequest("PL-CP-A5-80", 3, A5_COPY)])
        assert q.total == baht("391.62")

    def test_no_float_anywhere_in_the_money_path(self):
        # Every monetary value is an int satang.
        q = quote([LineRequest("PL-CP-A4-80", 50, A4_COPY)])
        values = [q.subtotal, q.delivery, q.vat, q.total]
        for line in q.lines:
            values += [line.unit_price, line.line_total, line.list_price]
        for value in values:
            assert isinstance(value.satang, int)
            assert not isinstance(value.satang, float)

    def test_input_facts_not_mutated(self):
        before = A4_COPY.list_price.satang
        quote([LineRequest("PL-CP-A4-80", 50, A4_COPY)])
        assert A4_COPY.list_price.satang == before
