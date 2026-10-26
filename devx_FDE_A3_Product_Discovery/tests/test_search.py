"""Search tests: hard constraints, not-applicable semantics, ranking, justification.

The products and facts used here are built from the real catalog shape, so the
tests assert against values that actually exist (A4 copy at 129.00, the 20+
tier at 233.20, the single sale item, the two out-of-stock items).
"""

from __future__ import annotations

import pytest

from paperlane.criteria import Criteria
from paperlane.money import Money
from paperlane.pricing import PriceFacts, PriceTier
from paperlane.search import (
    RANKING_ORDER,
    Candidate,
    search,
)


def b(s: str) -> Money:
    return Money.from_baht(s)


def product(sku, **overrides):
    """A catalog row with the real column names."""
    base = {
        "sku": sku,
        "name": f"Product {sku}",
        "brand": "Testbrand",
        "category": "Copy paper",
        "size_code": "A4",
        "width_mm": 210,
        "height_mm": 297,
        "weight_gsm": 80,
        "colour_name": "White",
        "colour_mode": None,
        "sides": None,
        "finish": "Uncoated",
        "pack_sheets": 500,
        "stock_status": "in_stock",
        "back_in_stock_date": None,
    }
    base.update(overrides)
    return base


def facts(sku, list_price, tiers=(), sale=None):
    """``tiers`` is a sequence of ``(price, min_qty)`` pairs."""
    return PriceFacts(
        sku=sku,
        list_price=b(list_price),
        tiers=tuple(PriceTier(q, b(p)) for p, q in tiers),
        sale_price=b(sale) if sale else None,
    )


#: A small catalog with the real value shapes.
CATALOG = [
    product("PL-CP-A4-80", name="Lotus Bright Premium A4 80gsm"),
    product("PL-CP-A5-80", size_code="A5", width_mm=148, height_mm=210,
            name="PaperLane Essentials A5 80gsm"),
    product("PL-CP-A4-80-ECO", name="PaperLane Essentials Recycled A4 80gsm"),
    product("PL-CS-A4-200-WH", category="Card and photo", weight_gsm=200,
            pack_sheets=100, finish="Smooth", name="PaperLane Card A4 200gsm White"),
    product("PL-CL-A4-80-PBL", category="Coloured paper",
            colour_name="pastel blue", name="Rainbow Pastel A4 80gsm Pastel Blue"),
    product("PL-CL-A4-100-IVY", category="Coloured paper", weight_gsm=100,
            colour_name="ivory", stock_status="out_of_stock",
            back_in_stock_date="20 November 2026", name="Heritage Ivory A4 100gsm"),
    product("PL-PR-LTR-GL-130-40", category="Flyer printing", size_code="LTR",
            width_mm=216, height_mm=279, weight_gsm=130, colour_name=None,
            colour_mode="Full colour (CMYK)", sides="single", finish="Gloss",
            pack_sheets=100, name="Letter-size Flyers — 130 gsm Single-sided"),
    product("PL-PR-LTR-GL-130-44", category="Flyer printing", size_code="LTR",
            width_mm=216, height_mm=279, weight_gsm=130, colour_name=None,
            colour_mode="Full colour (CMYK)", sides="double", finish="Gloss",
            pack_sheets=100, name="Letter-size Flyers — 130 gsm Double-sided"),
    product("PL-PR-A4-MT-100-10", category="Flyer printing", weight_gsm=100,
            colour_name=None, colour_mode="Black and white", sides="single",
            finish="Matte", pack_sheets=100,
            name="Digital Flyers A4 — 100 gsm Single-sided"),
]

FACTS = {
    "PL-CP-A4-80": facts("PL-CP-A4-80", "129.00",
                         [("122.55", 10), ("116.10", 50)]),
    "PL-CP-A5-80": facts("PL-CP-A5-80", "72.00", [("68.40", 10)]),
    "PL-CP-A4-80-ECO": facts("PL-CP-A4-80-ECO", "125.00", [("120.00", 10)]),
    "PL-CS-A4-200-WH": facts("PL-CS-A4-200-WH", "178.00"),
    "PL-CL-A4-80-PBL": facts("PL-CL-A4-80-PBL", "195.00"),
    "PL-CL-A4-100-IVY": facts("PL-CL-A4-100-IVY", "168.00"),
    "PL-PR-LTR-GL-130-40": facts("PL-PR-LTR-GL-130-40", "265.00",
                                 [("249.10", 5), ("233.20", 20)]),
    "PL-PR-LTR-GL-130-44": facts("PL-PR-LTR-GL-130-44", "359.00",
                                 [("337.46", 5), ("315.92", 20)]),
    "PL-PR-A4-MT-100-10": facts("PL-PR-A4-MT-100-10", "119.00",
                                [("111.86", 5), ("104.72", 20)]),
}


