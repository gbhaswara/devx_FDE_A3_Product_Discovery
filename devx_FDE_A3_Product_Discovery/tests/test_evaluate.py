"""The evaluation harness's own tests.

Two obligations here, and the second matters more than the first:

1. the recorded set runs and its expectations hold;
2. **the harness can fail.** A scoring scheme that reports a clean sweep is worth
   nothing until it is shown to detect the defects it claims to detect — and to
   attribute each defect to the right axis. Half of this file is deliberately
   corrupted results, asserting that the intended axis notices and the others do
   not.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from paperlane import catalog, cli
from paperlane.evaluate import (
    AXES,
    FAIL,
    NA,
    PASS,
    V1,
    V2,
    Case,
    CaseResult,
    _load_facts,
    _result_dict,
    _score_interpretation,
    _score_pricing,
    _score_reply,
    _score_retrieval,
    load_cases,
    recompute_totals,
    reset_cache,
    run_case,
    run_eval,
    self_check,
)
from paperlane.model import ModelClient, ModelConfig, ModelResult
from paperlane.pricing import LineRequest, quote


@pytest.fixture(scope="module")
def products():
    return catalog.load_products()


@pytest.fixture(scope="module")
def facts():
    return catalog.load_price_facts()


@pytest.fixture(scope="module")
def cases():
    return {case.number: case for case in load_cases()}


# ---------------------------------------------------------------------------
# 8.1 The recorded set exists and its totals are computed, not transcribed
# ---------------------------------------------------------------------------


class TestRecordedSet:
    def test_the_set_has_at_least_ten_cases(self, cases):
        # The brief's own floor.
        assert len(cases) >= 10

    def test_every_runnable_case_has_an_expected_outcome(self, cases):
        for case in cases.values():
            assert case.expect_outcome, case.number
            assert case.request.strip(), case.number
            assert case.proves.strip(), case.number

    def test_the_case_file_contains_no_transcribed_totals(self):
        """Expected totals must be computed, not written down.

        This is the whole point of the arithmetic being independent: a
        transcribed number is a guess that happens to be recorded, and it cannot
        detect a catalog change. So the file may name SKUs and quantities, and
        must not contain an expected total anywhere.
        """
        raw = json.loads(
            (Path(__file__).resolve().parents[1] / "eval" / "cases.json").read_text()
        )
        for entry in raw["cases"]:
            expect = entry.get("expect", {})
            assert "total" not in expect, entry["number"]
            assert "subtotal" not in expect, entry["number"]
            assert "vat" not in expect, entry["number"]
            # And no totals buried in the notes.
            assert "total:" not in entry.get("note", "").lower(), entry["number"]

    def test_expected_totals_are_recomputed_from_catalog_data(self, cases, facts):
        """Every priced case's expectation matches independent arithmetic."""
        for case in cases.values():
            if not case.expect_lines:
                continue
            expected = case.expected_figures()
            assert expected is not None
            # And it must equal what the *engine* produces, computed separately
            # here so the two paths are compared rather than assumed equal.
            engine = quote([
                LineRequest(line["sku"], int(line["quantity"]), facts[line["sku"]])
                for line in case.expect_lines
            ])
            assert expected["subtotal"] == engine.subtotal.format(), case.number
            assert expected["delivery"] == engine.delivery.format(), case.number
            assert expected["vat"] == engine.vat.format(), case.number
            assert expected["total"] == engine.total.format(), case.number

    def test_independent_arithmetic_agrees_with_the_engine(self, facts):
        # The check that makes the whole approach meaningful: two
        # implementations of PR2-PR5, written separately, must agree.
        baskets = [
            [{"sku": "PL-CP-A5-80", "quantity": 1}],
            [{"sku": "PL-CP-A4-80-NUSA", "quantity": 10}],
            [{"sku": "PL-CP-A4-80-NUSA", "quantity": 50}],
            [{"sku": "PL-PR-LTR-GL-170-40", "quantity": 20}],
            [{"sku": "PL-CP-A4-80", "quantity": 20},
             {"sku": "PL-PR-A4-MT-100-10", "quantity": 5}],
            [{"sku": "PL-CP-A4-80-ECO", "quantity": 25}],
        ]
        for lines in baskets:
            mine = recompute_totals(lines)
            engine = quote([
                LineRequest(line["sku"], line["quantity"], facts[line["sku"]])
                for line in lines
            ])
            assert mine["total"] == engine.total.format(), lines
            assert mine["delivery"] == engine.delivery.format(), lines
            assert mine["vat"] == engine.vat.format(), lines

    def test_recompute_does_not_call_the_pricing_engine(self):
        """The second opinion must be independent, not a wrapper.

        If ``recompute_totals`` delegated to ``quote``, a pricing bug would agree
        with itself and the harness would report a clean sweep forever. Checked
        by source inspection, which is crude but exactly the property wanted.
        """
        import inspect

        source = inspect.getsource(recompute_totals)
        assert "quote(" not in source
        assert "unit_price(" not in source

    def test_a_sale_price_is_not_combined_with_a_tier(self, facts):
        # PR3: the sale price replaces both list and tiers.
        mine = recompute_totals([{"sku": "PL-PR-LTR-GL-170-40", "quantity": 20}])
        assert mine["lines"][0]["unit_price"] == "259.00"
        assert "sale" in mine["lines"][0]["discount"]

    def test_the_delivery_threshold_boundary_is_exact(self, facts):
        # 25 x 120.00 = 3000.00 exactly: free delivery, not charged. An
        # off-by-one on the comparison shows up here and nowhere else.
        mine = recompute_totals([{"sku": "PL-CP-A4-80-ECO", "quantity": 25}])
        assert mine["subtotal"] == "3,000.00"
        assert mine["delivery"] == "0.00"

    def test_vat_is_rounded_half_up_once(self, facts):
        # 7% of (72.00 + 150.00) = 15.54 exactly; of 222.00 the half-up and
        # half-even results agree, so the case is about the base, not the
        # rounding mode. The base is the point: VAT is on goods *plus* delivery.
        mine = recompute_totals([{"sku": "PL-CP-A5-80", "quantity": 1}])
        assert mine["vat"] == "15.54"
        assert mine["total"] == "237.54"


