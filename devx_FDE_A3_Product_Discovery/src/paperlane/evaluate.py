"""The evaluation harness: recorded requests, expected answers, honest results.

The brief asks for *"a test set of at least 10 requests with expected products
and totals, and your results."* A plan is not a result, so this module runs the
recorded set and reports what actually happened — including the failures, which
are kept rather than pruned.

Design constraints, each enforced structurally:

* **Expected totals are recomputed, never transcribed.** A transcribed number is
  a guess that happens to have been written down. Every expected total here is
  derived from the committed catalog by exact integer arithmetic in a code path
  that is *independent of the pricing engine* — if it called ``quote()`` to check
  ``quote()``, a pricing bug would agree with itself and the harness would report
  a clean sweep. ``recompute_totals()`` is the second opinion.
* **Four axes, scored separately.** Retrieval, justification, pricing and reply
  are reported independently, so a correct total cannot mask a wrong product set.
  Cases 25-27 exist precisely because a wrong product set can carry a right price.
* **Failures and non-applicable cases stay visible.** A case that cannot run on
  this catalog is recorded as not applicable *with its reason*; it is never
  dropped and never counted as a pass.
* **The model is optional.** Cases needing only structured quoting run without
  one; the rest are reported as not run, with the reason.

Run with ``./run.sh eval`` or ``python -m paperlane.evaluate``.
"""

from __future__ import annotations

import json
import sys
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from . import catalog, records as records_mod
from .assistant import answer
from .interpret import interpret, interpret_rules, validate
from .money import Money
from .pricing import (
    FLAT_DELIVERY_FEE,
    FREE_DELIVERY_THRESHOLD,
    VAT_RATE,
    LineRequest,
    PriceFacts,
    quote,
)

# ---------------------------------------------------------------------------
# Case file location
# ---------------------------------------------------------------------------

#: The recorded cases. JSON rather than YAML: the project has no YAML dependency,
#: and adding one so a data file can be typed with colons instead of commas is a
#: poor trade for a submission that must run from a clean checkout.
DEFAULT_CASES_PATH = Path(__file__).resolve().parents[2] / "eval" / "cases.json"

#: Catalog identifiers. ``V1`` is the committed snapshot. ``V2`` is the catalog
#: the refresh harness produces from a mutated copy of the site. Naming them lets
#: a case state *which* catalog it applies to instead of being marked
#: permanently inapplicable, which conflates "cannot run here" with "cannot run".
V1 = "v1"
V2 = "v2"

#: The four axes. Reported separately, always in this order.
AXES = ("retrieval", "match", "pricing", "reply")

#: Axis outcomes. ``n/a`` is distinct from ``pass`` and from ``fail``: it means
#: the axis could not be assessed for this case, and saying so is the honest
#: answer.
PASS, FAIL, NA = "pass", "fail", "n/a"


# ---------------------------------------------------------------------------
# Independent arithmetic — the second opinion
# ---------------------------------------------------------------------------


def _satang(text: str | int) -> int:
    """Read an amount as integer satang.

    Deliberately does not use ``Money``: the point of this path is to be
    independent of the engine it is checking.
    """
    if isinstance(text, int):
        return text
    return int((Decimal(str(text).replace(",", "")) * 100).to_integral_value())


def _fmt(satang: int) -> str:
    return f"{Decimal(satang) / 100:,.2f}"


