"""Measure what the semantic tiebreak actually does to the recorded set.

The honest risk in a feature like this is shipping something that changes
nothing and describing it as an improvement. So this module produces a **number**
rather than a narrative: how many recorded cases change order with similarity
enabled, in which direction, and whether the change is an improvement.

What "improvement" means here, precisely — defined before any result was seen,
so the definition cannot be fitted to the outcome:

* **improvement** — the case's expected first item moves *up* under similarity.
* **regression** — the expected first item moves *down*.
* **neutral** — order unchanged, or the case has no expected first item.

Cases are counted, never eyeballed. If the count is zero, the report says zero
and the README says zero.

One subtlety worth stating because it is easy to get wrong: a case can pass its
retrieval axis and still have *changed order*. The axis checks the best match and
the set; it does not check the order of the rest. So "changed order" and "still
correct" are both reported, and a case that changes order without regressing is
exactly what a tiebreak is supposed to produce.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import catalog
from .criteria import Criteria
from .interpret import interpret_rules, validate
from .search import Candidate, search


@dataclass
class CaseEffect:
    """What enabling similarity did to one recorded case."""

    number: int
    request: str
    skus_off: tuple[str, ...] = ()
    skus_on: tuple[str, ...] = ()
    expected_first: str | None = None
    rank_off: int | None = None
    rank_on: int | None = None
    note: str = ""

    @property
    def order_changed(self) -> bool:
        return self.skus_off != self.skus_on

    @property
    def first_changed(self) -> bool:
        return bool(self.skus_off) and bool(self.skus_on) and (
            self.skus_off[0] != self.skus_on[0]
        )

    @property
    def verdict(self) -> str:
        """Improvement, regression or neutral — by the pre-declared rule."""
        if self.rank_off is None or self.rank_on is None:
            return "neutral"
        if self.rank_on < self.rank_off:
            return "improvement"
        if self.rank_on > self.rank_off:
            return "regression"
        return "neutral"


@dataclass
class Measurement:
    """The whole comparison, ready to render."""

    cases: list[CaseEffect] = field(default_factory=list)
    model: str = ""
    dimension: int | None = None
    unavailable: str | None = None

    @property
    def ran(self) -> int:
        return len(self.cases)

    @property
    def changed_order(self) -> int:
        return sum(1 for c in self.cases if c.order_changed)

    @property
    def changed_first(self) -> int:
        return sum(1 for c in self.cases if c.first_changed)

    @property
    def improvements(self) -> int:
        return sum(1 for c in self.cases if c.verdict == "improvement")

    @property
    def regressions(self) -> int:
        return sum(1 for c in self.cases if c.verdict == "regression")

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "dimension": self.dimension,
            "unavailable": self.unavailable,
            "cases_run": self.ran,
            "cases_with_order_changed": self.changed_order,
            "cases_with_first_changed": self.changed_first,
            "improvements": self.improvements,
            "regressions": self.regressions,
            "detail": [
                {
                    "number": c.number,
                    "request": c.request,
                    "order_changed": c.order_changed,
                    "first_changed": c.first_changed,
                    "verdict": c.verdict,
                    "expected_first": c.expected_first,
                    "rank_off": c.rank_off,
                    "rank_on": c.rank_on,
                    "skus_off": list(c.skus_off),
                    "skus_on": list(c.skus_on),
                    "note": c.note,
                }
                for c in self.cases
            ],
        }


def _criteria_for(case) -> Criteria:
    criteria = validate(interpret_rules(case.request))
    if case.quantity is not None:
        from dataclasses import replace

        criteria = replace(criteria, quantity=case.quantity)
    return criteria


def _order(candidates: Sequence[Candidate]) -> tuple[str, ...]:
    return tuple(c.sku for c in candidates)


def _rank_of(skus: Sequence[str], expected: str | None) -> int | None:
    if expected is None:
        return None
    try:
        return list(skus).index(expected)
    except ValueError:
        # The expected item is absent entirely — not a rank change, and calling
        # it one would disguise a membership bug as an ordering result.
        return None


def measure(
    *,
    cases_path=None,
    db_path=None,
    scorer_factory=None,
    products=None,
    facts=None,
) -> Measurement:
    """Run every recorded case twice and count the differences.

    ``scorer_factory`` takes the request text and returns a scorer or ``None``.
    It is injectable so the comparison itself can be tested without a provider —
    the measurement logic and the model are separate concerns, and only the
    latter needs to be skipped when Ollama is absent.
    """
    from .evaluate import load_cases

    cases = load_cases(cases_path)
    rows = products if products is not None else catalog.load_products(db_path)
    price_facts = facts if facts is not None else catalog.load_price_facts(db_path)

    if scorer_factory is None:
        from .embeddings import EmbeddingConfig, scorer_for

        config = EmbeddingConfig.from_env()
        if not config.configured:
            return Measurement(
                unavailable=(
                    "no embedding provider configured; set "
                    "PAPERLANE_EMBED_BASE_URL and PAPERLANE_EMBED_MODEL"
                )
            )

        def scorer_factory(text: str):
            return scorer_for(text, rows, db_path=db_path)

    measurement = Measurement()
    from .embeddings import EmbeddingConfig

    config = EmbeddingConfig.from_env()
    measurement.model = config.model

    for case in cases:
        criteria = _criteria_for(case)
        off = search(criteria, rows, price_facts)
        scorer = scorer_factory(case.request)
        on = search(criteria, rows, price_facts, scorer=scorer)

        if on.semantic == "unavailable" and measurement.unavailable is None:
            measurement.unavailable = on.semantic_detail
        # Read from the scorer that actually ran, so the figure describes the
        # vectors used rather than the configured intent.
        dimension = getattr(getattr(scorer, "_client", None), "dimension", None)
        if dimension is not None:
            measurement.dimension = dimension

        expected_first = case.expect_skus[0] if case.expect_skus else None
        effect = CaseEffect(
            number=case.number,
            request=case.request,
            skus_off=_order(off.matches),
            skus_on=_order(on.matches),
            expected_first=expected_first,
            rank_off=_rank_of(_order(off.matches), expected_first),
            rank_on=_rank_of(_order(on.matches), expected_first),
            note=case.proves,
        )
        measurement.cases.append(effect)

    return measurement


def render(measurement: Measurement, *, out=None) -> None:
    """Print the counts. A case count, not a narrative."""
    out = out if out is not None else sys.stdout

    if measurement.unavailable:
        print(f"Semantic tiebreak: NOT MEASURED — {measurement.unavailable}", file=out)
        print(
            "The ranking is the pre-semantic one. Set the two environment "
            "variables to measure the effect.",
            file=out,
        )
        return

    print(f"Model: {measurement.model}", file=out)
    print(f"Cases run: {measurement.ran}", file=out)
    print(f"Cases whose order changed: {measurement.changed_order}", file=out)
    print(f"Cases whose first result changed: {measurement.changed_first}", file=out)
    print(f"Improvements (expected item moved up): {measurement.improvements}", file=out)
    print(f"Regressions (expected item moved down): {measurement.regressions}", file=out)

    if measurement.changed_order == 0:
        print(
            "\nNo recorded case changed order. On this evaluation set the "
            "semantic tiebreak is inert — stated plainly rather than presented "
            "as a benefit.",
            file=out,
        )
        return

    print("\nCases that changed order:", file=out)
    for case in measurement.cases:
        if not case.order_changed:
            continue
        direction = {
            "improvement": "up",
            "regression": "DOWN",
            "neutral": "same rank",
        }[case.verdict]
        print(f"  {case.number:>2}  {direction:<10}  {case.request[:56]}", file=out)
        print(f"      off: {' > '.join(case.skus_off[:4]) or '(none)'}", file=out)
        print(f"      on:  {' > '.join(case.skus_on[:4]) or '(none)'}", file=out)


def run_measure(*, as_json: bool = False, cases_path=None, db_path=None, out=None) -> int:
    """Entry point for ``./run.sh similarity``."""
    import json

    measurement = measure(cases_path=cases_path, db_path=db_path)
    out = out if out is not None else sys.stdout
    if as_json:
        json.dump(measurement.as_dict(), out, indent=2)
        print(file=out)
    else:
        render(measurement, out=out)
    # Not measured is not a failure of the code; a regression is a finding, not
    # an error. The command reports, it does not gate.
    return 0