# ---------------------------------------------------------------------------
# 8.2 Coverage of the required behaviours
# ---------------------------------------------------------------------------


class TestCoverage:
    """Each difficult behaviour the spec names must have at least one case.

    Coverage is read from a declared ``behaviour`` tag on each case, not grepped
    out of the prose. A keyword search over free text can pass on a case that
    says the right word while testing something else, which is exactly the
    failure mode a coverage check exists to prevent.

    **What this does not do.** The structural rules below only constrain tags
    that imply a shape. A tag with no structural implication — "synonym and
    notation handling", "filter semantics for inapplicable attributes" — is
    accepted on any case. Two mistaggings survived this check while the set was
    being written and were caught by reading the coverage table, not by the
    test. The test is a partial guard; review is still required.
    """

    #: The behaviours the evaluation-harness spec names, verbatim.
    REQUIRED = (
        "budget-dependent quantity",
        "sale precedence",
        "unavailable items",
        "no-match",
        "clarification",
        "small-order delivery and tax",
        "multi-item orders",
        "synonym and notation handling",
        "filter semantics for inapplicable attributes",
    )

    def test_every_required_behaviour_has_at_least_one_case(self, cases):
        covered = {tag for case in cases.values() for tag in case.behaviour}
        missing = [b for b in self.REQUIRED if b not in covered]
        assert not missing, f"no case covers: {missing}"

    def test_no_case_declares_an_unknown_behaviour(self, cases):
        # Keeps the vocabulary closed: a typo'd tag would silently stop counting
        # as coverage for the behaviour it was meant to name.
        known = set(self.REQUIRED) | {
            "tier boundary",
            "extraction shape",
            "per-sku tiers",
            "untrusted input handling",
        }
        for case in cases.values():
            for tag in case.behaviour:
                assert tag in known, f"case {case.number} declares {tag!r}"

    def test_coverage_is_declared_on_cases_that_actually_prove_it(self, cases, facts):
        """A declared behaviour must be structurally visible in the case.

        Not a keyword search over the prose — that is the weakness this test
        replaced. Each behaviour implies a shape, and the shape is checked
        against the case's own data: a case claiming "clarification" must expect
        a clarification, one claiming "small-order delivery" must have an
        expected delivery charge, and so on. If the tag and the shape disagree,
        the coverage claim is wrong.
        """
        def expected_delivery(case):
            figures = case.expected_figures()
            return None if figures is None else figures["delivery"]

        for case in cases.values():
            for tag in case.behaviour:
                if tag == "clarification":
                    assert case.expect_outcome == "clarified", case.number
                    assert case.expect_questions, case.number
                elif tag == "no-match":
                    assert case.expect_outcome == "no_match", case.number
                elif tag == "unavailable items":
                    assert case.expect_outcome == "refused", case.number
                elif tag == "small-order delivery and tax":
                    delivery = expected_delivery(case)
                    assert delivery not in (None, "0.00"), (
                        f"case {case.number} claims delivery but expects "
                        f"delivery {delivery}"
                    )
                elif tag == "multi-item orders":
                    assert case.expect_outcome == "multi_line", case.number
                    assert len(case.expect_lines) >= 2, case.number
                elif tag == "sale precedence":
                    assert any(
                        facts[line["sku"]].on_sale for line in case.expect_lines
                    ), f"case {case.number} claims sale precedence but no line is on sale"
                elif tag == "tier boundary":
                    # The quantity must sit exactly on a tier boundary, or the
                    # case cannot be proving anything about one.
                    for line in case.expect_lines:
                        tiers = facts[line["sku"]].tiers
                        assert any(
                            tier.min_qty == line["quantity"] for tier in tiers
                        ), f"case {case.number} qty {line['quantity']} is not a tier boundary"
                elif tag == "per-sku tiers":
                    # Every line must have a tier above the quantity it buys,
                    # or the case cannot show that a shared tier was not used.
                    for line in case.expect_lines:
                        tiers = facts[line["sku"]].tiers
                        assert tiers, f"case {case.number} {line['sku']} has no tiers"
                        assert all(
                            line["quantity"] < tier.min_qty
                            for tier in tiers
                            if tier.min_qty > line["quantity"]
                        ), f"case {case.number} {line['sku']} already meets its top tier"
                elif tag == "untrusted input handling":
                    # The case is only meaningful if it is marked not applicable
                    # on a catalog with no injected sample, or expects a refusal.
                    assert case.not_applicable or case.expect_outcome in (
                        "quoted", "refused"
                    ), case.number
                elif tag == "extraction shape":
                    # A shape case must produce a real quote from a real SKU.
                    assert case.expect_outcome == "quoted", case.number
                    assert case.expect_skus, case.number