def run(criteria, quantity=None):
    return search(criteria, CATALOG, FACTS, quantity=quantity)


# ---------------------------------------------------------------------------
# 4.1 Hard constraints
# ---------------------------------------------------------------------------


class TestHardConstraints:
    def test_size_is_a_hard_constraint(self):
        result = run(Criteria(size_code="A5"))
        assert [c.sku for c in result.matches] == ["PL-CP-A5-80"]

    def test_weight_is_a_hard_constraint(self):
        result = run(Criteria(weight_gsm=200))
        assert [c.sku for c in result.matches] == ["PL-CS-A4-200-WH"]

    def test_finish_is_a_hard_constraint(self):
        result = run(Criteria(finish="Matte"))
        assert [c.sku for c in result.matches] == ["PL-PR-A4-MT-100-10"]

    def test_shade_is_a_hard_constraint(self):
        result = run(Criteria(colour_name="pastel blue"))
        assert [c.sku for c in result.matches] == ["PL-CL-A4-80-PBL"]

    def test_category_is_a_hard_constraint(self):
        result = run(Criteria(category="Coloured paper"))
        # IVY is out of stock, so it is reported as unavailable, not offered.
        assert {c.sku for c in result.matches} == {"PL-CL-A4-80-PBL"}
        assert {c.sku for c in result.unavailable} == {"PL-CL-A4-100-IVY"}
        assert {c.sku for c in result.matches} | {
            c.sku for c in result.unavailable
        } == {"PL-CL-A4-80-PBL", "PL-CL-A4-100-IVY"}

    def test_contradicting_items_are_excluded(self):
        # A5 + 200 gsm: no item is both.
        result = run(Criteria(size_code="A5", weight_gsm=200))
        assert result.matches == ()

    def test_weight_range_is_a_hard_constraint(self):
        result = run(Criteria(weight_gsm_min=130))
        assert {c.sku for c in result.matches} == {
            "PL-CS-A4-200-WH", "PL-PR-LTR-GL-130-40", "PL-PR-LTR-GL-130-44"
        }

    def test_sides_excludes_the_wrong_side_for_printed_goods(self):
        # Plain paper has no sides, so it passes through; the single-sided
        # flyer is genuinely excluded because its sides contradict the request.
        result = run(Criteria(category="Flyer printing", sides="double",
                              colour_mode="Full colour (CMYK)"))
        assert [c.sku for c in result.matches] == ["PL-PR-LTR-GL-130-44"]


# ---------------------------------------------------------------------------
# 4.2 Not-applicable semantics
# ---------------------------------------------------------------------------


class TestNotApplicable:
    def test_printing_constraint_does_not_exclude_plain_paper(self):
        # The plain-paper items have sides=None. They must remain eligible.
        result = run(Criteria(sides="double"))
        skus = {c.sku for c in result.matches}
        assert "PL-PR-LTR-GL-130-44" in skus          # genuinely double-sided
        assert "PL-CP-A4-80" in skus                  # plain paper, not applicable
        assert "PL-PR-LTR-GL-130-40" not in skus      # genuinely single-sided

    def test_plain_paper_is_not_claimed_to_match_the_printing_constraint(self):
        result = run(Criteria(sides="double"))
        plain = next(c for c in result.matches if c.sku == "PL-CP-A4-80")
        attributes = [r.attribute for r in plain.match_reasons]
        assert "sides" not in attributes

    def test_colour_mode_constraint_does_not_exclude_plain_paper(self):
        result = run(Criteria(colour_mode="Black and white"))
        skus = {c.sku for c in result.matches}
        assert "PL-PR-A4-MT-100-10" in skus
        assert "PL-CP-A4-80" in skus                  # plain paper unaffected

    def test_shade_constraint_still_excludes_printed_goods_with_no_shade(self):
        # A shade constraint applies to everything, and flyers have no shade.
        result = run(Criteria(colour_name="white"))
        skus = {c.sku for c in result.matches}
        assert "PL-CP-A4-80" in skus
        assert "PL-PR-LTR-GL-130-44" not in skus


