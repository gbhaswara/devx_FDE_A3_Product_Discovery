"""Assistant tests: four outcomes, guards, clarification rule.

The catalog here mirrors the real one's awkward cases: an out-of-stock item, a
sale item, a plain-paper product with no printing attributes, and flyers whose
only difference is print colour mode.
"""

from __future__ import annotations

import pytest

from paperlane.assistant import (
    MAX_QUESTIONS,
    OUTCOME_CLARIFIED,
    OUTCOME_NO_MATCH,
    OUTCOME_QUOTED,
    OUTCOME_REFUSED,
    answer,
    check_figures_match,
    check_no_internal_ids,
    check_no_invented_products,
    computed_amounts,
    decide_questions,
)
from paperlane.criteria import Criteria
from paperlane.interpret import (
    CriteriaInvalid,
    interpret_rules,
    merge_model_and_rules,
    parse_budget,
    parse_quantity,
    validate,
)
from paperlane.money import Money
from paperlane.pricing import PriceFacts, PriceTier


def b(s: str) -> Money:
    return Money.from_baht(s)


def row(sku, **overrides):
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
        "list_price_satang": 12900,
        "sale_price_satang": None,
    }
    base.update(overrides)
    return base


def facts(sku, list_price, tiers=(), sale=None):
    return PriceFacts(
        sku=sku,
        list_price=b(list_price),
        tiers=tuple(PriceTier(q, b(p)) for p, q in tiers),
        sale_price=b(sale) if sale else None,
    )


PRODUCTS = [
    row("PL-CP-A4-80", name="Lotus Bright Premium A4 80gsm"),
    row("PL-CP-A5-80", name="PaperLane Essentials A5 80gsm", size_code="A5",
        list_price_satang=7200),
    row("PL-CL-A4-100-IVY", name="Heritage Ivory A4 100gsm",
        category="Coloured paper", colour_name="ivory", weight_gsm=100,
        stock_status="out_of_stock", back_in_stock_date="20 November 2026",
        list_price_satang=16800),
    row("PL-PR-LTR-MT-100-40", name="Letter-size Flyers — 100 gsm, Single-sided, "
        "Full colour (CMYK)", category="Flyer printing", size_code="LTR",
        weight_gsm=100, colour_name=None, colour_mode="Full colour (CMYK)",
        sides="single", finish="Matte", pack_sheets=100,
        list_price_satang=22500),
    row("PL-PR-LTR-MT-100-10", name="Letter-size Flyers — 100 gsm, Single-sided, "
        "Black and white", category="Flyer printing", size_code="LTR",
        weight_gsm=100, colour_name=None, colour_mode="Black and white",
        sides="single", finish="Matte", pack_sheets=100,
        list_price_satang=12500),
]

FACTS = {
    "PL-CP-A4-80": facts("PL-CP-A4-80", "129.00",
                         [("122.55", 10), ("116.10", 50)]),
    "PL-CP-A5-80": facts("PL-CP-A5-80", "72.00", [("68.40", 10)]),
    "PL-CL-A4-100-IVY": facts("PL-CL-A4-100-IVY", "168.00"),
    "PL-PR-LTR-MT-100-40": facts("PL-PR-LTR-MT-100-40", "225.00",
                                 [("211.50", 5), ("198.00", 20)]),
    "PL-PR-LTR-MT-100-10": facts("PL-PR-LTR-MT-100-10", "125.00",
                                 [("117.50", 5), ("110.00", 20)]),
}

def ask(text: str):
    criteria = validate(interpret_rules(text))
    return answer(criteria, PRODUCTS, FACTS)


# ---------------------------------------------------------------------------
# 5.1 Criteria models and validation
# ---------------------------------------------------------------------------