# ---------------------------------------------------------------------------
# 8.3 / 8.4 Running and four-axis scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_every_axis_is_reported_for_a_runnable_case(self, cases, products,
                                                        facts):
        result = run_case(cases[4], products=products, facts=facts)
        assert set(result.axes) == set(AXES)
        for axis in AXES:
            assert result.axes[axis] in (PASS, FAIL, NA), axis

    def test_a_case_with_right_prices_but_wrong_products_fails_retrieval_only(
        self, cases, products, facts
    ):
        """The requirement, stated as a test.

        Case 25 (colour paper A4) is chosen because it is exactly this shape:
        seven coloured papers come back at a correct total. Reverse them and the
        best match is wrong — the price is still right, so only retrieval may
        move.
        """
        case = cases[25]
        good = run_case(case, products=products, facts=facts)
        assert good.verdict == "pass"

        bad = run_case(case, products=products, facts=facts)
        bad.actual_skus = tuple(reversed(bad.actual_skus))
        assert _score_retrieval(case, bad) == FAIL
        assert _score_pricing(case, bad) == PASS

    def test_a_wrong_total_fails_pricing_and_leaves_retrieval_alone(
        self, cases, products, facts
    ):
        case = cases[6]
        result = run_case(case, products=products, facts=facts)
        # VAT on the subtotal alone — the documented error.
        result.actual_figures["vat"] = "5.04"
        result.actual_figures["total"] = "227.04"
        assert _score_pricing(case, result) == FAIL
        assert _score_retrieval(case, result) == PASS

    def test_pricing_is_exact_to_the_satang(self, cases, products, facts):
        case = cases[6]
        result = run_case(case, products=products, facts=facts)
        # One satang out.
        result.actual_figures["total"] = "237.55"
        assert _score_pricing(case, result) == FAIL

    def test_a_missing_reply_fails_the_reply_axis(self, cases, products, facts):
        case = cases[4]
        result = run_case(case, products=products, facts=facts)
        result.reply_text = "   "
        assert _score_reply(case, result) == FAIL

    def test_a_reply_naming_an_absent_product_fails(self, cases, products, facts):
        case = cases[4]
        result = run_case(case, products=products, facts=facts)
        result.reply_text += "\nAlso: PL-NO-SUCH-1 at 10.00"
        assert _score_reply(case, result) == FAIL

    def test_a_non_quoted_outcome_carrying_a_total_fails_the_reply_axis(
        self, cases, products, facts
    ):
        case = cases[14]        # no_match
        result = run_case(case, products=products, facts=facts)
        result.reply_text += "\n  Total         999.00"
        assert _score_reply(case, result) == FAIL

    def test_per_line_delivery_is_caught_on_the_basket(self, cases, products, facts):
        """The bug that is invisible on every single-item case.

        Case 16's two lines are each below the 3000 threshold but together clear
        it. Charging delivery per line adds 150.00 per line instead of 0.00.
        """
        case = cases[16]
        result = run_case(case, products=products, facts=facts)
        assert result.verdict == "pass"

        wrong = recompute_totals(list(case.expect_lines))
        wrong["delivery"] = "300.00"
        result.actual_figures = wrong
        assert _score_pricing(case, result) == FAIL

    def test_tiers_are_not_aggregated_across_skus(self, cases, products, facts):
        """Case 27: 10 + 10 packs is not 20 packs of one thing."""
        case = cases[27]
        result = run_case(case, products=products, facts=facts)
        assert result.verdict == "pass"
        # If a 20+ tier had been applied across both SKUs, both unit prices
        # would be lower than the 5+ tier they actually earn.
        units = [line["unit_price"] for line in result.actual_figures["lines"]]
        assert units == ["202.10", "234.06"]


# ---------------------------------------------------------------------------
# 8.x The interpretation axis: a misread is not a mis-rank
# ---------------------------------------------------------------------------


