"""The five metrics, derived from records on every read.

**No counter is incremented while a request is handled.** Every value here is
computed by re-reading the record log, which is what makes the spec's
"computed from records, not from counters" scenario true by construction rather
than by discipline. The cost is an O(n) scan per read — microseconds at this
scale — and the benefit is that a metric cannot drift away from the events it
claims to summarise. A counter and its log can disagree; when they do, you no
longer know which one is true.

The five, and why each is worth watching:

``fallback_rate``
    The share of requests the rule interpreter served *although a model was
    configured*. Not "the share served by rules" — a deployment with no model is
    legitimately all-rules, and reporting that as degradation would make the
    metric permanently alarming and therefore ignored.

``zero_result_rate``
    The share of requests that found nothing. Clarifications and refusals are
    **not** counted: a clarification is the system correctly declining to guess,
    and a refusal is the system correctly declining to sell. Counting either as a
    miss would make the metric measure questions rather than failures.

``review_backlog``
    Pages awaiting human review after ingestion. Read from the snapshot's own
    state rather than from the records, because it is a fact about the catalog,
    not about traffic. A rise after a refresh means the site changed shape.

``p95_latency_ms``
    End-to-end latency at the 95th percentile, over the most recent N records.
    Nearest-rank, not interpolated: with small N an interpolated p95 is a number
    no request actually experienced.

``disagreement_count``
    Replies whose printed total differs from the total re-derived for the same
    lines by ``evaluate.recompute_totals``. Expected to stay zero. This is the
    only metric here that can detect a *correctness* bug rather than a
    degradation, and it is computed by a genuinely different code path — see
    :func:`disagreements`.

Two design points worth stating because they are easy to get wrong:

**An empty record set is not a healthy system.** Every rate returns ``None``
rather than ``0.0`` when there is nothing to divide by, and the payload says so.
A 0% fallback rate over zero requests looks exactly like a perfect run.

**The p95 window is a count, not a time window.** A burst can flush history.
That is a stated limitation, not an oversight — a time window needs a clock and
a retention policy, which is a bigger feature than this one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import catalog, records as records_mod

#: Alarm thresholds, stated so that "what would you watch" has an answer with a
#: number in it rather than a list of names. Each is a starting point for a real
#: deployment, not a universal constant.
THRESHOLDS = {
    "fallback_rate": 0.20,        # above this, the model is probably degraded
    "zero_result_rate": 0.10,     # above this, the catalog or the parser has a gap
    "review_backlog": 5,          # above this, a refresh changed the site's shape
    "p95_latency_ms": 2000.0,     # above this, the assistant feels slow to use
    "disagreement_count": 0,      # anything above zero is a correctness bug
}


# ---------------------------------------------------------------------------
# Individual derivations
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> float | None:
    """A proportion, or ``None`` when there is nothing to divide by.

    ``None`` rather than ``0.0`` is the whole point: an empty log must not report
    a perfect score.
    """
    if denominator <= 0:
        return None
    return numerator / denominator


def fallback_rate(records: Sequence[dict[str, Any]]) -> float | None:
    """Share of model-eligible requests that the rule path served.

    The denominator is **requests where a model was configured**, not all
    requests. A deployment with no model answers everything with rules and that
    is correct behaviour; counting it as fallback would make the metric
    permanently red and therefore invisible.
    """
    eligible = [r for r in records if r.get("model_configured")]
    fell_back = [
        r for r in eligible
        if r.get("interpretation") == "rules" and r.get("outcome") != "failed"
    ]
    return _rate(len(fell_back), len(eligible))


def zero_result_rate(records: Sequence[dict[str, Any]]) -> float | None:
    """Share of requests that found nothing.

    ``clarified`` and ``refused`` are excluded from the numerator *and* the
    denominator's intent: both are correct answers, and a system that asks a
    good question should not look like a system that failed to find anything.
    """
    answered = [
        r for r in records
        if r.get("outcome") in ("quoted", "no_match")
    ]
    missed = [r for r in answered if r.get("outcome") == "no_match"]
    return _rate(len(missed), len(answered))


def review_backlog(db_path=None) -> int | None:
    """Pages awaiting review, straight from the snapshot.

    Not derived from records: this is a fact about the catalog, and reading it
    from the snapshot is what makes it reflect the *current* one rather than
    whatever was true when the last request was handled.
    """
    try:
        info = catalog.health(db_path)
    except Exception:  # noqa: BLE001 - a metrics read must never raise
        return None
    if not info.get("snapshot_present"):
        return None
    open_items = int(info.get("open_review_items") or 0)
    carried = int(info.get("carried_review_items") or 0)
    return open_items + carried


def p95_latency(records: Sequence[dict[str, Any]]) -> float | None:
    """Nearest-rank 95th percentile of end-to-end latency.

    Nearest-rank rather than interpolated: with a small window an interpolated
    p95 reports a duration between two observed requests, which is a number no
    request experienced. The nearest-rank value is always a real measurement.

    ``None`` on an empty window, so "no data" never renders as "0ms".
    """
    values = sorted(
        float(r["timings"]["total_ms"])
        for r in records
        if isinstance(r.get("timings"), dict)
        and isinstance(r["timings"].get("total_ms"), (int, float))
    )
    if not values:
        return None
    rank = max(1, math.ceil(0.95 * len(values)))
    return values[rank - 1]


@dataclass
class Comparison:
    """The disagreement measurement, with the basis it was taken over.

    ``checked`` is how many records actually had a printed total to verify. It
    travels with the count because "0 disagreements" over 0 checked records and
    "0 disagreements" over 17 checked records are very different claims, and
    without the basis the payload cannot tell them apart.
    """

    checked: int = 0
    disagreements: list[dict[str, Any]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.disagreements)


def compare(records: Sequence[dict[str, Any]], *, db_path=None) -> Comparison:
    """Re-derive every quoted reply's total and report where it disagrees.

    For each record whose reply printed a total, that figure is compared against
    ``evaluate.recompute_totals`` run on the same SKUs and quantities. That
    function was written from the published pricing rules and is separately
    asserted (by source inspection) not to call ``quote()`` — so this is a
    comparison between two implementations, not a reply agreeing with itself.

    A record that printed a total but cannot be re-derived is reported as a
    disagreement *with a reason*, not skipped. Silently dropping the records that
    cannot be checked would make the metric look better the less it was able to
    do, which is the wrong direction for a health measure to fail in.
    """
    from .evaluate import recompute_totals

    result = Comparison()
    for record in records:
        stated = record.get("stated_total")
        if stated is None:
            # No printed total, so nothing to check. Not a disagreement: a
            # clarification or a refusal correctly prints no total at all.
            continue
        result.checked += 1
        lines = record.get("lines")
        if not lines:
            result.disagreements.append({
                "endpoint": record.get("endpoint"),
                "digest": record.get("request_digest"),
                "stated": stated,
                "reason": "reply stated a total but recorded no lines to re-derive from",
            })
            continue
        try:
            expected = recompute_totals(list(lines))
        except Exception as exc:  # noqa: BLE001 - an unpriceable line is a finding
            result.disagreements.append({
                "endpoint": record.get("endpoint"),
                "digest": record.get("request_digest"),
                "stated": stated,
                "reason": f"could not re-derive: {type(exc).__name__}: {exc}",
            })
            continue
        if expected["total"] != stated:
            result.disagreements.append({
                "endpoint": record.get("endpoint"),
                "digest": record.get("request_digest"),
                "stated": stated,
                "recomputed": expected["total"],
                "lines": list(lines),
                "reason": "stated total differs from the recomputed total",
            })
    return result


def disagreements(
    records: Sequence[dict[str, Any]], *, db_path=None
) -> list[dict[str, Any]]:
    """Just the disagreement entries. See :func:`compare` for the basis."""
    return compare(records, db_path=db_path).disagreements
    return found


# ---------------------------------------------------------------------------
# The whole picture
# ---------------------------------------------------------------------------


@dataclass
class Metrics:
    """The five measures, with the basis they were computed from.

    ``record_count`` and ``window`` travel with the values because a rate of
    zero over zero records is indistinguishable from a healthy system. Reporting
    the basis is how the reader tells them apart.
    """

    record_count: int = 0
    window: int = 0
    fallback_rate: float | None = None
    zero_result_rate: float | None = None
    review_backlog: int | None = None
    p95_latency_ms: float | None = None
    disagreement_count: int | None = None
    #: How many records actually carried a printed total to verify. Reported
    #: beside the count so "0 over 0 checked" cannot pass for "0 over 17".
    disagreement_checked: int = 0
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    #: Which snapshot the backlog figure came from, and how many records carry
    #: each outcome — enough for a reader to sanity-check the basis.
    snapshot: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    #: Which population these numbers describe, and — for an eval run — which
    #: run. Without it a report cannot say what it measured.
    source: str = "live"
    run_id: str | None = None

    @property
    def has_data(self) -> bool:
        return self.record_count > 0

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "record_count": self.record_count,
            "window": self.window,
            "has_data": self.has_data,
            "fallback_rate": self.fallback_rate,
            "zero_result_rate": self.zero_result_rate,
            "review_backlog": self.review_backlog,
            "p95_latency_ms": self.p95_latency_ms,
            "disagreement_count": self.disagreement_count,
            "disagreement_checked": self.disagreement_checked,
            "thresholds": dict(THRESHOLDS),
            "snapshot": self.snapshot,
            "counts": self.counts,
            "source": self.source,
        }
        if self.run_id:
            payload["run_id"] = self.run_id
        # The empty case says so in words. A caller that only reads the numbers
        # would see nulls; a human reading the JSON sees why.
        if not self.has_data:
            payload["note"] = (
                "no requests recorded yet, so no rate is reported — a rate over "
                "zero records would look like a healthy system"
            )
        if self.disagreements:
            payload["disagreements"] = self.disagreements
        return payload

    def alarms(self) -> list[str]:
        """Which thresholds are currently exceeded. Empty is the good case."""
        raised: list[str] = []
        for name, limit in THRESHOLDS.items():
            value = getattr(self, name, None)
            if value is None:
                continue
            if name == "disagreement_count":
                if value > limit:
                    raised.append(f"{name}: {value} > {limit}")
            elif value > limit:
                raised.append(f"{name}: {value:.3f} > {limit}")
        return raised


def derive(
    *,
    writer: "records_mod.RecordWriter | None" = None,
    db_path=None,
    window: int | None = None,
    source: str = "live",
    run_id: str | None = None,
) -> Metrics:
    """Read the records and compute every metric from them.

    The window applies to the latency figure only. The rates use the whole log,
    because they are proportions rather than tail statistics and a truncated
    denominator would make a rare outcome vanish; latency is the one where
    recency is the point.

    ``source`` selects which population to read: ``"live"`` for the requests the
    service handled, ``"eval"`` for the records the evaluation harness wrote.
    They are separate on purpose — see ``records.EVAL_PATH`` — and a caller has
    to say which one it wants rather than silently receiving a mixture.

    For ``source="eval"`` with no ``run_id``, the most recent run is read. The
    eval log accumulates across runs, and the negative control deliberately fails,
    so a union of runs would describe no single run at all.
    """
    window = window if window is not None else records_mod.window_size()
    if writer is not None:
        everything = writer.read()
    elif source == "eval":
        everything = records_mod.eval_records(run_id)
    else:
        everything = records_mod.all_records()
    recent = everything[-window:] if window and len(everything) > window else everything

    try:
        info = catalog.health(db_path)
    except Exception:  # noqa: BLE001
        info = {}

    comparison = compare(everything, db_path=db_path)

    return Metrics(
        record_count=len(everything),
        window=window,
        fallback_rate=fallback_rate(everything),
        zero_result_rate=zero_result_rate(everything),
        review_backlog=review_backlog(db_path),
        p95_latency_ms=p95_latency(recent),
        # ``None`` over an empty log, for the same reason the rates are: "zero
        # disagreements" and "nothing to disagree with" must not read the same.
        # Once there are records, 0 is a real measurement — it means every
        # quotable reply was checked and agreed.
        disagreement_count=comparison.count if everything else None,
        disagreement_checked=comparison.checked,
        disagreements=comparison.disagreements,
        snapshot={
            "path": info.get("path"),
            "products": info.get("products"),
            "built_at": (info.get("last_ingest") or {}).get("finished_at"),
            # The catalog's age, reported beside the review backlog — the other
            # snapshot-derived measure. Not a sixth metric: the brief asks for the
            # measures worth watching, and "how old is this catalog" is a fact
            # about the snapshot rather than a rate over records.
            "freshness": info.get("freshness"),
        },
        counts=records_mod.summarise(everything),
        source=source,
        run_id=run_id or (
            records_mod.latest_eval_run(everything) if source == "eval" else None
        ),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_rate(value: float | None) -> str:
    return "no data" if value is None else f"{value:.1%}"


def _fmt_ms(value: float | None) -> str:
    return "no data" if value is None else f"{value:.0f}ms"


def _fmt_int(value: int | None) -> str:
    return "no data" if value is None else str(value)


def render(metrics: Metrics, *, out=None) -> None:
    """Print the five measures with the basis they came from."""
    import sys

    out = out if out is not None else sys.stdout

    if not metrics.has_data:
        print("No requests recorded yet — no metrics to report.", file=out)
        print(
            "That is not a zero rate: a proportion over zero records would look "
            "like a healthy system.",
            file=out,
        )
        if metrics.source == "eval":
            print(
                f"No records for run {metrics.run_id or 'unknown'} in "
                f"{records_mod.eval_path()}.",
                file=out,
            )
            print(
                "Run ./run.sh eval to produce some, or ./run.sh metrics --eval "
                "for the most recent run.",
                file=out,
            )
        else:
            print(
                f"Records are written to {records_mod.record_path()} when the "
                "service handles a request.",
                file=out,
            )
        fresh = (metrics.snapshot or {}).get("freshness") or {}
        if fresh.get("age_human"):
            # The catalog's age does not depend on traffic, so it is reported
            # here too rather than being hidden behind an empty record log.
            flag = "  STALE" if fresh.get("stale") else ""
            print(
                f"  catalog age: {fresh['age_human']}"
                f"  (stale above {fresh['stale_after_hours']:g}h){flag}",
                file=out,
            )
        return

    print(f"Records: {metrics.record_count}  (p95 window: {metrics.window})", file=out)
    if metrics.source == "eval":
        # Which run these numbers describe. The eval log accumulates across runs
        # — including the negative control, whose purpose is to fail — so a
        # report that did not name its run could not be checked against anything.
        print(
            f"Source: evaluation harness, run {metrics.run_id or 'unknown'}",
            file=out,
        )
    print(file=out)
    rows = (
        ("interpretation fallback rate", _fmt_rate(metrics.fallback_rate),
         f"alarm above {THRESHOLDS['fallback_rate']:.0%}"),
        ("zero-result rate", _fmt_rate(metrics.zero_result_rate),
         f"alarm above {THRESHOLDS['zero_result_rate']:.0%}"),
        ("extraction review backlog", _fmt_int(metrics.review_backlog),
         f"alarm above {THRESHOLDS['review_backlog']}"),
        ("p95 latency", _fmt_ms(metrics.p95_latency_ms),
         f"alarm above {THRESHOLDS['p95_latency_ms']:.0f}ms"),
        ("reply/total disagreement", _fmt_int(metrics.disagreement_count),
         "alarm above 0"),
    )
    width = max(len(label) for label, _, _ in rows)
    for label, value, threshold in rows:
        print(f"  {label:<{width}}  {value:>10}   ({threshold})", file=out)

    # The basis for the disagreement figure, stated rather than implied. "0"
    # alone does not say whether 17 replies were re-derived and agreed or none
    # were ever checked, and those are opposite findings.
    print(
        f"  {'':<{width}}  {f'({metrics.disagreement_checked} checked)':>10}",
        file=out,
    )

    print(file=out)
    fresh = (metrics.snapshot or {}).get("freshness") or {}
    if fresh.get("age_human"):
        # Reported even when no requests have been recorded: how old the catalog
        # is does not depend on traffic.
        flag = "  STALE" if fresh.get("stale") else ""
        print(
            f"  catalog age: {fresh['age_human']}"
            f"  (stale above {fresh['stale_after_hours']:g}h){flag}",
            file=out,
        )
    by_outcome = metrics.counts.get("by_outcome") or {}
    if by_outcome:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(by_outcome.items()))
        print(f"  outcomes: {summary}", file=out)
    by_path = metrics.counts.get("by_interpretation") or {}
    if by_path:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(by_path.items()))
        print(f"  interpretation: {summary}", file=out)

    if metrics.disagreements:
        print(file=out)
        print("Disagreements:", file=out)
        for item in metrics.disagreements:
            print(
                f"  {item.get('endpoint')} {item.get('digest')}: "
                f"stated {item.get('stated')}, {item.get('reason')}",
                file=out,
            )

    raised = metrics.alarms()
    if raised:
        print(file=out)
        for line in raised:
            print(f"  ALARM {line}", file=out)


def run_metrics(
    *, as_json: bool = False, out=None, db_path=None, writer=None,
    source: str = "live", run_id: str | None = None,
) -> int:
    """Entry point for ``./run.sh metrics``.

    Exits 0 whether or not alarms are raised: this command reports, it does not
    gate. A non-zero exit on a threshold would make it unusable in a shell
    pipeline that legitimately continues.
    """
    import json
    import sys

    out = out if out is not None else sys.stdout
    metrics = derive(db_path=db_path, writer=writer, source=source, run_id=run_id)
    if as_json:
        json.dump(metrics.as_dict(), out, indent=2)
        print(file=out)
    else:
        render(metrics, out=out)
    return 0