class TestCriteriaValidation:
    def test_valid_request_becomes_criteria(self):
        c = interpret_rules("A4 copy paper 80 gsm, 20 reams")
        assert c.size_code == "A4"
        assert c.weight_gsm == 80
        assert c.quantity == 20

    def test_unstocked_size_is_rejected(self):
        c = Criteria(size_code="B5")
        with pytest.raises(CriteriaInvalid, match="not a size"):
            validate(c)

    def test_invalid_category_rejected(self):
        with pytest.raises(CriteriaInvalid, match="not a catalog category"):
            validate(Criteria(category="Tissue paper"))

    def test_invalid_sides_rejected(self):
        with pytest.raises(CriteriaInvalid, match="not a printing side"):
            validate(Criteria(sides="triple"))

    def test_implausible_quantity_rejected(self):
        with pytest.raises(CriteriaInvalid, match="implausibly large"):
            validate(Criteria(quantity=10_000_000))

    def test_zero_quantity_rejected(self):
        with pytest.raises(CriteriaInvalid, match="at least 1"):
            validate(Criteria(quantity=0))

    def test_implausible_weight_rejected(self):
        with pytest.raises(CriteriaInvalid, match="plausible grammage"):
            validate(Criteria(weight_gsm=50_000))

    def test_negative_budget_rejected(self):
        with pytest.raises(CriteriaInvalid, match="positive"):
            validate(Criteria(budget_per_unit=b("-1.00")))

    def test_invalid_interpretation_never_reaches_pricing(self):
        # A model-supplied size the catalog does not stock never reaches
        # pricing, by two mechanisms.
        # 1. It is dropped at the boundary rather than injected...
        injected = merge_model_and_rules({"size": "B5"}, interpret_rules("paper"))
        assert injected.size_code is None
        # ...but it is not silently lost: it becomes a question.
        reply = ask("B5 paper")
        assert reply.outcome == OUTCOME_CLARIFIED
        assert reply.quote is None
        assert any(q.field == "size" for q in reply.questions)
        assert reply.candidates == ()

        # 2. If a caller constructs invalid criteria directly, validate() raises
        #    before answer() is ever reached.
        with pytest.raises(CriteriaInvalid):
            validate(Criteria(size_code="B5"))


# ---------------------------------------------------------------------------
# 5.3 Rule-based interpretation
# ---------------------------------------------------------------------------


class TestRuleInterpretation:
    def test_the_briefs_example(self):
        c = interpret_rules(
            "We need letter-size flyers, one side, colour, under 250 a pack, 20 packs."
        )
        assert c.category == "Flyer printing"
        assert c.size_code == "LTR"
        assert c.sides == "single"
        assert c.colour_mode == "Full colour (CMYK)"
        assert c.budget_per_unit == b("250.00")
        assert c.quantity == 20

    def test_quantity_phrasings(self):
        for text, expected in [
            ("20 packs", 20),
            ("3 reams", 3),
            ("10 boxes", 10),
            ("qty 5", 5),
            ("5 x A4", 5),
        ]:
            assert parse_quantity(text) == expected

    def test_no_quantity(self):
        assert parse_quantity("A4 paper please") is None

    def test_budget_phrasings(self):
        for text, expected in [
            ("under 250 a pack", "250.00"),
            ("max 300", "300.00"),
            ("budget of 150", "150.00"),
            ("no more than 200", "200.00"),
            ("at most 99.50", "99.50"),
        ]:
            amount, _ = parse_budget(text)
            assert amount is not None and amount.format().replace(",", "") == expected

    def test_budget_basis_detected(self):
        _, basis = parse_budget("under 250 per ream")
        assert "ream" in basis

    def test_a_vat_qualifier_beats_the_unit_word(self):
        # BUG.md A20. "a pack including VAT" says *including*; the unit pattern
        # matched first and the reply stated the opposite assumption.
        _, basis = parse_budget("letter flyers, under 240 a pack including VAT, 20 packs")
        assert basis == "per pack, including VAT"

    def test_a_vat_qualifier_combines_with_the_unit_word(self):
        _, basis = parse_budget("under 60 per ream including VAT")
        assert basis == "per ream, including VAT"

    def test_an_exclusive_qualifier_stays_before_vat(self):
        _, basis = parse_budget("under 240 a pack excluding VAT")
        assert basis == "per pack, before VAT"

    def test_no_budget(self):
        assert parse_budget("A4 paper") == (None, "per pack, before VAT")

    def test_budget_and_quantity_are_independent(self):
        # The brief's example puts the budget before the quantity; neither may
        # swallow the other.
        c = interpret_rules("under 250 a pack, 20 packs")
        assert c.budget_per_unit == b("250.00")
        assert c.quantity == 20

    def test_two_products_do_not_merge_into_a_phantom(self):
        # BUG.md A29. "Gloss" belongs to the flyers clause; applying it to the
        # copy paper half produced a product in neither clause and answered
        # no_match for an item that is in stock at 121.50.
        c = interpret_rules("A4 80gsm copy paper and A4 gloss flyers")
        assert any(n.startswith("compound:") for n in c.notes), c.notes

    def test_a_second_item_is_never_dropped_silently(self):
        # The same parse quoted the copy paper and discarded the card without
        # a word, so the reply read as a complete answer.
        c = interpret_rules(
            "A4 80gsm copy paper, 20 packs, and 5 packs of A4 250gsm white card"
        )
        assert any(n.startswith("compound:") for n in c.notes), c.notes

    def test_one_product_with_several_clauses_is_not_compound(self):
        # The guard must not fire on a request that merely states its
        # requirements in separate clauses.
        for text in [
            "A4 80gsm copy paper, 20 packs, under 250 a pack",
            "letter-size flyers, one side, colour, under 250 a pack, 20 packs",
            "A4 80gsm and 90gsm copy paper",
        ]:
            c = interpret_rules(text)
            assert not any(n.startswith("compound:") for n in c.notes), text