class TestInterpretationAxis:
    """Validating criteria is not validating the reading of them.

    Every criterion can be typed, in range and drawn from a known vocabulary
    while the *set* of them is wrong — an A4 request read as A3 yields a valid,
    internally consistent quote for something nobody asked for. The four
    original axes cannot see that, which is why this one exists.
    """

    def test_it_is_a_first_class_axis(self):
        assert "interpretation" in AXES
        assert AXES[0] == "interpretation"

    def test_a_case_records_what_it_expects_and_what_it_forbids(self):
        cases = {c.number: c for c in load_cases()}
        # Case 1 is the brief's own example: "under 250 a pack" is a budget, not
        # a weight, and the case says so explicitly rather than by omission.
        one = cases[1]
        assert one.expect_criteria["quantity"] == 20
        assert "weight_gsm" in one.expect_absent_criteria

    def test_a_misread_derivation_fails(self, cases, products, facts):
        case = cases[1]
        result = run_case(case, products=products, facts=facts)
        assert result.axes["interpretation"] == PASS

        result.criteria = dict(result.criteria, size="A3")
        assert _score_interpretation(case, result) == FAIL
        assert "size" in result.notes[-1]

    def test_an_invented_requirement_fails(self, cases, products, facts):
        """The mirror defect: adding a constraint the request never stated."""
        case = cases[1]
        result = run_case(case, products=products, facts=facts)
        result.criteria = dict(result.criteria, weight_gsm=80)
        assert _score_interpretation(case, result) == FAIL

    def test_a_missing_expected_field_fails(self, cases, products, facts):
        case = cases[1]
        result = run_case(case, products=products, facts=facts)
        result.criteria = {k: v for k, v in result.criteria.items()
                           if k != "quantity"}
        assert _score_interpretation(case, result) == FAIL

    def test_a_case_with_no_recorded_criteria_is_not_applicable(
        self, cases, products, facts
    ):
        # Case 16 is a multi-line basket priced through a different endpoint; it
        # was not written to test interpretation, and calling that a pass would
        # inflate the axis.
        case = cases[16]
        result = run_case(case, products=products, facts=facts)
        assert _score_interpretation(case, result) == NA

    def test_a_corrupted_reading_does_not_move_the_other_axes(
        self, cases, products, facts
    ):
        """The property that makes the axis worth having.

        If corrupting the reading also failed retrieval, every misreading would
        be reported as a search failure — naming the symptom and hiding the
        cause, which is the one thing the separate-axes design exists to avoid.
        """
        case = cases[1]
        result = run_case(case, products=products, facts=facts)
        result.criteria = dict(result.criteria, size="A3")
        assert _score_interpretation(case, result) == FAIL
        assert _score_retrieval(case, result) == PASS
        assert _score_pricing(case, result) == PASS
        assert _score_reply(case, result) == PASS

    def test_the_expectation_is_a_declared_subset_not_the_engines_output(
        self, cases, products, facts
    ):
        """Guards the anti-pattern the design records.

        Recording `criteria.describe()` would be the engine agreeing with
        itself — the same defect `recompute_totals` avoids for money. A case's
        declared criteria must be smaller than what the engine derives, or the
        axis measures nothing.
        """
        for case in load_cases():
            if not case.expect_criteria:
                continue
            derived = run_case(case, products=products, facts=facts)
            if not derived.ran:
                # A case skipped on this catalog derives nothing, so there is
                # nothing for the declared set to be a subset of.
                continue
            # Either the declared subset is smaller than the derived criteria,
            # or the case declares fields the request must *not* produce — both
            # leave the axis able to disagree with the engine independently.
            independent = (
                len(case.expect_criteria) < len(derived.criteria)
                or bool(case.expect_absent_criteria)
            )
            assert independent, (
                f"case {case.number} records the engine's full output with "
                "nothing it must not read, so the interpretation axis cannot "
                "independently disagree with it"
            )


# ---------------------------------------------------------------------------
# 8.5 Retention of failures and not-applicable recording
# ---------------------------------------------------------------------------


class TestRetention:
    def test_a_case_with_absent_data_is_not_applicable_not_a_pass(self, cases,
                                                                 products, facts):
        for number in (21, 22, 23, 24):
            result = run_case(cases[number], products=products, facts=facts)
            assert result.verdict == "not run", number
            assert result.skipped_reason, number
            assert all(result.axes[axis] == NA for axis in AXES), number

    def test_a_not_applicable_case_still_appears_in_the_output(self):
        buffer = io.StringIO()
        run_eval(out=buffer)
        text = buffer.getvalue()
        for number in (21, 22, 23, 24):
            assert f"{number}" in text, number
        assert "not run" in text

    def test_a_failing_case_stays_in_the_results_with_its_cause(self, cases,
                                                               products, facts):
        """Failures are retained, with expected, actual and a note.

        Simulated rather than manufactured: a deliberately broken case is run
        through the same reporting path a real failure would take.
        """
        broken = Case(
            number=999,
            request="A4 copy paper, 80 gsm, 20 reams",
            proves="a deliberately failing case, to prove failures are retained",
            expect_outcome="quoted",
            expect_skus=("PL-DOES-NOT-EXIST",),
            expect_lines=({"sku": "PL-CP-A4-80-NUSA", "quantity": 20},),
        )
        result = run_case(broken, products=products, facts=facts)
        assert result.verdict == "fail"
        assert "retrieval" in result.failures

        # And it must be reported, not swallowed.
        buffer = io.StringIO()
        from paperlane.evaluate import _render_text, _result_dict, _summary

        payload = {
            "snapshot": {"path": "x", "products": 72, "price_tiers": 105},
            "model_available": False,
            "cases": [_result_dict(result)],
            "summary": _summary([result]),
            "strategies": [],
        }
        _render_text(payload, out=buffer)
        text = buffer.getvalue()
        assert "999" in text
        assert "PL-DOES-NOT-EXIST" in text
        assert "fail" in text

    def test_the_summary_counts_failures_rather_than_hiding_them(self, cases,
                                                                products, facts):
        broken = Case(
            number=999, request="A4 copy paper",
            proves="deliberate failure",
            expect_outcome="no_match",     # wrong on purpose
        )
        result = run_case(broken, products=products, facts=facts)
        from paperlane.evaluate import _summary

        summary = _summary([result])
        assert summary["failed"] == 1
        assert summary["failed_numbers"] == [999]


# ---------------------------------------------------------------------------
# 8.6 Interpretation-strategy comparison
# ---------------------------------------------------------------------------


class StubModel(ModelClient):
    """A stand-in that returns the *model's own* vocabulary.

    The live model was measured returning keys like ``gsm``, ``packs`` and
    ``product`` and values like ``letter`` and ``one-sided``. Using the same
    vocabulary here means the comparison exercises the translation layer rather
    than a tidy payload the real model never produces.
    """

    def __init__(self) -> None:
        super().__init__(ModelConfig(
            base_url="http://stub.invalid/v1", api_key="k", model="9inference",
        ))

    @property
    def available(self) -> bool:
        return True

    def extract_criteria(self, request_text: str) -> ModelResult:
        return ModelResult(
            criteria={"product": "A4 copy paper", "gsm": 80, "packs": 20},
            strategy="model",
        )


