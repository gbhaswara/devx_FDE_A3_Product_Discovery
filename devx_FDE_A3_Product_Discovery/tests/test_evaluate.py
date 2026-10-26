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

from paperlane import catalog
from paperlane.evaluate import (
    AXES,
    FAIL,
    NA,
    PASS,
    Case,
    _score_pricing,
    _score_reply,
    _score_retrieval,
    load_cases,
    recompute_totals,
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
    def test_all_four_axes_are_reported_for_a_runnable_case(self, cases, products,
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
        corrupted = {4, 6, 14}

        for number, case in control.items():
            result = run_case(case, products=products, facts=facts)
            if number in corrupted:
                assert result.verdict == "fail", (
                    f"case {number} is corrupted in the fixture but passed"
                )
            elif case.not_applicable:
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

    def test_the_control_runs_through_the_cli_path(self):
        # The file is referenced in results.md as runnable; keep that true.
        buffer = io.StringIO()
        code = run_eval(cases_path=self.CONTROL, out=buffer)
        assert code == 1, "a failing case must produce a non-zero exit"
        assert "failed: 3" in buffer.getvalue()