class TestModelMerge:
    def test_model_values_win_where_present(self):
        rules = interpret_rules("A4 paper")
        merged = merge_model_and_rules({"weight_gsm": 100}, rules)
        assert merged.weight_gsm == 100

    def test_rules_fill_gaps(self):
        rules = interpret_rules("A4 paper")
        merged = merge_model_and_rules({}, rules)
        assert merged.size_code == "A4"

    def test_model_cannot_inject_an_invalid_size(self):
        rules = interpret_rules("paper")
        merged = merge_model_and_rules({"size": "B5"}, rules)
        # Dropped at the boundary: the catalog does not stock B5, so no
        # constraint is applied...
        assert merged.size_code is None
        # ...and the gap is recorded so the assistant asks about it.
        assert any(note.startswith("size:") for note in merged.notes)

    def test_model_size_vocabulary_is_re_resolved(self):
        # Measured: the live model returns "letter" and "flyers". Passing those
        # through verbatim produced size_code="LETTER", which failed validation
        # and discarded a correct interpretation.
        rules = interpret_rules("paper")
        merged = merge_model_and_rules(
            {"size": "letter", "category": "flyers"}, rules
        )
        assert merged.size_code == "LTR"
        assert merged.category == "Flyer printing"

    def test_model_side_phrasings_are_normalised(self):
        rules = interpret_rules("paper")
        for phrasing, expected in [
            ("one-sided", "single"), ("one side", "single"),
            ("double-sided", "double"), ("two sided", "double"),
        ]:
            merged = merge_model_and_rules({"sides": phrasing}, rules)
            assert merged.sides == expected, phrasing

    def test_bare_colour_from_the_model_is_ambiguity_not_a_value(self):
        # The live model returns {"colour": "colour"} — it is echoing the word,
        # not naming a shade. That must become a question, not a filter.
        rules = interpret_rules("paper")
        merged = merge_model_and_rules({"colour": "colour"}, rules)
        assert merged.colour_name is None
        assert merged.colour_mode is None
        assert merged.colour_ambiguous is True

    def test_model_budget_becomes_money(self):
        rules = interpret_rules("A4 paper")
        merged = merge_model_and_rules({"budget_per_unit": "250.00"}, rules)
        assert merged.budget_per_unit == b("250.00")

    def test_model_cannot_smuggle_a_price_into_criteria(self):
        # Only allow-listed keys are taken; a price or SKU has no field to land
        # in.
        rules = interpret_rules("A4 paper")
        merged = merge_model_and_rules(
            {"unit_price": "1.00", "sku": "PL-FAKE-1", "total": 0}, rules
        )
        assert not hasattr(merged, "unit_price")
        assert "PL-FAKE-1" not in str(merged.describe())


# ---------------------------------------------------------------------------
# 5.4 Fallback and disclosure
# ---------------------------------------------------------------------------