class TestStrategyComparison:
    def test_both_strategies_run_on_the_same_requests(self, cases):
        buffer = io.StringIO()
        run_eval(out=buffer, model_client=StubModel())
        text = buffer.getvalue()
        assert "Interpretation strategies" in text
        # The same case numbers appear in the comparison as in the run.
        assert "rules" in text and "model" in text

    def test_the_comparison_reports_outcomes_side_by_side(self):
        from paperlane.evaluate import _compare_strategies, load_cases as load

        rows = _compare_strategies(
            load(), catalog.load_products(), catalog.load_price_facts(),
            StubModel(),
        )
        assert rows
        for row in rows:
            assert "rules" in row and "model" in row
            assert row["rules"]["outcome"]
            assert row["model"]["outcome"]

    def test_without_a_model_the_comparison_says_so(self):
        buffer = io.StringIO()
        run_eval(out=buffer)
        text = buffer.getvalue()
        assert "No model was configured" in text
        # And it must not silently report agreement it never measured.
        assert "reached the same outcome" not in text

    def test_the_model_vocabulary_is_translated_not_trusted(self):
        """`packs`/`gsm`/`product` must reach the same place as the rules path."""
        from paperlane.evaluate import _compare_strategies, load_cases as load

        rows = _compare_strategies(
            load(), catalog.load_products(), catalog.load_price_facts(),
            StubModel(),
        )
        # Case 26 is "A4 copy paper": the stub's `product`+`gsm` payload should
        # not degrade it to a different outcome than the rules reached.
        row26 = next(r for r in rows if r["number"] == 26)
        assert row26["model"]["outcome"] == row26["rules"]["outcome"]


# ---------------------------------------------------------------------------
# 8.6b A configured model that cannot answer is not an agreeing model
# ---------------------------------------------------------------------------

class _UnreachableModel(ModelClient):
    """Configured, and every call raises — what a missing key looks like."""

    def __init__(self) -> None:
        super().__init__(ModelConfig(
            base_url="http://127.0.0.1:20128/v1", model="9inference",
        ))

    @property
    def available(self) -> bool:
        return True

    def extract_criteria(self, request_text: str) -> ModelResult:
        from paperlane.model import ModelUnavailable

        raise ModelUnavailable("model returned HTTP 401: Missing API key")

class TestUnreachableModel:
    """A38: an unreachable model must not manufacture a 24/24 agreement.

    Before the probe, every request fell back to the rules interpretation, so
    both columns were the same run and the harness reported perfect agreement
    between them.
    """

    def test_it_reports_unreachable_rather_than_agreeing(self):
        buffer = io.StringIO()
        assert run_eval(out=buffer, model_client=_UnreachableModel()) == 0
        text = buffer.getvalue()
        assert "configured, unreachable" in text
        assert "Missing API key" in text
        assert "reached the same outcome" not in text

    def test_the_json_payload_carries_the_reason(self):
        buffer = io.StringIO()
        run_eval(out=buffer, model_client=_UnreachableModel(), as_json=True)
        payload = json.loads(buffer.getvalue())
        assert payload["model_probe_error"].startswith("ModelUnavailable")
        assert all(row["model"]["outcome"] == "not run" for row in payload["strategies"])

    def test_a_working_model_still_compares(self):
        buffer = io.StringIO()
        run_eval(out=buffer, model_client=StubModel())
        text = buffer.getvalue()
        assert "reached the same outcome" in text
        assert "unreachable" not in text

# ---------------------------------------------------------------------------
# 8.7 Running with no model
# ---------------------------------------------------------------------------


class TestModelAbsent:
    def test_the_structured_cases_still_run(self):
        buffer = io.StringIO()
        code = run_eval(out=buffer)
        assert code == 0
        text = buffer.getvalue()
        assert "model: not configured" in text
        # Structured cases ran, and the summary says so.
        assert "ran: 24" in text

    def test_the_remainder_is_reported_as_not_run(self):
        buffer = io.StringIO()
        run_eval(out=buffer)
        text = buffer.getvalue()
        assert "not run: [21, 22, 23, 24]" in text

    def test_a_case_needing_a_model_is_not_run_without_one(self, products, facts):
        case = Case(
            number=998, request="A4 copy paper", proves="needs a model",
            expect_outcome="quoted", needs_model=True,
        )
        result = run_case(case, products=products, facts=facts, strategy="model",
                          model_client=None)
        assert result.verdict == "not run"
        assert "no model client" in result.skipped_reason

    def test_json_output_is_machine_readable(self):
        buffer = io.StringIO()
        run_eval(as_json=True, out=buffer)
        payload = json.loads(buffer.getvalue())
        assert payload["model_available"] is False
        assert len(payload["cases"]) == 28
        assert payload["summary"]["total"] == 28
        for case in payload["cases"]:
            assert "expected" in case and "actual" in case and "axes" in case


# ---------------------------------------------------------------------------
# The harness must be able to fail
# ---------------------------------------------------------------------------


class TestSelfCheck:
    def test_every_self_check_passes(self):
        # The self-checks are the harness's own test suite: each corrupts one
        # thing and asserts the intended axis notices.
        buffer = io.StringIO()
        assert self_check(out=buffer) == 0
        text = buffer.getvalue()
        assert "FAIL" not in text
        assert "delivery per line" in text
        assert "VAT on the subtotal alone" in text


# ---------------------------------------------------------------------------
# The shipped negative control must keep failing
# ---------------------------------------------------------------------------