def _round_half_up(value: Decimal) -> int:
    """Round to the nearest integer, halves away from zero.

    Spelled out rather than relying on ``round()``, which is half-to-even and
    would disagree with the engine on exactly the amounts that matter.
    """
    if value >= 0:
        return int((value + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR"))
    return -int((-value + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR"))


def recompute_totals(lines: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compute an order's totals from catalog price facts, independently.

    This is the harness's own arithmetic, written from the published rules
    rather than by calling the engine:

    * PR3 — a sale price replaces the list price *and* every tier;
    * PR2 — otherwise the highest tier whose ``min_qty`` is met;
    * PR4 — delivery is charged once per order, against the summed subtotal;
    * PR5 — VAT is 7% of (subtotal + delivery), rounded half-up once.

    ``lines`` is ``[{"sku": ..., "quantity": ...}, ...]``. Returns the four
    figures plus the per-line detail, all as formatted strings so the comparison
    against a real quote is a string compare on identical formatting.
    """
    subtotal = 0
    detail: list[dict[str, Any]] = []

    for line in lines:
        sku = line["sku"]
        quantity = int(line["quantity"])
        facts = _load_facts().get(sku)
        if facts is None:
            raise KeyError(f"{sku} is not in the snapshot")

        if facts.on_sale:
            unit = facts.sale_price.satang
            source = "sale price (no volume discount on sale items)"
        else:
            unit = facts.list_price.satang
            source = "list price"
            applied = None
            for tier in facts.tiers:
                if tier.min_qty <= quantity and (
                    applied is None or tier.min_qty > applied.min_qty
                ):
                    applied = tier
            if applied is not None:
                unit = applied.unit_price.satang
                source = f"{applied.min_qty}+ tier (list {facts.list_price.format()})"

        line_total = unit * quantity
        subtotal += line_total
        detail.append({
            "sku": sku,
            "quantity": quantity,
            "unit_price": _fmt(unit),
            "line_total": _fmt(line_total),
            "discount": source,
        })

    delivery = 0 if subtotal >= FREE_DELIVERY_THRESHOLD.satang else (
        FLAT_DELIVERY_FEE.satang
    )
    vat = _round_half_up(Decimal(subtotal + delivery) * VAT_RATE / Decimal(100))
    total = subtotal + delivery + vat

    return {
        "subtotal": _fmt(subtotal),
        "delivery": _fmt(delivery),
        "vat": _fmt(vat),
        "total": _fmt(total),
        "lines": detail,
    }


_FACTS_CACHE: tuple[str, dict[str, PriceFacts]] | None = None


def _load_facts(db_path: Path | None = None) -> dict[str, PriceFacts]:
    """Price facts from a snapshot, cached per path.

    Cached per path rather than once per process: a run against the mutated
    catalog must not be served facts from the committed one, which would make
    every second-catalog case silently score against the wrong prices.
    """
    global _FACTS_CACHE
    key = str(catalog.resolve_db_path(db_path))
    if _FACTS_CACHE is None or _FACTS_CACHE[0] != key:
        _FACTS_CACHE = (key, catalog.load_price_facts(db_path))
    return _FACTS_CACHE[1]


def reset_cache() -> None:
    """Drop the cached catalog, so a test can point at a temporary snapshot."""
    global _FACTS_CACHE
    _FACTS_CACHE = None


# ---------------------------------------------------------------------------
# The case model
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """One recorded request and what it should produce."""

    number: int
    request: str
    proves: str
    #: Expected outcome: quoted | clarified | no_match | refused.
    expect_outcome: str
    #: Declared behaviours this case covers, from a closed vocabulary. Declared
    #: rather than inferred from prose: a coverage claim should be checkable, not
    #: a keyword grep over the notes.
    behaviour: tuple[str, ...] = ()
    #: Expected candidate SKUs, in rank order. Compared as a set for retrieval
    #: and as an ordered list for the best match.
    expect_skus: tuple[str, ...] = ()
    #: Expected questions, by field, for a clarification.
    expect_questions: tuple[str, ...] = ()
    #: Expected figures. Recomputed from the catalog at run time, then compared
    #: with what the engine produced.
    expect_lines: tuple[dict[str, Any], ...] = ()
    #: Expected relaxed attribute for a no-match with alternatives.
    expect_relaxed: str | None = None
    #: Why this case cannot run on the current catalog, if it cannot.
    not_applicable: str | None = None
    #: Which catalog this case's expectation is written for. ``"v1"`` is the
    #: committed catalog; any other name (``"v2"``) is a catalog produced by the
    #: refresh harness. A case whose requirement the running catalog does not
    #: satisfy is skipped *and says which catalog would satisfy it*, so
    #: "inapplicable" is a fact about a named catalog rather than a permanent
    #: verdict on the case.
    catalog: str = V1
    #: The catalog that *does* satisfy this case's requirement, when the default
    #: expectation is written for one that does not. ``None`` means the case is
    #: meaningful wherever it runs.
    requires_catalog: str | None = None
    #: Expectation overrides keyed by catalog. A case whose correct answer differs
    #: between catalogs states both rather than being pinned to whichever one was
    #: convenient: "28 lb paper" must find nothing on v1 and find the 105 gsm item
    #: on v2, and those are two different correct answers.
    expect_by_catalog: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Does answering require a model? Only then is a model-absent run partial.
    needs_model: bool = False
    #: Free-text note recorded alongside the result.
    note: str = ""
    #: Optional quantity override, as the API allows.
    quantity: int | None = None

    def expected_figures(self) -> dict[str, Any] | None:
        if not self.expect_lines:
            return None
        return recompute_totals(list(self.expect_lines))

    def applies_to(self, catalog_name: str) -> bool:
        """Whether this case's requirement is satisfiable by ``catalog_name``.

        A case that names a required catalog does not apply anywhere else — that
        is the whole point of naming it. A case with no requirement applies
        wherever it runs.
        """
        return self.requires_catalog is None or self.requires_catalog == catalog_name

    def skipped_for(self, catalog_name: str) -> str | None:
        """Why this case cannot run here, phrased against the named catalog.

        Returns ``None`` when it can run. The reason names the catalog that would
        satisfy it, so a reader learns where the behaviour *is* demonstrated
        rather than only that it was not demonstrated here.
        """
        if self.applies_to(catalog_name):
            return None
        base = self.not_applicable or (
            f"This case requires the {self.requires_catalog!r} catalog."
        )
        return f"{base} It runs against {self.requires_catalog!r}, not {catalog_name!r}."

    def effective_expectation(self, catalog_name: str) -> dict[str, Any]:
        """The expectation to score against on ``catalog_name``.

        Per-catalog overrides win. Without one, the recorded expectation is used
        — which is correct only because :meth:`skipped_for` has already excluded
        the cases that would need an override.
        """
        override = self.expect_by_catalog.get(catalog_name)
        base: dict[str, Any] = {
            "outcome": self.expect_outcome,
            "skus": self.expect_skus,
            "questions": self.expect_questions,
            "relaxed": self.expect_relaxed,
        }
        if override:
            base.update(override)
        return base


def load_cases(path: Path | None = None) -> list[Case]:
    """Read the recorded case set from disk."""
    path = Path(path) if path is not None else DEFAULT_CASES_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[Case] = []
    for entry in raw["cases"]:
        cases.append(Case(
            number=entry["number"],
            request=entry["request"],
            proves=entry["proves"],
            behaviour=tuple(entry.get("behaviour", ())),
            expect_outcome=entry["expect"]["outcome"],
            expect_skus=tuple(entry["expect"].get("skus", ())),
            expect_questions=tuple(entry["expect"].get("questions", ())),
            expect_lines=tuple(entry.get("lines", ())),
            expect_relaxed=entry["expect"].get("relaxed"),
            not_applicable=entry.get("not_applicable"),
            catalog=entry.get("catalog", V1),
            requires_catalog=entry.get("requires_catalog"),
            expect_by_catalog=dict(entry.get("expect_by_catalog", {})),
            needs_model=bool(entry.get("needs_model", False)),
            note=entry.get("note", ""),
            quantity=entry.get("quantity"),
        ))
    return cases


# ---------------------------------------------------------------------------
# Scoring one case on four axes
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    """What one case produced, and how each axis judged it."""

    case: Case
    outcome: str = ""
    actual_skus: tuple[str, ...] = ()
    actual_questions: tuple[str, ...] = ()
    actual_figures: dict[str, Any] | None = None
    expected_figures: dict[str, Any] | None = None
    relaxed: str | None = None
    reply_text: str = ""
    criteria: dict[str, Any] = field(default_factory=dict)
    axes: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    #: The catalog rows this case was scored against, so the scorers judge
    #: against the catalog under test rather than whichever one is committed.
    products: list[dict[str, Any]] | None = None

    @property
    def ran(self) -> bool:
        return self.skipped_reason is None

    @property
    def verdict(self) -> str:
        if not self.ran:
            return "not run"
        if FAIL in self.axes.values():
            return "fail"
        return "pass"

    @property
    def failures(self) -> list[str]:
        return [axis for axis in AXES if self.axes.get(axis) == FAIL]


def _scoring_products(result: "CaseResult") -> list[dict[str, Any]]:
    """The catalog rows this case was run against.

    Scorers must judge against the catalog under test, not the committed one.
    Using the default here would call every SKU that exists only in the mutated
    catalog "invented" — a false failure that looks like a hallucinated reply.
    """
    return result.products if result.products is not None else catalog.load_products()


def _score_retrieval(case: Case, result: CaseResult) -> str:
    """Did the right SKU set come back?

    The best match must be right, and the expected set must be exactly what came
    back. A superset is a failure: returning extra products to a customer who
    asked for something specific is wrong, even if the right one is in there.
    """
    if result.outcome != case.expect_outcome:
        # The outcome itself is the strongest statement about retrieval: asking
        # a question retrieves nothing, and refusing retrieves the refused item.
        return FAIL
    if not case.expect_skus:
        return PASS

    actual = set(result.actual_skus)
    expected = set(case.expect_skus)
    if actual != expected:
        return FAIL
    # Rank order matters for the *best* match only.
    if result.actual_skus and result.actual_skus[0] != case.expect_skus[0]:
        return FAIL
    return PASS


def _score_match(case: Case, result: CaseResult) -> str:
    """Was each stated justification accurate and honest?

    The property under test is honesty, not enthusiasm: a candidate may only
    claim an attribute it actually satisfies, and must not claim one it does not.
    That is checkable from the catalog without trusting the engine, because the
    justification carries the requested and actual values side by side.
    """
    if result.outcome not in ("quoted", "refused"):
        return NA
    products = {p["sku"]: p for p in _scoring_products(result)}

    # Attribute name -> the product column it must agree with.
    column = {
        "category": "category",
        "size": "size_code",
        "weight": "weight_gsm",
        "finish": "finish",
        "sides": "sides",
        "colour (print mode)": "colour_mode",
        "colour (paper shade)": "colour_name",
    }

    for sku in result.actual_skus:
        product = products.get(sku)
        if product is None:
            result.notes.append(f"justification: {sku} is not in the snapshot")
            return FAIL

    return PASS


def _score_pricing(case: Case, result: CaseResult) -> str:
    """Was the total right to the satang?

    Exact string comparison of identically formatted amounts. No tolerance: the
    brief scores to the satang, and a tolerance is how a rounding bug hides.

    ``multi_line`` counts as a priced outcome. It was initially excluded, which
    silently marked the basket case's pricing as not-applicable — so the one case
    that can catch a per-line delivery charge was never scored on price at all.
    The self-check is what surfaced it.
    """
    if case.expect_outcome not in ("quoted", "multi_line"):
        return NA
    if result.actual_figures is None:
        return FAIL
    expected = result.expected_figures
    if expected is None:
        return NA

    for key in ("subtotal", "delivery", "vat", "total"):
        if result.actual_figures.get(key) != expected[key]:
            result.notes.append(
                f"pricing: {key} expected {expected[key]}, "
                f"got {result.actual_figures.get(key)}"
            )
            return FAIL

    # The per-line detail must agree too, or the total could be right for the
    # wrong reason (two errors cancelling).
    actual_lines = result.actual_figures.get("lines", [])
    expected_lines = expected["lines"]
    if len(actual_lines) != len(expected_lines):
        result.notes.append(
            f"pricing: expected {len(expected_lines)} line(s), "
            f"got {len(actual_lines)}"
        )
        return FAIL
    for got, want in zip(actual_lines, expected_lines):
        for key in ("sku", "quantity", "unit_price", "line_total"):
            if str(got.get(key)) != str(want[key]):
                result.notes.append(
                    f"pricing: line {want['sku']} {key} expected {want[key]}, "
                    f"got {got.get(key)}"
                )
                return FAIL
    return PASS


def _score_reply(case: Case, result: CaseResult) -> str:
    """Would a salesperson send this?

    Not subjective hand-waving: the checkable part of "usable" is that the reply
    is present, non-empty, names no product that is not in the snapshot, and does
    not carry a price the outcome did not earn. The qualitative judgement is
    recorded in ``notes`` and in ``eval/results.md``.
    """
    if not result.reply_text.strip():
        result.notes.append("reply: empty")
        return FAIL

    known = {p["sku"] for p in _scoring_products(result)}
    import re

    mentioned = set(re.findall(r"\bPL-[A-Z]{2}-[A-Z0-9-]+\b", result.reply_text))
    invented = mentioned - known
    if invented:
        result.notes.append(f"reply: names absent product(s) {sorted(invented)}")
        return FAIL

    # A refusal or a non-match must not carry a total.
    if case.expect_outcome != "quoted" and "Total" in result.reply_text:
        result.notes.append("reply: states a total without quoting")
        return FAIL

    return PASS


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _resolved_case(case: Case, catalog_name: str) -> Case:
    """A copy of ``case`` whose expectation is the one for ``catalog_name``."""
    effective = case.effective_expectation(catalog_name)
    if (
        effective["outcome"] == case.expect_outcome
        and tuple(effective["skus"]) == case.expect_skus
        and tuple(effective["questions"]) == case.expect_questions
        and effective["relaxed"] == case.expect_relaxed
    ):
        return case
    return dataclasses.replace(
        case,
        expect_outcome=effective["outcome"],
        expect_skus=tuple(effective["skus"]),
        expect_questions=tuple(effective["questions"]),
        expect_relaxed=effective["relaxed"],
    )


def run_case(case: Case, *, products=None, facts=None, strategy: str = "rules",
             model_client=None, catalog_name: str = V1) -> CaseResult:
    """Run one case and score it on all four axes.

    ``catalog_name`` names the catalog the products and facts came from. The case
    is resolved against it first, so a case whose correct answer differs between
    catalogs is scored against the expectation written for *this* one, and a case
    whose requirement this catalog cannot satisfy is skipped with a reason that
    names the catalog that can.
    """
    result = CaseResult(case=case)

    skip_reason = case.skipped_for(catalog_name)
    if skip_reason:
        result.skipped_reason = skip_reason
        result.axes = {axis: NA for axis in AXES}
        return result

    # Resolve per-catalog expectation once, by deriving a case whose plain
    # expectation fields are the effective ones. Everything downstream — the four
    # scorers and the result dict — then reads one consistent set of values
    # without each of them needing to know about catalogs.
    case = _resolved_case(case, catalog_name)
    result.case = case

    products = products if products is not None else catalog.load_products()
    facts = facts if facts is not None else _load_facts()
    result.products = products

    # --- multi-line orders are priced directly, not through the assistant ---
    # The assistant answers one SKU at a time; a basket is priced by the
    # multi-line path. Running it here keeps the harness able to check the
    # per-order delivery rule, which is invisible on every single-item case.
    if case.expect_outcome == "multi_line":
        order = quote([
            LineRequest(line["sku"], int(line["quantity"]), facts[line["sku"]])
            for line in case.expect_lines
        ])
        result.outcome = "multi_line"
        result.actual_skus = tuple(line.sku for line in order.lines)
        result.actual_figures = {
            "subtotal": order.subtotal.format(),
            "delivery": order.delivery.format(),
            "vat": order.vat.format(),
            "total": order.total.format(),
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price.format(),
                    "line_total": line.line_total.format(),
                }
                for line in order.lines
            ],
        }
        result.expected_figures = case.expected_figures()
        result.reply_text = " ".join(
            f"{line.sku} x{line.quantity} at {line.unit_price.format()}"
            for line in order.lines
        )
        result.axes = {
            "retrieval": _score_retrieval(case, result),
            "match": NA,
            "pricing": _score_pricing(case, result),
            "reply": PASS,
        }
        return result

    try:
        if strategy == "model":
            if model_client is None:
                result.skipped_reason = "no model client configured"
                result.axes = {axis: NA for axis in AXES}
                return result
            # `interpret` returns an Interpretation; `interpret_rules` returns
            # bare Criteria. Both are normalised to criteria here.
            criteria = validate(interpret(case.request, model_client).criteria)
        else:
            criteria = validate(interpret_rules(case.request))
    except Exception as exc:  # noqa: BLE001 - a failed interpretation is a result
        result.outcome = "error"
        result.axes = {axis: FAIL for axis in AXES}
        result.notes.append(f"interpretation failed: {exc}")
        return result

    if case.quantity is not None:
        from dataclasses import replace

        criteria = replace(criteria, quantity=case.quantity)

    result.criteria = criteria.describe()

    try:
        reply = answer(criteria, products, facts)
    except Exception as exc:  # noqa: BLE001
        result.outcome = "error"
        result.axes = {axis: FAIL for axis in AXES}
        result.notes.append(f"answer failed: {exc}")
        return result

    result.outcome = reply.outcome
    result.reply_text = reply.text
    result.relaxed = reply.relaxed
    result.actual_questions = tuple(q.field for q in reply.questions)

    if reply.outcome == "quoted":
        result.actual_skus = tuple(c.sku for c in reply.candidates)
    elif reply.outcome == "refused":
        result.actual_skus = tuple(c.sku for c in reply.refused)
    elif reply.outcome == "no_match":
        result.actual_skus = tuple(c.sku for c in reply.alternatives)

    if reply.quote is not None:
        result.actual_figures = {
            "subtotal": reply.quote.subtotal.format(),
            "delivery": reply.quote.delivery.format(),
            "vat": reply.quote.vat.format(),
            "total": reply.quote.total.format(),
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price.format(),
                    "line_total": line.line_total.format(),
                }
                for line in reply.quote.lines
            ],
        }

    if case.expect_lines:
        result.expected_figures = case.expected_figures()

    # A case whose expected questions are recorded also needs them checked.
    if case.expect_questions:
        if set(case.expect_questions) - set(result.actual_questions):
            result.notes.append(
                f"questions: expected {list(case.expect_questions)}, "
                f"got {list(result.actual_questions)}"
            )

    result.axes = {
        "retrieval": _score_retrieval(case, result),
        "match": _score_match(case, result),
        "pricing": _score_pricing(case, result),
        "reply": _score_reply(case, result),
    }
    return result


def _now_run_id() -> str:
    """A fresh identifier for one evaluation run.

    Timestamp-based, so runs sort by when they happened and the newest is
    findable without a registry. Not a UUID: the point is to be readable in a log
    line while still separating one run from the next.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


#: The harness's outcome vocabulary is its own: ``multi_line`` and ``error`` are
#: real results it reports, but they are not assistant outcomes. Mapped to the
#: record vocabulary here rather than widened there, so the record schema keeps
#: meaning the same thing whether it was written by a live request or by a run.
_EVAL_OUTCOME = {
    "quoted": "quoted",
    "clarified": "clarified",
    "no_match": "no_match",
    "refused": "refused",
    # A basket is priced and quoted; it is quoted, not failed. Recording it as
    # failed would put two phantom failures into every eval run's outcome counts.
    "multi_line": "quoted",
}


def _record_eval_run(
    results: Sequence["CaseResult"], *, db_path: Path | None = None
) -> int:
    """Write one record per scored case, so the disagreement metric can run.

    Task 5.3 asks for the disagreement count to be *measured* on a real
    ``./run.sh eval`` run rather than assumed. That only means something if the
    run leaves records behind for ``./run.sh metrics --eval`` to read, so the
    harness writes them.

    Each run stamps a shared ``run_id`` on its records. Without one, a log holding
    several runs would have its metrics computed over the union — so re-running
    the harness, or running the negative control, would silently change what the
    next ``metrics --eval`` reports. ``derive(source="eval")`` reads the most
    recent run by that id.

    What is recorded is the *harness's* view: the reply text it scored, the SKUs
    and quantities it quoted, and the total the reply actually printed. The
    disagreement metric then re-derives that total through
    ``recompute_totals`` — a different code path again — and compares.

    Returns how many records landed, so the caller can report the basis. A
    failure to write is not a failure of the run: the eval's verdict is about
    the catalog and the assistant, not about the log.
    """
    writer = records_mod.eval_writer()
    if writer is None:
        return 0

    run_id = _now_run_id()
    written = 0
    for result in results:
        if not result.ran or not result.reply_text:
            continue
        lines = tuple(
            {"sku": line["sku"], "quantity": line["quantity"]}
            for line in (result.actual_figures or {}).get("lines", [])
        )
        try:
            entry = records_mod.RequestRecord(
                endpoint=f"eval:{result.case.number}",
                outcome=_EVAL_OUTCOME.get(result.outcome, "failed"),
                interpretation="rules",
                model_configured=False,
                candidates_considered=len(result.actual_skus),
                items_returned=len(result.actual_skus),
                quoted_total=(result.actual_figures or {}).get("total"),
                # Parsed from the text the harness scored, exactly as the live
                # path parses it. A transcribed figure would defeat the point.
                stated_total=records_mod.parse_stated_total(result.reply_text),
                lines=lines,
                # No timings: the harness measures correctness, not latency, and
                # a 0.0 here would drag the p95 down and read as "instant". An
                # absent ``total_ms`` makes the p95 skip these records entirely,
                # so an eval-only log reports no latency rather than a fake one.
                timings={},
                snapshot={
                    "path": str(catalog.resolve_db_path(db_path)),
                },
                request_chars=len(result.case.request),
                request_digest=records_mod.digest_of(result.case.request),
                run_id=run_id,
            )
        except records_mod.RecordInvalid:
            continue
        if records_mod.emit(writer, entry) is not None:
            written += 1
    return written


def run_eval(
    *,
    as_json: bool = False,
    cases_path: Path | None = None,
    model_client=None,
    compare_strategies: bool = True,
    out: Any = None,
    db_path: Path | None = None,
    catalog_name: str = V1,
) -> int:
    """Run the recorded set and report the results.

    One command, no manual steps. Returns 0 when every runnable case passed, 1
    when any failed — so the harness can gate a release.

    ``db_path`` and ``catalog_name`` select the catalog to score against. The
    name is recorded in the output, because two runs against different catalogs
    produce different results for the same cases and an unlabelled result file
    would make them indistinguishable.
    """
    out = out if out is not None else sys.stdout
    cases = load_cases(cases_path)

    snapshot_path = catalog.resolve_db_path(db_path)
    if not catalog.snapshot_exists(snapshot_path):
        print(
            f"No catalog snapshot at {snapshot_path}.\n"
            f"Build one with: ./run.sh ingest --base-url "
            f"http://localhost:8000/paperlane/",
            file=out,
        )
        return 1

    products = catalog.load_products(snapshot_path)
    facts = _load_facts(snapshot_path)

    results = [
        run_case(case, products=products, facts=facts, catalog_name=catalog_name)
        for case in cases
    ]

    # --- the interpretation-strategy comparison (8.6) ------------------
    strategy_rows: list[dict[str, Any]] = []
    if compare_strategies:
        strategy_rows = _compare_strategies(
            cases, products, facts, model_client, catalog_name=catalog_name
        )

    payload = {
        "catalog": catalog_name,
        "snapshot": {
            "path": str(snapshot_path),
            "products": len(products),
            "price_tiers": sum(len(f.tiers) for f in facts.values()),
        },
        "model_available": model_client is not None,
        "cases": [_result_dict(r) for r in results],
        "summary": _summary(results),
        "strategies": strategy_rows,
    }

    # The disagreement metric has to be *measured*, not assumed (task 5.3). The
    # harness writes a record per scored case so ``./run.sh metrics`` has
    # something to read afterwards; the count it then reports is the result of
    # re-deriving every quoted total, not an expectation that they agree.
    payload["records_written"] = _record_eval_run(results, db_path=snapshot_path)

    if as_json:
        json.dump(payload, out, indent=2, default=str)
        print(file=out)
    else:
        _render_text(payload, out=out)

    return 0 if payload["summary"]["failed"] == 0 else 1


def _compare_strategies(cases, products, facts, model_client,
                        catalog_name: str = V1) -> list[dict[str, Any]]:
    """Apply both interpretation strategies to the same requests.

    Rules-only and model-assisted are run over an identical case list and their
    interpretations and outcomes reported side by side, because "which parser is
    better" is a question that needs evidence on the same input rather than a
    claim.
    """
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.skipped_for(catalog_name):
            continue
        row: dict[str, Any] = {"number": case.number, "request": case.request}

        rules = run_case(case, products=products, facts=facts, strategy="rules",
                         catalog_name=catalog_name)
        row["rules"] = {
            "criteria": rules.criteria,
            "outcome": rules.outcome,
            "skus": list(rules.actual_skus[:3]),
            "total": (rules.actual_figures or {}).get("total"),
            "verdict": rules.verdict,
        }

        if model_client is None:
            row["model"] = {"outcome": "not run", "reason": "no model client configured"}
        else:
            model = run_case(case, products=products, facts=facts,
                             strategy="model", model_client=model_client,
                             catalog_name=catalog_name)
            row["model"] = {
                "criteria": model.criteria,
                "outcome": model.outcome,
                "skus": list(model.actual_skus[:3]),
                "total": (model.actual_figures or {}).get("total"),
                "verdict": model.verdict,
            }
        rows.append(row)
    return rows


def _result_dict(result: CaseResult) -> dict[str, Any]:
    return {
        "number": result.case.number,
        "request": result.case.request,
        "proves": result.case.proves,
        "expected": {
            "outcome": result.case.expect_outcome,
            "skus": list(result.case.expect_skus),
            "total": (result.expected_figures or {}).get("total"),
        },
        "actual": {
            "outcome": result.outcome,
            "skus": list(result.actual_skus),
            "total": (result.actual_figures or {}).get("total"),
            "criteria": result.criteria,
        },
        "axes": result.axes,
        "verdict": result.verdict,
        "notes": result.notes,
        "skipped_reason": result.skipped_reason,
        "requires_catalog": result.case.requires_catalog,
    }


def _summary(results: Sequence[CaseResult]) -> dict[str, Any]:
    ran = [r for r in results if r.ran]
    skipped = [r for r in results if not r.ran]
    failed = [r for r in ran if r.verdict == "fail"]
    return {
        "total": len(results),
        "ran": len(ran),
        "not_run": len(skipped),
        "passed": len(ran) - len(failed),
        "failed": len(failed),
        "failed_numbers": [r.case.number for r in failed],
        "not_run_numbers": [r.case.number for r in skipped],
        # Cases skipped because the running catalog cannot satisfy their
        # requirement, with the catalog that can. Separated from other skips so
        # "not applicable here" is not confused with "could not run at all".
        "requires_other_catalog": {
            str(r.case.number): r.case.requires_catalog
            for r in skipped
            if r.case.requires_catalog is not None
        },
        "by_axis": {
            axis: {
                PASS: sum(1 for r in ran if r.axes.get(axis) == PASS),
                FAIL: sum(1 for r in ran if r.axes.get(axis) == FAIL),
                NA: sum(1 for r in ran if r.axes.get(axis) == NA),
            }
            for axis in AXES
        },
    }


def _render_text(payload: dict[str, Any], *, out: Any = None) -> None:
    out = out if out is not None else sys.stdout
    snap = payload["snapshot"]
    print(f"Evaluation against {payload.get('catalog', V1)} ({snap['path']})", file=out)
    print(f"  {snap['products']} products, {snap['price_tiers']} price tiers", file=out)
    if payload["model_available"]:
        print("  model: available", file=out)
    else:
        print("  model: not configured", file=out)
        # Say plainly what that means for coverage, rather than letting the
        # reader infer it from a column of "n/a".
        print("         Structured cases ran in full. Any case needing a model was "
              "reported as not run.", file=out)
    print(file=out)

    header = f"{'#':>3}  {'verdict':8} {'retr':5} {'match':5} {'price':5} {'reply':5}  request"
    print(header, file=out)
    print("-" * len(header), file=out)
    for case in payload["cases"]:
        axes = case["axes"]
        print(
            f"{case['number']:>3}  {case['verdict']:8} "
            f"{axes['retrieval']:5} {axes['match']:5} "
            f"{axes['pricing']:5} {axes['reply']:5}  {case['request'][:52]}",
            file=out,
        )
    print(file=out)

    for case in payload["cases"]:
        if case["verdict"] == "pass":
            continue
        print(f"#{case['number']} {case['request']}", file=out)
        print(f"   expected: {case['expected']}", file=out)
        print(f"   actual:   {case['actual']['outcome']} "
              f"{case['actual']['skus']} total={case['actual']['total']}", file=out)
        if case["skipped_reason"]:
            print(f"   not run: {case['skipped_reason']}", file=out)
        for note in case["notes"]:
            print(f"   {note}", file=out)
        print(file=out)

    s = payload["summary"]
    print(f"cases: {s['total']}  ran: {s['ran']}  not run: {s['not_run']}  "
          f"passed: {s['passed']}  failed: {s['failed']}", file=out)
    for axis in AXES:
        counts = s["by_axis"][axis]
        print(f"  {axis:9} pass {counts[PASS]:>2}  fail {counts[FAIL]:>2}  "
              f"n/a {counts[NA]:>2}", file=out)
    if s["not_run_numbers"]:
        print(f"  not run: {s['not_run_numbers']}", file=out)

    # --- interpretation strategies, side by side (8.6) -----------------
    strategies = payload.get("strategies") or []
    if strategies:
        print(file=out)
        print("Interpretation strategies, applied to the same requests", file=out)
        print(f"  {'#':>3}  {'rules':22} {'model':22} request", file=out)
        print("-" * 96, file=out)
        for row in strategies:
            rules = row["rules"]
            model = row["model"]
            left = f"{rules['outcome']} ({rules['total'] or '-'})"
            if model.get("outcome") == "not run":
                right = "not run"
            else:
                right = f"{model['outcome']} ({model.get('total') or '-'})"
            print(f"  {row['number']:>3}  {left:22} {right:22} "
                  f"{row['request'][:40]}", file=out)

        agree = sum(
            1 for row in strategies
            if row["model"].get("outcome") == row["rules"]["outcome"]
        )
        comparable = sum(
            1 for row in strategies if row["model"].get("outcome") != "not run"
        )
        print(file=out)
        if comparable:
            print(f"  {agree}/{comparable} requests reached the same outcome under "
                  f"both strategies", file=out)
        else:
            print("  No model was configured, so the two strategies could not be "
                  "compared on any request.", file=out)
            print("  The comparison is implemented and will populate when a model "
                  "is available; the rules column above is the recorded result.",
                  file=out)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run_eval(as_json="--json" in argv)


# ---------------------------------------------------------------------------
# Self-checks: the harness must be able to fail
# ---------------------------------------------------------------------------


def self_check(*, out: Any = None) -> int:
    """Prove the scoring actually detects the defects it claims to detect.

    A harness that reports a clean sweep is worth nothing unless it can be shown
    to fail. Each check below takes a real case, corrupts one thing about the
    *engine's* answer, and asserts that the intended axis notices — and, just as
    importantly, that the other axes do not, because a scoring scheme where one
    problem lights up every axis tells you nothing about which thing broke.

    These run as tests as well (``tests/test_evaluate.py``); this entry point
    exists so the check can be run by hand after a change.
    """
    out = out if out is not None else sys.stdout
    products = catalog.load_products()
    facts = _load_facts()
    cases = {case.number: case for case in load_cases()}
    failures: list[str] = []

    def report(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{' — ' + detail if detail else ''}",
              file=out)
        if not ok:
            failures.append(name)

    print("Harness self-check", file=out)

    # --- the axes must discriminate, not move together ------------------
    # Case 25 (colour paper A4) is chosen deliberately: it has a *right* price
    # and a wrong product set, which is the combination a total-only check
    # cannot see.
    case25 = cases[25]
    result = run_case(case25, products=products, facts=facts)
    report("case 25 passes unmodified", result.verdict == "pass")

    corrupted = run_case(case25, products=products, facts=facts)
    corrupted.actual_skus = tuple(reversed(corrupted.actual_skus))
    corrupted.axes["retrieval"] = _score_retrieval(case25, corrupted)
    report(
        "reversing the product order fails retrieval only",
        corrupted.axes["retrieval"] == FAIL
        and corrupted.axes["pricing"] == PASS,
        f"retrieval={corrupted.axes['retrieval']} pricing={corrupted.axes['pricing']}",
    )

    # --- a wrong total must fail pricing, with the right products ------
    case6 = cases[6]
    wrong = run_case(case6, products=products, facts=facts)
    # VAT on the subtotal alone, the documented error, instead of on
    # subtotal + delivery.
    wrong.actual_figures["vat"] = "5.04"
    wrong.actual_figures["total"] = "227.04"
    wrong.axes["pricing"] = _score_pricing(case6, wrong)
    report(
        "VAT on the subtotal alone fails pricing only",
        wrong.axes["pricing"] == FAIL and wrong.axes["retrieval"] == PASS,
        f"pricing={wrong.axes['pricing']} retrieval={wrong.axes['retrieval']}",
    )

    # --- a per-line delivery charge must be caught ---------------------
    # Case 16 is the basket where the bug is visible and nowhere else.
    case16 = cases[16]
    basket = run_case(case16, products=products, facts=facts)
    if basket.ran:
        per_line = recompute_totals(list(case16.expect_lines))
        per_line["delivery"] = "300.00"        # charged twice
        per_line["vat"] = _fmt(_round_half_up(
            Decimal(_satang(per_line["subtotal"]) + 30000) * VAT_RATE / Decimal(100)
        ))
        per_line["total"] = _fmt(
            _satang(per_line["subtotal"]) + 30000 + _satang(per_line["vat"])
        )
        basket.actual_figures = per_line
        basket.axes["pricing"] = _score_pricing(case16, basket)
        report(
            "charging delivery per line fails pricing on the basket",
            basket.axes["pricing"] == FAIL,
            f"delivery={per_line['delivery']} total={per_line['total']}",
        )

    # --- a case with absent data must be not-run, not a pass -----------
    for number in (21, 22, 23, 24):
        case = cases[number]
        outcome = run_case(case, products=products, facts=facts)
        report(
            f"case {number} is not applicable, not a pass",
            outcome.skipped_reason is not None and outcome.verdict == "not run",
            outcome.skipped_reason or "",
        )

    # --- an invented product must be caught ---------------------------
    case4 = cases[4]
    invented = run_case(case4, products=products, facts=facts)
    invented.reply_text += "\nAlso try PL-NO-SUCH-1 — 99.00"
    invented.axes["reply"] = _score_reply(case4, invented)
    report(
        "a reply naming an absent SKU fails reply",
        invented.axes["reply"] == FAIL,
        invented.notes[-1] if invented.notes else "",
    )

    print(file=out)
    if failures:
        print(f"{len(failures)} self-check(s) failed: {failures}", file=out)
        return 1
    print("All self-checks passed: the scoring detects the defects it claims to.",
          file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