# ---------------------------------------------------------------------------
# 4.5 Deterministic ranking
# ---------------------------------------------------------------------------


class TestRanking:
    def test_cheapest_qualifying_first(self):
        result = run(Criteria(size_code="A4"))
        prices = [c.unit_price.satang for c in result.matches]
        assert prices == sorted(prices)

    def test_repeated_runs_identical(self):
        first = [c.sku for c in run(Criteria(size_code="A4")).matches]
        for _ in range(5):
            assert [c.sku for c in run(Criteria(size_code="A4")).matches] == first

    def test_input_order_does_not_matter(self):
        forward = [c.sku for c in search(
            Criteria(size_code="A4"), CATALOG, FACTS).matches]
        backward = [c.sku for c in search(
            Criteria(size_code="A4"), list(reversed(CATALOG)), FACTS).matches]
        assert forward == backward

    def test_ties_broken_by_sku_consistently(self):
        # Two items with identical price and availability must still order
        # deterministically.
        products = [product("ZZZ"), product("AAA")]
        f = {"ZZZ": facts("ZZZ", "100.00"), "AAA": facts("AAA", "100.00")}
        result = search(Criteria(size_code="A4"), products, f)
        assert [c.sku for c in result.matches] == ["AAA", "ZZZ"]

    def test_available_before_unavailable(self):
        result = run(Criteria(category="Coloured paper"))
        # IVY is out of stock, so it must not be offered as a match.
        assert all(c.available for c in result.matches)
        assert "PL-CL-A4-100-IVY" in {c.sku for c in result.unavailable}

    def test_ranking_order_constant_matches_implementation(self):
        # The documented chain and the sort key must not drift apart.
        assert RANKING_ORDER == ("availability_penalty", "budget_margin", "sku")
        candidate_a = Candidate(
            sku="A", name="a", product=product("A"), facts=FACTS["PL-CP-A5-80"],
            match_reasons=(), unit_price=b("10.00"), line_total=b("10.00"),
            quantity=1, tier_applied=None, available=True,
            stock_status="in_stock", back_in_stock_date=None,
        )
        candidate_b = Candidate(
            sku="B", name="b", product=product("B"), facts=FACTS["PL-CP-A5-80"],
            match_reasons=(), unit_price=b("20.00"), line_total=b("20.00"),
            quantity=1, tier_applied=None, available=True,
            stock_status="in_stock", back_in_stock_date=None,
        )
        from paperlane.search import _rank_key
        assert sorted([candidate_b, candidate_a], key=_rank_key) == [
            candidate_a, candidate_b
        ]


# ---------------------------------------------------------------------------
# 4.6 Justification
# ---------------------------------------------------------------------------


class TestJustification:
    def test_one_reason_per_satisfied_requirement(self):
        result = run(Criteria(size_code="A4", weight_gsm=80, colour_name="white"))
        match = next(c for c in result.matches if c.sku == "PL-CP-A4-80")
        attributes = {r.attribute for r in match.match_reasons}
        assert attributes == {"size", "weight", "colour (paper shade)"}

    def test_reason_names_requested_and_actual(self):
        result = run(Criteria(size_code="A5"))
        match = result.matches[0]
        reason = match.match_reasons[0]
        assert reason.requested == "A5"
        assert reason.actual == "A5"

    def test_budget_reason_records_quantity_and_tier(self):
        result = run(Criteria(size_code="LTR", budget_per_unit=b("250.00")), quantity=20)
        match = next(c for c in result.matches if c.sku == "PL-PR-LTR-GL-130-40")
        budget_reason = next(
            r for r in match.match_reasons if r.attribute == "budget per unit"
        )
        assert "quantity 20" in budget_reason.detail
        assert "20+ tier" in budget_reason.detail
        assert budget_reason.actual == "233.20"

    def test_justification_is_serialisable(self):
        result = run(Criteria(size_code="A5"))
        payload = result.matches[0].as_dict()
        assert payload["match_reasons"][0]["attribute"] == "size"
        assert isinstance(payload["match_reasons"], list)

    def test_justification_needs_no_model(self):
        # search() has no model client; a full justification is produced from
        # catalog data and the request alone.
        result = run(Criteria(size_code="A5"))
        assert result.matches[0].match_reasons