class TestNegativeControl:
    """`eval/negative-control.json` is a fixture, and a fixture can rot.

    It exists to demonstrate that the harness fails when it should. If a later
    change to the catalog or the engine made those corruptions pass, the file
    would become a document claiming something untrue — so the claim is tested.
    """

    CONTROL = Path(__file__).resolve().parents[1] / "eval" / "negative-control.json"

    def test_the_control_fails_on_exactly_the_corrupted_cases(self, products, facts):
        control = {case.number: case for case in load_cases(self.CONTROL)}
        corrupted = {4, 6, 10, 14}

        for number, case in control.items():
            result = run_case(case, products=products, facts=facts,
                              catalog_name="v1")
            if number in corrupted:
                assert result.verdict == "fail", (
                    f"case {number} is corrupted in the fixture but passed"
                )
            elif case.skipped_for("v1"):
                # Inapplicability is now relative to a named catalog, so the
                # check asks the case rather than reading the raw field.
                assert result.verdict == "not run", number
            else:
                assert result.verdict == "pass", (
                    f"case {number} is not corrupted but failed: {result.notes}"
                )

    def test_the_control_attributes_each_failure_to_the_intended_axis(
        self, products, facts
    ):
        control = {case.number: case for case in load_cases(self.CONTROL)}

        # Case 6: right price, wrong product set. Only retrieval may move.
        six = run_case(control[6], products=products, facts=facts)
        assert six.axes["retrieval"] == FAIL
        assert six.axes["pricing"] == PASS, (
            "the wrong-set case must keep a correct price, or it does not "
            "demonstrate that the axes are independent"
        )

        # Case 4: the declared line contradicts the request, so price moves.
        four = run_case(control[4], products=products, facts=facts)
        assert four.axes["pricing"] == FAIL
        assert four.axes["retrieval"] == PASS

        # Case 14: the expected outcome is wrong. Retrieval fails, and pricing
        # fails too — the case expected a price and the engine produced none,
        # which is a real shortfall against the expectation rather than an
        # axis that does not apply.
        fourteen = run_case(control[14], products=products, facts=facts)
        assert fourteen.axes["retrieval"] == FAIL
        assert fourteen.axes["pricing"] == FAIL

        # Case 10: the request's unit conversion is stated as 70 gsm when the
        # request says 20 lb (75 gsm). The products and the price are the
        # engine's own and correct; only the *reading* is corrupted, which is
        # the defect the interpretation axis exists to name. Retrieval and
        # pricing must both stay put, or the axis is measuring the symptom.
        ten = run_case(control[10], products=products, facts=facts)
        assert ten.axes["interpretation"] == FAIL
        assert ten.axes["retrieval"] == PASS, (
            "a corrupted reading must not be reported as a retrieval failure — "
            "the engine found the right products for the criteria it derived"
        )
        assert ten.axes["pricing"] == PASS

    def test_the_control_runs_through_the_cli_path(self):
        # The file is referenced in results.md as runnable; keep that true.
        buffer = io.StringIO()
        code = run_eval(cases_path=self.CONTROL, out=buffer)
        assert code == 1, "a failing case must produce a non-zero exit"
        assert "failed: 4" in buffer.getvalue()


# ---------------------------------------------------------------------------
# The held-out set
# ---------------------------------------------------------------------------


class TestHeldOutSet:
    """A set the rules were not developed against.

    `cases.json` was written while the rules path was being built and was used
    to fix it, which makes it a good regression set and a biased estimate of
    behaviour on unseen wording. This file is the unbiased one, and the two
    properties that matter are that it stays separate and that it is scored by
    the same harness rather than a parallel one.
    """

    HELD_OUT = Path(__file__).resolve().parents[1] / "eval" / "held-out-cases.json"

    def test_it_exists_and_loads_through_the_same_loader(self):
        cases = load_cases(self.HELD_OUT)
        assert len(cases) >= 10
        assert [c.number for c in cases] == list(range(1, len(cases) + 1))

    def test_it_is_a_separate_file_from_the_regression_set(self):
        """The separation is the whole value; merging it would quietly consume it."""
        regression = {c.request for c in load_cases()}
        held_out = {c.request for c in load_cases(self.HELD_OUT)}
        assert held_out, "the held-out set is empty"
        assert not (held_out & regression), (
            "a request appears in both sets, so it was used to develop the rules "
            "and is no longer held out"
        )

    def test_a_default_run_does_not_load_it(self, products, facts):
        """The regression run's counts must not change because a second file exists."""
        buffer = io.StringIO()
        run_eval(out=buffer)
        assert "held-out" not in buffer.getvalue()

    def test_it_is_scored_by_the_same_harness(self, products, facts):
        """Same loader, same axes, same scoring — no parallel reporting path."""
        cases = load_cases(self.HELD_OUT)
        result = run_case(cases[0], products=products, facts=facts)
        assert set(result.axes) == set(AXES)
        for axis in AXES:
            assert result.axes[axis] in (PASS, FAIL, NA), axis

    def test_it_carries_no_transcribed_totals(self):
        """Same rule as the recorded set: totals are recomputed, never written."""
        raw = json.loads(self.HELD_OUT.read_text())
        for entry in raw["cases"]:
            expect = entry.get("expect", {})
            for key in ("total", "subtotal", "vat", "delivery"):
                assert key not in expect, (entry["number"], key)

    def test_it_records_at_least_one_failure(self, products, facts):
        """A held-out set that passes completely is evidence about its author.

        The failures currently recorded are all one defect — an unmappable noun
        ("pink", "grey", "lb") is dropped rather than honoured, widening the
        answer to every paper of that size. Asserting a failure remains is how
        that finding cannot be quietly lost by a later change that deletes the
        cases instead of fixing the cause.
        """
        cases = {c.number: c for c in load_cases(self.HELD_OUT)}
        results = [
            run_case(case, products=products, facts=facts)
            for case in cases.values()
        ]
        failed = [r.case.number for r in results if r.verdict == "fail"]
        assert failed, (
            "the held-out set now passes entirely. That is possible — but if it "
            "is real, say so explicitly rather than deleting this assertion"
        )

    def test_a_failure_names_the_case_and_carries_its_expectation(
        self, products, facts
    ):
        """A failure must be legible: what was expected, and what was read."""
        cases = {c.number: c for c in load_cases(self.HELD_OUT)}
        for number, case in cases.items():
            result = run_case(case, products=products, facts=facts)
            if result.verdict != "fail":
                continue
            assert result.notes, number
            # The expectation travels with the result, so a reader sees both
            # sides rather than only the verdict.
            payload = _result_dict(result)
            assert payload["expected"]["outcome"] == case.expect_outcome
            break