class TestInterpretationDisclosure:
    def test_rule_based_is_reported(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert reply.interpretation == "rules"

    def test_reply_is_usable_with_no_model_configured(self):
        # Nothing here touches the network; the whole path is local.
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert reply.outcome == OUTCOME_QUOTED

    def test_nothing_understood_asks_a_question(self):
        reply = ask("hello there")
        assert reply.outcome == OUTCOME_CLARIFIED
        assert reply.questions


# ---------------------------------------------------------------------------
# 5.5 Reply contract
# ---------------------------------------------------------------------------


class TestReplyContract:
    def test_reply_states_why_each_product_matches(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert "Matches" in reply.text
        assert reply.candidates[0].match_reasons

    def test_reply_contains_a_complete_breakdown(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        for label in ("Subtotal", "Delivery", "VAT", "Total"):
            assert label in reply.text

    def test_breakdown_identifies_the_discount(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert "10+ tier" in reply.text
        assert "list 129.00" in reply.text

    def test_breakdown_states_the_unit_price_and_quantity(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        payload = reply.as_dict()
        line = payload["breakdown"]["lines"][0]
        assert line["quantity"] == 20
        assert line["unit_price"] == "122.55"

    def test_a_cheaper_larger_quantity_is_named(self):
        # BUG.md A30. 19 packs of this flyer pay the 5+ price (211.50); 20 packs
        # reach the 20+ tier (198.00) and cost less in total. Withholding that
        # invites the customer to discover it themselves.
        reply = ask("letter-size matte flyers 100gsm single sided full colour, "
                    "19 packs")
        assert reply.outcome == OUTCOME_QUOTED
        assert "20 packs would come to 4,237.20" in reply.text

    def test_no_hint_when_the_larger_quantity_costs_more(self):
        # 6 packs is past the 5+ tier; the next tier is 20 packs, which costs
        # more. Nothing to point out, so nothing is said.
        reply = ask("letter-size matte flyers 100gsm single sided full colour, "
                    "6 packs")
        assert reply.outcome == OUTCOME_QUOTED
        assert "would come to" not in reply.text

    def test_no_hint_when_no_larger_tier_exists(self):
        # 20 packs is already the top tier.
        reply = ask("letter-size matte flyers 100gsm single sided full colour, "
                    "20 packs")
        assert reply.outcome == OUTCOME_QUOTED
        assert "would come to" not in reply.text

    def test_a_charged_delivery_states_the_threshold(self):
        # BUG.md A27. The threshold was named only in the branch where delivery
        # was already free — published to the customer it costs nothing and
        # withheld from the one paying 150.00.
        reply = ask("A5 paper, 3 reams")
        assert reply.outcome == OUTCOME_QUOTED
        assert reply.quote.delivery.satang > 0
        assert "free from 3,000.00" in reply.text

    def test_the_free_delivery_shortfall_is_exact(self):
        # Recomputed from the quote, not from the reply: what is asserted is the
        # relation between the two, so a wrong constant cannot be transcribed
        # into the test.
        from paperlane.pricing import FREE_DELIVERY_THRESHOLD

        reply = ask("A5 paper, 3 reams")
        shortfall = FREE_DELIVERY_THRESHOLD - reply.quote.subtotal
        assert shortfall.satang > 0
        assert f"{shortfall.format()} more" in reply.text

    def test_a_free_delivery_order_does_not_state_a_shortfall(self):
        # The mirror guard: nothing to add up to when delivery is already free.
        reply = ask("A4 copy paper 80 gsm, 50 reams")
        assert reply.quote.delivery.satang == 0
        assert "more)" not in reply.text

    def test_list_price_case_identified_as_list(self):
        reply = ask("A5 paper")
        assert "list price" in reply.text

    def test_sale_price_case_identified(self):
        products = PRODUCTS + [row(
            "PL-PR-LTR-GL-170-40", name="Sale flyer", category="Flyer printing",
            size_code="LTR", colour_mode="Full colour (CMYK)", sides="single",
            list_price_satang=29900, sale_price_satang=25900,
        )]
        f = dict(FACTS)
        f["PL-PR-LTR-GL-170-40"] = facts(
            "PL-PR-LTR-GL-170-40", "299.00", sale="259.00"
        )
        criteria = validate(interpret_rules("letter flyers full colour single sided"))
        reply = answer(criteria, products, f)
        # The sale item is cheapest, so it should win and be identified.
        assert reply.outcome == OUTCOME_QUOTED
        assert "sale" in reply.text.lower()


# ---------------------------------------------------------------------------
# 5.6 Clarification rule
# ---------------------------------------------------------------------------


class TestClarification:
    def test_missing_quantity_asked_when_it_changes_the_price(self):
        # A budget with no quantity, where the tier genuinely decides whether
        # anything qualifies: 225.00 at qty 1 fails "under 220", but the 5+ tier
        # at 211.50 passes. The qualifying set differs by quantity, so the
        # question is worth asking.
        #
        # No `product_tiers` argument is passed: the tiers must be derived from
        # the price facts, which is the only path the API uses. Supplying them
        # separately is what let this branch be dead in production while the
        # test passed.
        criteria = validate(interpret_rules(
            "letter flyers full colour single sided under 220 a pack"
        ))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert reply.outcome == OUTCOME_CLARIFIED
        assert any(q.field == "quantity" for q in reply.questions)

    def test_quantity_not_asked_when_every_quantity_qualifies(self):
        # The mirror case, and the one that keeps the question honest: if the
        # budget is met at qty 1 and at every tier, the answer is identical
        # whatever the quantity, so asking is noise.
        criteria = validate(interpret_rules(
            "letter flyers full colour single sided under 250 a pack"
        ))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert not any(q.field == "quantity" for q in reply.questions)

    def test_quantity_not_asked_when_no_budget(self):
        # Without a budget, quantity 1 is a fine default.
        criteria = validate(interpret_rules("A4 copy paper 80 gsm"))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert not any(q.field == "quantity" for q in reply.questions)

    def test_quantity_not_asked_when_no_tier_could_help(self):
        # Budget far above any price: quantity cannot change the verdict.
        criteria = validate(interpret_rules("A4 copy paper 80 gsm under 9999 a pack"))
        questions = decide_questions(criteria, PRODUCTS)
        assert not any(q.field == "quantity" for q in questions)

    def test_a_compound_request_asks_which_item_first(self):
        # BUG.md A29. Two products in one request: asking is the only honest
        # answer, because a single-item quote silently covers half of it.
        criteria = validate(interpret_rules("A4 copy paper and A4 card"))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert reply.outcome == OUTCOME_CLARIFIED
        assert any(q.field == "compound" for q in reply.questions)

    def test_a_compound_clarification_does_not_restate_the_merged_reading(self):
        # The criteria behind this question are the merged reading of two
        # products; printing them back would assert the phantom the question
        # exists to avoid — here "Gloss" taken from the flyers half.
        criteria = validate(interpret_rules("A4 80gsm copy paper and A4 gloss flyers"))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert "Gloss" not in reply.text
        assert "So far I have" not in reply.text

    def test_ambiguous_colour_is_asked(self):
        # "colour" with no noun that settles it is a genuine question.
        criteria = validate(interpret_rules("I need colour"))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert reply.outcome == OUTCOME_CLARIFIED
        assert any(q.field == "colour" for q in reply.questions)

    def test_colour_paper_does_not_re_ask_what_the_words_settled(self):
        # "colour paper" names the product class, so the word "colour" can only
        # mean paper shade. Asking "did you mean paper colour or print colour?"
        # would re-ask what the customer's own words answered — and the four
        # conditions for asking (needed, absent, uninferable, answer-changing)
        # are not all met, because every match is a coloured paper either way.
        #
        # This is the analysis document's case 25: "colour paper A4" must read
        # colour as a *paper shade*, never as a print mode.
        criteria = validate(interpret_rules("colour paper A4"))
        assert criteria.category == "Coloured paper"
        assert criteria.colour_mode is None        # not CMYK
        assert criteria.colour_name is None        # no shade named yet

        # Driven against the real catalog: the local fixture holds a single
        # coloured-paper SKU, which cannot show that the *set* of coloured papers
        # comes back.
        from paperlane import catalog as store

        reply = answer(criteria, store.load_products(), store.load_price_facts())
        assert reply.outcome == OUTCOME_QUOTED
        assert not any(q.field == "colour" for q in reply.questions)
        assert reply.candidates
        assert all(c.sku.startswith("PL-CL-") for c in reply.candidates)

    def test_at_most_two_questions(self):
        criteria = Criteria(colour_ambiguous=True, budget_per_unit=b("250.00"))
        questions = decide_questions(criteria, PRODUCTS)
        assert len(questions) <= MAX_QUESTIONS

    def test_questions_name_the_detail(self):
        # Same discriminating budget as above: the tier flips the verdict.
        criteria = validate(interpret_rules(
            "letter flyers under 220 a pack"
        ))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert "quantity" in reply.text.lower() or "how many" in reply.text.lower()

    def test_clarification_does_not_price(self):
        criteria = validate(interpret_rules("I need colour paper"))
        reply = answer(criteria, PRODUCTS, FACTS)
        assert reply.quote is None


# ---------------------------------------------------------------------------
# 5.7 Refusals
# ---------------------------------------------------------------------------


class TestRefusal:
    def test_out_of_stock_refused_with_restock_date(self):
        reply = ask("ivory A4 paper")
        assert reply.outcome == OUTCOME_REFUSED
        assert "out of stock" in reply.text.lower()
        assert "20 November 2026" in reply.text
        assert reply.quote is None

    def test_out_of_stock_not_quoted_as_purchasable(self):
        reply = ask("ivory A4 paper")
        assert reply.quote is None
        assert "I cannot quote it as a purchase" in reply.text

    def test_discontinued_refused_distinctly(self):
        products = [row("PL-CL-A4-100-IVY", name="Heritage Ivory A4 100gsm",
                        category="Coloured paper", colour_name="ivory",
                        stock_status="discontinued")]
        criteria = validate(interpret_rules("ivory paper"))
        reply = answer(criteria, products, FACTS)
        assert reply.outcome == OUTCOME_REFUSED
        assert "discontinued" in reply.text.lower()
        # Distinct from a temporary shortage.
        assert "out of stock" not in reply.text.lower()


# ---------------------------------------------------------------------------
# 5.8 No invented products
# ---------------------------------------------------------------------------


class TestNoInventedProducts:
    def test_known_sku_is_kept(self):
        text, errors = check_no_invented_products(
            "Lotus Bright (PL-CP-A4-80) costs 129.00", {"PL-CP-A4-80"}
        )
        assert "PL-CP-A4-80" in text
        assert errors == []

    def test_unknown_sku_is_removed_and_reported(self):
        text, errors = check_no_invented_products(
            "Magic Paper (PL-XX-A4-999) costs 1.00", {"PL-CP-A4-80"}
        )
        assert "PL-XX-A4-999" not in text
        assert errors
        assert "not in the current snapshot" in errors[0]

    def test_reply_from_real_path_has_no_invented_products(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert reply.errors == ()


# ---------------------------------------------------------------------------
# 5.9 Stated figures match computed figures
# ---------------------------------------------------------------------------


class TestFigureAgreement:
    def test_matching_amounts_pass(self):
        _, errors = check_figures_match("Total 1,471.79", {"1,471.79"})
        assert errors == []

    def test_mismatched_amount_is_detected(self):
        _, errors = check_figures_match("Total 9,999.99", {"1,471.79"})
        assert errors
        assert "9,999.99" in errors[0]

    def test_real_reply_has_no_discrepancies(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert reply.errors == ()

    def test_stated_total_equals_computed_total(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert reply.quote is not None
        assert reply.quote.total.format() in reply.text

    def test_computed_amounts_includes_every_component(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        amounts = computed_amounts(reply.quote)
        for value in (
            reply.quote.subtotal.format(),
            reply.quote.delivery.format(),
            reply.quote.vat.format(),
            reply.quote.total.format(),
        ):
            assert value in amounts


# ---------------------------------------------------------------------------
# 5.10 Usable by a salesperson
# ---------------------------------------------------------------------------


class TestUsability:
    def test_product_named_as_the_catalog_names_it(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert "Lotus Bright Premium A4 80gsm" in reply.text

    def test_identifier_is_not_the_description(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        _, warnings = check_no_internal_ids(
            reply.text, [c.sku for c in reply.candidates]
        )
        assert warnings == []

    def test_bare_sku_is_flagged(self):
        _, warnings = check_no_internal_ids("PL-CP-A4-80", ["PL-CP-A4-80"])
        assert warnings

    def test_unit_matches_the_product(self):
        reply = ask("A5 paper")
        # A5 copy is sold as a pack of 500 sheets.
        assert "pack of 500 sheets" in reply.text

    def test_flyer_unit_is_a_pack_of_100(self):
        reply = ask("letter flyers black and white single sided")
        assert "pack of 100 sheets" in reply.text

    def test_no_raw_json_in_the_reply(self):
        reply = ask("A4 copy paper 80 gsm, 20 reams")
        assert "{" not in reply.text
        assert "None" not in reply.text


# ---------------------------------------------------------------------------
# 5.3 outcome enum coverage
# ---------------------------------------------------------------------------


class TestFourOutcomes:
    def test_quoted(self):
        assert ask("A4 copy paper 80 gsm, 20 reams").outcome == OUTCOME_QUOTED

    def test_clarified(self):
        assert ask("hello").outcome == OUTCOME_CLARIFIED

    def test_refused(self):
        assert ask("ivory A4 paper").outcome == OUTCOME_REFUSED

    def test_no_match(self):
        # 400 gsm exists nowhere.
        assert ask("paper 400 gsm").outcome == OUTCOME_NO_MATCH

    def test_each_outcome_has_its_required_fields(self):
        quoted = ask("A4 copy paper 80 gsm, 20 reams")
        assert quoted.quote is not None and quoted.candidates

        clarified = ask("hello")
        assert clarified.questions and clarified.quote is None

        refused = ask("ivory A4 paper")
        assert refused.refused and refused.quote is None

        no_match = ask("paper 400 gsm")
        assert no_match.quote is None and no_match.candidates == ()


class TestNoMatch:
    """BUG.md A28: "nothing close" must be true when it is said.

    Runs over the real snapshot, because the defect is in its contents: the only
    A4 ivory sheet in the catalog is out of stock until 20 November 2026.
    """

    def reply(self, request: str):
        from paperlane import catalog

        if not catalog.snapshot_exists():
            pytest.skip("no committed catalog snapshot")
        return answer(
            validate(interpret_rules(request)),
            catalog.load_products(),
            catalog.load_price_facts(),
        )

    def test_the_near_match_carries_its_restock_date(self):
        reply = self.reply("A4 120gsm ivory paper 4 packs")
        assert reply.outcome == OUTCOME_NO_MATCH
        assert "PL-CL-A4-100-IVY" in reply.text
        assert "20 November 2026" in reply.text

    def test_the_false_claim_is_not_made(self):
        # The sentence is a factual claim about the assortment; when an item is
        # close but unorderable, saying nothing is close is false.
        reply = self.reply("A4 120gsm ivory paper 4 packs")
        assert "could not find anything close" not in reply.text


class TestModelMergeDoesNotRetractSettledColour:
    """The model may add information; it must not un-settle what the rules read.

    Found by running the evaluation set against the live endpoint. For
    "letter-size flyers, one side, colour, under 250 a pack, 20 packs" the model
    returns ``{"colour": "colour"}`` — a bare colour, which on its own is the
    ambiguous case. But the rules have already read "flyers ... colour" as print
    colour and set ``colour_mode``. The merge consulted only the model's payload
    (which carries no ``colour_mode``), re-opened the ambiguity, and the
    assistant asked "paper colour or print colour?" about a request that had
    answered it. Three of the twenty-eight evaluation cases degraded to
    clarification this way, and only the live run showed it: a stub returning
    tidy payloads never triggers it.
    """

    def test_a_bare_model_colour_does_not_undo_a_settled_print_mode(self):
        rules = interpret_rules("letter-size flyers, one side, colour, 20 packs")
        assert rules.colour_mode == "Full colour (CMYK)"
        merged = merge_model_and_rules({"colour": "colour"}, rules)
        assert merged.colour_ambiguous is False
        assert merged.colour_mode == "Full colour (CMYK)"

    def test_the_final_flag_is_normalised_against_settled_criteria(self):
        # Whichever path settled the colour, the flag must agree with it.
        rules = interpret_rules("A4 paper")
        merged = merge_model_and_rules(
            {"colour": "colour", "colour_mode": "CMYK"}, rules
        )
        assert merged.colour_mode == "Full colour (CMYK)"
        assert merged.colour_ambiguous is False

    def test_genuine_ambiguity_is_still_reported(self):
        # The guard must not have been defeated: "I need colour" names neither a
        # paper nor a print job, so the question is still owed.
        rules = interpret_rules("I need colour")
        assert rules.colour_ambiguous is True
        merged = merge_model_and_rules({"colour": "colour"}, rules)
        assert merged.colour_ambiguous is True