# ---------------------------------------------------------------------------
# 4.7 Unavailable items
# ---------------------------------------------------------------------------


class TestUnavailable:
    def test_out_of_stock_is_marked_not_offered(self):
        result = run(Criteria(colour_name="ivory"))
        assert result.matches == ()
        assert len(result.unavailable) == 1
        item = result.unavailable[0]
        assert item.stock_status == "out_of_stock"
        assert item.back_in_stock_date == "20 November 2026"

    def test_unavailable_carries_its_date(self):
        result = run(Criteria(colour_name="ivory"))
        assert result.unavailable[0].back_in_stock_date == "20 November 2026"

    def test_available_and_unavailable_are_separated(self):
        result = run(Criteria(category="Coloured paper"))
        assert {c.sku for c in result.matches} == {"PL-CL-A4-80-PBL"}
        assert {c.sku for c in result.unavailable} == {"PL-CL-A4-100-IVY"}


# ---------------------------------------------------------------------------
# 4.8 No match and relaxation
# ---------------------------------------------------------------------------


class TestNoMatch:
    def test_genuinely_unmatched_is_reported_as_no_match(self):
        # A5 at 200 gsm exists nowhere.
        result = run(Criteria(size_code="A5", weight_gsm=200))
        assert result.matches == ()

    def test_no_match_offers_labelled_alternatives(self):
        result = run(Criteria(size_code="A5", weight_gsm=200))
        assert result.alternatives
        assert result.relaxed is not None

    def test_alternative_names_the_relaxed_requirement(self):
        result = run(Criteria(size_code="A5", weight_gsm=200))
        assert result.relaxed in ("weight", "size")

    def test_budget_is_relaxed_first(self):
        # Nothing at A4 80gsm under 60.00; the budget is the thing to drop.
        result = run(Criteria(size_code="A4", weight_gsm=80,
                              budget_per_unit=b("60.00")))
        assert result.matches == ()
        assert result.relaxed == "budget"
        assert result.alternatives

    def test_alternatives_are_clearly_separate_from_matches(self):
        result = run(Criteria(size_code="A5", weight_gsm=200))
        assert result.matches == ()
        assert result.alternatives != ()
        assert result.is_match is False

    def test_a_match_never_also_appears_as_an_alternative(self):
        result = run(Criteria(size_code="A4"))
        assert result.matches
        assert result.alternatives == ()


# ---------------------------------------------------------------------------
# Budget at the requested quantity (the central trap)
# ---------------------------------------------------------------------------


class TestBudgetAtQuantity:
    def test_budget_met_at_20_packs(self):
        result = run(Criteria(size_code="LTR", budget_per_unit=b("250.00")), quantity=20)
        assert "PL-PR-LTR-GL-130-40" in {c.sku for c in result.matches}

    def test_same_budget_fails_at_1_pack(self):
        result = run(Criteria(size_code="LTR", budget_per_unit=b("250.00")), quantity=1)
        # 265.00 > 250.00 at qty 1, so it is not a match at that quantity.
        assert "PL-PR-LTR-GL-130-40" not in {c.sku for c in result.matches}

    def test_list_price_comparison_would_get_the_brief_example_wrong(self):
        # The naive filter compares 265.00 with 250.00 and finds nothing.
        naive = FACTS["PL-PR-LTR-GL-130-40"].list_price <= b("250.00")
        correct = "PL-PR-LTR-GL-130-40" in {
            c.sku for c in run(
                Criteria(size_code="LTR", budget_per_unit=b("250.00")),
                quantity=20,
            ).matches
        }
        assert naive is False
        assert correct is True

    def test_inclusive_boundary(self):
        result = run(Criteria(size_code="A5", budget_per_unit=b("72.00")), quantity=1)
        assert "PL-CP-A5-80" in {c.sku for c in result.matches}

    def test_one_satang_over_is_excluded(self):
        result = run(Criteria(size_code="A5", budget_per_unit=b("71.99")), quantity=1)
        assert "PL-CP-A5-80" not in {c.sku for c in result.matches}

    def test_quantity_defaults_to_one(self):
        result = run(Criteria(size_code="A5"))
        assert result.matches[0].quantity == 1