# ---------------------------------------------------------------------------
# Second-catalog evaluation
# ---------------------------------------------------------------------------


class TestCaseFormatExtension:
    """Inapplicability names a catalog, rather than being a permanent verdict."""

    def test_the_committed_cases_still_load(self):
        cases = load_cases()
        assert len(cases) == 28
        assert [c.number for c in cases] == list(range(1, 29))

    def test_the_four_previously_inapplicable_cases_name_their_catalog(self):
        cases = {c.number: c for c in load_cases()}
        for number in (21, 22, 23, 24):
            assert cases[number].requires_catalog == "v2", number
            assert cases[number].not_applicable, number

    def test_a_case_with_no_requirement_applies_everywhere(self):
        case = Case(number=1, request="x", proves="y", expect_outcome="quoted")
        assert case.applies_to("v1")
        assert case.applies_to("v2")
        assert case.skipped_for("v1") is None

    def test_a_required_catalog_skip_names_the_catalog_that_can_run_it(self):
        case = Case(number=1, request="x", proves="y", expect_outcome="quoted",
                    requires_catalog="v2")
        reason = case.skipped_for("v1")
        assert reason is not None
        assert "'v2'" in reason and "'v1'" in reason

    def test_per_catalog_expectation_overrides_the_base(self):
        case = Case(
            number=23, request="28 lb paper", proves="conversion",
            expect_outcome="no_match", expect_relaxed="weight",
            requires_catalog="v2",
            expect_by_catalog={"v2": {"outcome": "quoted", "skus": ["PL-CP-LTR-28"]}},
        )
        assert case.effective_expectation("v2")["outcome"] == "quoted"
        assert case.effective_expectation("v2")["skus"] == ["PL-CP-LTR-28"]

    def test_without_an_override_the_recorded_expectation_stands(self):
        case = Case(number=1, request="x", proves="y", expect_outcome="quoted",
                    expect_skus=("PL-A",))
        assert case.effective_expectation("v1")["outcome"] == "quoted"


class TestCrossCatalogScoring:
    def test_a_v2_case_is_skipped_on_v1(self, products, facts):
        cases = {c.number: c for c in load_cases()}
        result = run_case(cases[23], products=products, facts=facts,
                          catalog_name="v1")
        assert result.verdict == "not run"
        assert "v2" in result.skipped_reason

    def test_the_same_case_runs_against_a_catalog_that_satisfies_it(self):
        """The behaviour that made the case inapplicable is now demonstrable."""
        pytest.importorskip("duckdb")
        mutated = Path(__file__).resolve().parents[1] / ".refresh-verification" / "mutated.duckdb"
        if not mutated.exists():
            pytest.skip("run ./run.sh verify-refresh to build the mutated catalog")

        reset_cache()
        products = catalog.load_products(mutated)
        facts = _load_facts(mutated)
        cases = {c.number: c for c in load_cases()}

        result = run_case(cases[23], products=products, facts=facts,
                          catalog_name="v2")
        assert result.verdict == "pass", (result.axes, result.notes)
        assert result.outcome == "quoted"
        assert result.actual_skus[0] == "PL-CP-LTR-28"
        reset_cache()

    def test_a_case_pinned_to_v1_is_skipped_on_v2(self, products, facts):
        cases = {c.number: c for c in load_cases()}
        result = run_case(cases[4], products=products, facts=facts,
                          catalog_name="v2")
        assert result.verdict == "not run"
        assert "v1" in result.skipped_reason


class TestTheCatalogFlagOnTheCommandLine:
    """`--catalog v2` has to reach the runner, not just parse.

    The number 21/21 was already true through the Python API; the defect was
    that ``./run.sh`` could not ask for it. These pin the command-line path and
    the two pairings that would otherwise be labelled wrongly.
    """

    def test_the_flag_defaults_to_the_committed_catalog(self):
        assert cli.build_parser().parse_args(["eval"]).catalog == V1

    def test_the_flag_reaches_the_runner(self, monkeypatch):
        seen: dict = {}

        def fake_run_eval(**kwargs):
            seen.update(kwargs)
            return 0

        monkeypatch.setattr("paperlane.evaluate.run_eval", fake_run_eval)
        code = cli.main(["eval", "--catalog", V2, "--db", "/tmp/mutated.duckdb"])
        assert code == 0
        assert seen["catalog_name"] == V2
        assert seen["db_path"] == "/tmp/mutated.duckdb"

    def test_v2_against_the_committed_snapshot_is_refused(self, capsys, monkeypatch):
        """The flag names the expectations; the snapshot has to be the one they
        describe. Scoring v2 cases against v1 data would print a v2 label over a
        v1 run — the same mislabel the flag exists to remove."""
        monkeypatch.delenv("PAPERLANE_DB", raising=False)
        code = cli.main(["eval", "--catalog", V2])
        assert code == 2
        assert "--catalog v2" in capsys.readouterr().err

    def test_a_conversation_set_refuses_a_catalog_it_cannot_use(self, capsys):
        """The conversation cases have no per-catalog expectation.

        Ignoring the flag would be worse than refusing: the run would carry a
        label that is not what was scored.
        """
        cases = Path(__file__).resolve().parents[1] / "eval" / "conversation-cases.json"
        code = cli.main(["eval", "--cases", str(cases), "--catalog", V2])
        assert code == 2
        assert "conversation set" in capsys.readouterr().err


class TestEvalCliModelWiring:
    """A37: the documented comparison must actually reach the model.

    ``run_eval`` has accepted a ``model_client`` since 0.5.0, and
    ``eval/results.md`` records a rules-versus-model table under
    ``./run.sh eval``. The command never built a client, so the run printed
    ``model: not configured`` no matter what the environment held.
    """

    def test_a_configured_environment_passes_a_client(self, monkeypatch):
        seen: dict = {}

        def fake_run_eval(**kwargs):
            seen.update(kwargs)
            return 0

        monkeypatch.setenv("PAPERLANE_LLM_BASE_URL", "http://localhost:11434/v1")
        monkeypatch.setenv("PAPERLANE_LLM_MODEL", "qwen3.5:2b")
        monkeypatch.setenv("PAPERLANE_LLM_REASONING_EFFORT", "none")
        monkeypatch.setattr("paperlane.evaluate.run_eval", fake_run_eval)

        assert cli.main(["eval"]) == 0
        client = seen["model_client"]
        assert client is not None
        assert client.available is True
        assert client.config.base_url == "http://localhost:11434/v1"
        assert client.config.model == "qwen3.5:2b"
        assert client.config.reasoning_effort == "none"

    def test_an_unconfigured_environment_passes_none(self, monkeypatch):
        """The model-free run must stay byte-identical: no client, no change."""
        seen: dict = {}

        def fake_run_eval(**kwargs):
            seen.update(kwargs)
            return 0

        for name in (
            "PAPERLANE_LLM_BASE_URL",
            "PAPERLANE_LLM_MODEL",
            "PAPERLANE_LLM_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
            "OPENAI_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr("paperlane.evaluate.run_eval", fake_run_eval)

        assert cli.main(["eval"]) == 0
        assert seen["model_client"] is None


class TestCatalogRecordedInResults:
    def test_the_run_names_its_catalog(self):
        buffer = io.StringIO()
        run_eval(out=buffer)
        assert "Evaluation against v1" in buffer.getvalue()

    def test_two_catalogs_are_distinguishable_in_the_output(self):
        first, second = io.StringIO(), io.StringIO()
        run_eval(out=first)
        run_eval(out=second, catalog_name="v2")
        assert "v1" in first.getvalue()
        assert "v2" in second.getvalue()
        assert first.getvalue() != second.getvalue()

    def test_the_payload_records_the_catalog(self):
        buffer = io.StringIO()
        run_eval(as_json=True, out=buffer)
        payload = json.loads(buffer.getvalue())
        assert payload["catalog"] == "v1"

    def test_the_summary_separates_other_catalog_skips(self):
        buffer = io.StringIO()
        run_eval(as_json=True, out=buffer)
        summary = json.loads(buffer.getvalue())["summary"]
        assert summary["requires_other_catalog"] == {
            "21": "v2", "22": "v2", "23": "v2", "24": "v2",
        }


class TestScorersUseTheCatalogUnderTest:
    """The regression guard for the defect the second catalog exposed.

    `_score_reply` and `_score_match` used to validate against
    `catalog.load_products()` with no argument — always the committed snapshot.
    Any SKU existing only in the catalog under test was then reported as
    "invented", i.e. a correct reply was scored as a hallucination.

    Asserted with a synthetic second catalog rather than the real mutated one, so
    the guard runs in a clean checkout instead of skipping when the scratch
    directory is absent.
    """

    def _second_catalog(self):
        return [{
            "sku": "PL-ZZ-ONLY-IN-V2",
            "category": "Copy paper",
            "stock_status": "in_stock",
            "weight_gsm": 80,
            "size_code": "A4",
            "colour_name": "White",
            "colour_mode": None,
            "list_price_satang": 12_900,
            "sale_price_satang": None,
            "unit_word": "ream of 500 sheets",
            "has_volume_pricing": False,
        }]

    def test_a_sku_only_in_the_catalog_under_test_is_not_invented(self):
        case = Case(number=900, request="x", proves="y", expect_outcome="quoted")
        result = CaseResult(case=case)
        result.outcome = "quoted"
        result.reply_text = "Best match — something (PL-ZZ-ONLY-IN-V2)"
        result.products = self._second_catalog()

        assert _score_reply(case, result) == PASS, result.notes

    def test_the_same_reply_fails_when_judged_against_the_committed_catalog(self):
        """Proves the assertion above is not vacuous."""
        case = Case(number=901, request="x", proves="y", expect_outcome="quoted")
        result = CaseResult(case=case)
        result.outcome = "quoted"
        result.reply_text = "Best match — something (PL-ZZ-ONLY-IN-V2)"
        result.products = None  # falls back to the committed snapshot

        assert _score_reply(case, result) == FAIL
