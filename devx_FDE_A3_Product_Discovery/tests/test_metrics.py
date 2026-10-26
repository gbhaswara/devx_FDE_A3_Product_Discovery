"""The five metrics: each derived from records, each shown able to move.

The property this file exists to protect is stated in the spec as *"computed from
records, not from counters"*. Every test below therefore drives the metric through
records — writing them, deleting them, corrupting them — rather than poking a
counter. Where a metric reads zero, there is a companion test that makes it
non-zero, because a metric that has never been observed failing is
indistinguishable from one that never runs.

The disagreement metric gets the most attention: it is the only one that can
detect a *correctness* bug rather than a degradation, and it is the one most
easily written in a way that measures nothing (comparing a reply's total against
that same reply's total).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from paperlane import metrics, records
from paperlane.records import RequestRecord
from paperlane.metrics import (
    THRESHOLDS,
    Comparison,
    Metrics,
    compare,
    derive,
    disagreements,
    fallback_rate,
    p95_latency,
    review_backlog,
    render,
    run_metrics,
    zero_result_rate,
)

def _called_names(function) -> set[str]:
    """Every function name ``function`` calls, from its AST.

    Source inspection is the right tool for "this code must not call that code",
    but a substring search is the wrong implementation of it: a docstring saying
    *"unlike ``quote()``"* would fail the test while proving the opposite. The AST
    sees calls, not prose.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def record(**overrides) -> dict:
    """A plausible record payload, with the fields a metric might read.

    Built as a dict rather than a ``RequestRecord`` because the metrics read what
    is *on disk*, and a metric that only works on freshly-constructed objects
    would not be reading a log at all.
    """
    payload = {
        "timestamp": "2026-01-01T00:00:00.000+00:00",
        "endpoint": "/api/ask",
        "outcome": "quoted",
        "interpretation": "rules",
        "model_configured": False,
        "candidates_considered": 72,
        "items_returned": 1,
        "timings": {"interpret_ms": 1.0, "search_ms": 0.5, "price_ms": 0.2,
                    "total_ms": 10.0},
        "snapshot": {"path": "/tmp/catalog.duckdb", "products": 72},
        "request_chars": 20,
        "request_digest": "0123456789abcdef",
    }
    payload.update(overrides)
    return payload


def write(tmp_path: Path, *payloads: dict) -> records.RecordWriter:
    """Write records through the real writer, so the file is the real format."""
    writer = records.RecordWriter(tmp_path / "requests.jsonl")
    for payload in payloads:
        with writer.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    return writer


# ---------------------------------------------------------------------------
# 3.1 Fallback rate
# ---------------------------------------------------------------------------


class TestFallbackRate:
    def test_the_exact_proportion(self):
        """A known set yields the exact expected proportion, not approximately.

        Four model-eligible requests, one served by rules: 0.25.
        """
        records_ = [
            record(model_configured=True, interpretation="model"),
            record(model_configured=True, interpretation="mixed"),
            record(model_configured=True, interpretation="model"),
            record(model_configured=True, interpretation="rules",
                   fallback_reason="model unavailable, used rules: timed out"),
        ]
        assert fallback_rate(records_) == 0.25

    def test_all_fell_back(self):
        records_ = [
            record(model_configured=True, interpretation="rules",
                   fallback_reason="no model client supplied")
            for _ in range(3)
        ]
        assert fallback_rate(records_) == 1.0

    def test_none_fell_back(self):
        records_ = [
            record(model_configured=True, interpretation="model")
            for _ in range(5)
        ]
        assert fallback_rate(records_) == 0.0

    def test_a_deployment_without_a_model_is_not_fallback(self):
        """The distinction that keeps the metric worth watching.

        A system with no model configured answers everything with rules, and that
        is correct. Counting it as fallback would make the metric permanently
        red and therefore ignored.
        """
        records_ = [
            record(model_configured=False, interpretation="rules")
            for _ in range(10)
        ]
        assert fallback_rate(records_) is None

    def test_no_records_reports_no_data_not_zero(self):
        assert fallback_rate([]) is None

    def test_a_failed_request_is_not_counted_as_fallback(self):
        # A request that never produced a reply did not "fall back" — it failed,
        # and the failure is counted by the outcome, not by this rate.
        records_ = [
            record(model_configured=True, interpretation="rules", outcome="failed"),
            record(model_configured=True, interpretation="model"),
        ]
        assert fallback_rate(records_) == 0.0

    def test_structured_requests_are_excluded(self):
        # /api/quote never consults a model, so it cannot fall back.
        records_ = [
            record(model_configured=False, interpretation="structured"),
            record(model_configured=True, interpretation="model"),
        ]
        assert fallback_rate(records_) == 0.0


# ---------------------------------------------------------------------------
# 3.2 Zero-result rate
# ---------------------------------------------------------------------------


class TestZeroResultRate:
    def test_the_exact_proportion(self):
        records_ = [
            record(outcome="quoted"),
            record(outcome="quoted"),
            record(outcome="quoted"),
            record(outcome="no_match"),
        ]
        assert zero_result_rate(records_) == 0.25

    def test_clarification_is_not_a_zero_result(self):
        """Asking a good question is not failing to find anything.

        This is the assertion that keeps the metric measuring misses rather than
        questions.
        """
        records_ = [record(outcome="clarified") for _ in range(4)]
        assert zero_result_rate(records_) is None, (
            "a clarified request must not even enter the denominator"
        )

    def test_refusal_is_not_a_zero_result(self):
        # A refusal is the system declining to sell something unavailable — a
        # correct answer, not a miss.
        records_ = [record(outcome="refused") for _ in range(4)]
        assert zero_result_rate(records_) is None

    def test_a_mix_excludes_both_from_the_denominator(self):
        records_ = [
            record(outcome="quoted"),
            record(outcome="no_match"),
            record(outcome="clarified"),
            record(outcome="refused"),
        ]
        # One miss out of two answered (quoted + no_match) = 0.5, not 0.25.
        assert zero_result_rate(records_) == 0.5

    def test_all_missed(self):
        records_ = [record(outcome="no_match") for _ in range(3)]
        assert zero_result_rate(records_) == 1.0

    def test_no_records_reports_no_data(self):
        assert zero_result_rate([]) is None


# ---------------------------------------------------------------------------
# 3.3 Review backlog
# ---------------------------------------------------------------------------


class TestReviewBacklog:
    def test_it_equals_what_the_snapshot_reports(self):
        """Read from the snapshot, not from a cached figure."""
        from paperlane import catalog

        info = catalog.health()
        expected = int(info["open_review_items"]) + int(
            info.get("carried_review_items") or 0
        )
        assert review_backlog() == expected

    def test_it_moves_when_the_snapshot_changes(self, tmp_path):
        """The property that makes it a measurement rather than a constant.

        A snapshot with an extra unresolved review item must report a higher
        backlog than the same snapshot without it, or the metric is reading
        something other than the snapshot's own state.
        """
        import shutil

        from paperlane import catalog

        # A real copy, so the schema is exactly the committed one's.
        copy = tmp_path / "with-review.duckdb"
        shutil.copyfile(catalog.DEFAULT_DB_PATH, copy)
        baseline = review_backlog(copy)

        import duckdb

        con = duckdb.connect(str(copy))
        try:
            columns = [
                row[0] for row in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'review_items'"
                ).fetchall()
            ]
            con.execute(
                f"INSERT INTO review_items ({', '.join(columns)}) VALUES "
                f"({', '.join('?' for _ in columns)})",
                _review_row(columns),
            )
        finally:
            con.close()

        assert review_backlog(copy) == baseline + 1

    def test_an_absent_snapshot_reports_no_data(self, tmp_path):
        assert review_backlog(tmp_path / "absent.duckdb") is None


def _review_row(columns: list[str]) -> list:
    """One plausible unresolved review row, shaped to the snapshot's schema."""
    values = {
        "run_id": "test-run",
        "kind": "price",
        "url": "http://localhost:8000/paperlane/review-probe.html",
        "sku": "PL-REVIEW-PROBE",
        "reason": "test fixture",
        "raw_excerpt": "1.00",
        "resolved": False,
        "carried_from": None,
    }
    return [values.get(column) for column in columns]


# ---------------------------------------------------------------------------
# 3.4 p95 latency
# ---------------------------------------------------------------------------


class TestP95Latency:
    def test_nearest_rank_on_a_known_sequence(self):
        """Nearest-rank, computed by hand and checked against the value.

        Twenty values 1..20. Nearest rank at p95 is ceil(0.95 * 20) = 19, so the
        19th smallest — 19.0. An interpolated p95 would return 19.05, a duration
        no request experienced.
        """
        records_ = [record(timings={"total_ms": float(n)}) for n in range(1, 21)]
        value = p95_latency(records_)
        assert value == 19.0
        assert value in [r["timings"]["total_ms"] for r in records_], (
            "p95 must be an observed value, not an interpolation"
        )

    def test_the_rank_formula(self):
        # Checked against the definition for several sizes rather than one.
        for size in (1, 5, 10, 19, 20, 21, 100, 101):
            records_ = [
                record(timings={"total_ms": float(n)}) for n in range(1, size + 1)
            ]
            expected_rank = max(1, math.ceil(0.95 * size))
            assert p95_latency(records_) == float(expected_rank), (
                f"size {size}: expected rank {expected_rank}"
            )

    def test_a_single_record(self):
        assert p95_latency([record(timings={"total_ms": 42.0})]) == 42.0

    def test_an_empty_window_reports_no_data_not_zero(self):
        assert p95_latency([]) is None

    def test_records_without_a_timing_are_skipped(self):
        """An eval-only log has no latency, and must not report 0ms.

        The eval harness measures correctness, not speed. If its records carried a
        zero, the p95 would be dragged to 0 and read as "instant".
        """
        records_ = [
            record(timings={}),
            record(timings={"total_ms": 100.0}),
            record(timings={}),
        ]
        assert p95_latency(records_) == 100.0

    def test_a_window_of_only_untimed_records_reports_no_data(self):
        assert p95_latency([record(timings={}) for _ in range(3)]) is None


# ---------------------------------------------------------------------------
# 3.5 Derived on read, not accumulated
# ---------------------------------------------------------------------------


class TestDerivedOnRead:
    def test_deleting_a_record_changes_the_metric(self, tmp_path, monkeypatch):
        """The proof that the record is the source of truth.

        Delete one line from the log and the rate must move to match. If a
        counter were being maintained alongside, the two would disagree and this
        test would catch it.
        """
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(tmp_path / "r.jsonl"))
        writer = write(
            tmp_path,
            record(model_configured=True, interpretation="model"),
            record(model_configured=True, interpretation="model"),
            record(model_configured=True, interpretation="model"),
            record(model_configured=True, interpretation="rules",
                   fallback_reason="timed out"),
        )
        before = derive(writer=writer).fallback_rate
        assert before == 0.25

        # Remove the fallback line: the rate must become 0.
        lines = writer.path.read_text().splitlines()
        fallback_lines = [
            line for line in lines
            if json.loads(line)["interpretation"] == "rules"
        ]
        assert len(fallback_lines) == 1
        writer.path.write_text(
            "\n".join(line for line in lines if line not in fallback_lines) + "\n"
        )

        after = derive(writer=writer).fallback_rate
        assert after == 0.0
        assert derive(writer=writer).record_count == 3

    def test_adding_a_record_changes_the_metric(self, tmp_path):
        writer = write(tmp_path, record(outcome="quoted"))
        assert derive(writer=writer).zero_result_rate == 0.0
        write(tmp_path, record(outcome="no_match"))
        assert derive(writer=writer).zero_result_rate == 0.5

    def test_the_metrics_module_increments_no_counter(self):
        """No counter is maintained during handling.

        Checked against the module's AST rather than its text: the property is
        "no tally is incremented across calls", and a docstring mentioning the
        word "counter" is not a counter. ``Comparison.checked`` is a local tally
        inside one read — reset on every call — so it cannot drift from the
        records the way a persistent counter can.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(metrics))

        module_names = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

        # No augmented assignment against a module-level name: that is what a
        # counter is. ``THRESHOLDS`` is a constant dict and is fine.
        for node in ast.walk(tree):
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                assert node.target.id not in module_names, (
                    f"{node.target.id} is incremented at module scope; metrics "
                    f"must be derived, not accumulated"
                )

        # Nor may a module-level name be mutated in place, which is the same
        # counter by another spelling.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("append", "add", "update", "setdefault"):
                    target = node.func.value
                    if isinstance(target, ast.Name) and target.id in module_names:
                        raise AssertionError(
                            f"{target.id}.{node.func.attr}() mutates module "
                            f"state; metrics must be derived, not accumulated"
                        )

    def test_nothing_is_written_by_reading(self, tmp_path):
        writer = write(tmp_path, record())
        before = writer.path.read_text()
        derive(writer=writer)
        derive(writer=writer)
        assert writer.path.read_text() == before


# ---------------------------------------------------------------------------
# 4.2, 4.3 Disagreement: the metric that must be able to fail
# ---------------------------------------------------------------------------


class TestDisagreement:
    def _quoted(self, **overrides) -> dict:
        """A record for a real quote from the committed catalog."""
        payload = record(
            outcome="quoted",
            lines=[{"sku": "PL-CP-A4-80-NUSA", "quantity": 20}],
            quoted_total="2,664.30",
            stated_total="2,664.30",
        )
        payload.update(overrides)
        return payload

    def test_a_correct_reply_reads_zero(self, tmp_path):
        writer = write(tmp_path, self._quoted())
        comparison = compare(writer.read())
        assert comparison.count == 0
        assert comparison.checked == 1, "the record must actually be checked"

    def test_a_corrupted_stated_total_is_detected(self, tmp_path):
        """4.3: the test without which "reads zero" proves nothing.

        Alter the printed figure and the count must become non-zero *and* name
        the affected request.
        """
        writer = write(tmp_path, self._quoted(stated_total="2,664.31"))
        comparison = compare(writer.read())
        assert comparison.count == 1
        entry = comparison.disagreements[0]
        assert entry["stated"] == "2,664.31"
        assert entry["recomputed"] == "2,664.30"
        assert entry["digest"] == "0123456789abcdef"
        assert entry["endpoint"] == "/api/ask"
        assert "differs" in entry["reason"]

    def test_a_corrupted_quantity_is_detected(self, tmp_path):
        """Corrupting the lines rather than the text must also be caught.

        This is the case where the reply's *text* is right for its own lines but
        the lines recorded are not the ones priced — a bookkeeping defect rather
        than a rendering one.
        """
        writer = write(
            tmp_path,
            self._quoted(lines=[{"sku": "PL-CP-A4-80-NUSA", "quantity": 1}]),
        )
        comparison = compare(writer.read())
        assert comparison.count == 1
        assert comparison.disagreements[0]["recomputed"] != "2,664.30"

    def test_a_record_without_a_stated_total_is_not_checked(self, tmp_path):
        # A clarification prints no total; there is nothing to disagree with.
        writer = write(
            tmp_path,
            record(outcome="clarified", lines=None, quoted_total=None),
        )
        comparison = compare(writer.read())
        assert comparison.count == 0
        assert comparison.checked == 0

    def test_a_stated_total_with_no_lines_is_a_finding(self, tmp_path):
        """Dropping the un-checkable records would flatter the metric."""
        writer = write(tmp_path, self._quoted(lines=[]))
        comparison = compare(writer.read())
        assert comparison.count == 1
        assert "no lines" in comparison.disagreements[0]["reason"]

    def test_an_unpriceable_sku_is_a_finding(self, tmp_path):
        writer = write(
            tmp_path,
            self._quoted(lines=[{"sku": "PL-NOT-IN-CATALOG", "quantity": 1}]),
        )
        comparison = compare(writer.read())
        assert comparison.count == 1
        assert "could not re-derive" in comparison.disagreements[0]["reason"]

    def test_the_metric_reads_zero_across_the_recorded_evaluation_set(self):
        """4.2: measured over the real eval cases, not a synthetic sample."""
        from paperlane.evaluate import load_cases, recompute_totals
        from paperlane.assistant import answer
        from paperlane.catalog import load_price_facts, load_products
        from paperlane.interpret import interpret_rules, validate

        products = load_products()
        facts = load_price_facts()
        payloads: list[dict] = []
        for case in load_cases():
            if case.expect_outcome == "multi_line":
                continue  # no rendered reply text to parse
            try:
                criteria = validate(interpret_rules(case.request))
            except Exception:  # noqa: BLE001 - a case that cannot interpret
                continue
            reply = answer(criteria, products, facts)
            if reply.quote is None:
                continue
            payloads.append(record(
                outcome=reply.outcome,
                lines=[
                    {"sku": line.sku, "quantity": line.quantity}
                    for line in reply.quote.lines
                ],
                quoted_total=reply.quote.total.format(),
                stated_total=records.parse_stated_total(reply.text),
            ))

        assert payloads, "the eval set produced no quotable replies to check"
        comparison = compare(payloads)
        assert comparison.checked > 0
        assert comparison.count == 0, comparison.disagreements

    def test_the_comparison_is_not_the_reply_checking_itself(self, tmp_path):
        """4.4: the computation must not call the pricing engine.

        Mirrors the guarantee ``recompute_totals`` already carries. If the metric
        compared ``reply.total`` against ``reply.quote.total``, both come from one
        object and always agree — the metric would be structurally incapable of
        failing, and the corruption test above would be the only thing standing.

        Checked through the AST rather than a substring search, so a docstring
        that *mentions* ``quote()`` to explain why it is avoided does not trip it.
        """
        called = _called_names(compare)
        assert "quote" not in called, (
            "the disagreement metric calls the pricing engine; it would then be "
            "checking a bug against itself"
        )
        assert "unit_price" not in called
        # It must go through the independent arithmetic instead.
        assert "recompute_totals" in called

    def test_the_comparison_does_not_read_the_engines_own_figure(self):
        """The stronger version: it compares against ``stated``, not ``quoted``.

        ``quoted_total`` is the engine's figure. Reading it would make the metric
        agree by construction.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(compare)))
        # No string literal naming the engine's total may be used as a subscript
        # key, and no attribute access may reach it.
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value != "quoted_total", (
                    "the metric reads the engine's own total; it must compare the "
                    "printed figure against an independent re-derivation"
                )


# ---------------------------------------------------------------------------
# 5.1 The payload
# ---------------------------------------------------------------------------


class TestPayload:
    def test_an_empty_record_set_reports_as_empty(self):
        payload = Metrics().as_dict()
        assert payload["record_count"] == 0
        assert payload["has_data"] is False
        assert payload["fallback_rate"] is None
        assert payload["zero_result_rate"] is None
        assert payload["p95_latency_ms"] is None
        assert payload["disagreement_count"] is None
        assert "note" in payload, "the empty case must say so in words"

    def test_the_five_measures_are_all_present(self):
        payload = Metrics().as_dict()
        for name in (
            "fallback_rate",
            "zero_result_rate",
            "review_backlog",
            "p95_latency_ms",
            "disagreement_count",
        ):
            assert name in payload, f"the payload is missing {name}"

    def test_the_basis_travels_with_the_values(self):
        """A rate of 0 over 0 records must not look like a healthy system."""
        payload = Metrics(record_count=10, window=1000).as_dict()
        assert payload["record_count"] == 10
        assert payload["window"] == 1000
        assert payload["has_data"] is True

    def test_every_measure_has_a_threshold(self):
        """5.1's "what would you watch" answer must have a number in it."""
        for name in (
            "fallback_rate",
            "zero_result_rate",
            "review_backlog",
            "p95_latency_ms",
            "disagreement_count",
        ):
            assert name in THRESHOLDS, f"{name} has no stated alarm threshold"
            assert THRESHOLDS[name] is not None

    def test_alarms_fire_on_the_thresholds(self):
        bad = Metrics(
            record_count=10,
            fallback_rate=0.5,
            zero_result_rate=0.5,
            review_backlog=50,
            p95_latency_ms=9000.0,
            disagreement_count=3,
        )
        raised = bad.alarms()
        assert len(raised) == 5, raised

    def test_a_healthy_payload_raises_no_alarm(self):
        good = Metrics(
            record_count=10,
            fallback_rate=0.0,
            zero_result_rate=0.0,
            review_backlog=0,
            p95_latency_ms=100.0,
            disagreement_count=0,
        )
        assert good.alarms() == []

    def test_no_data_raises_no_alarm(self):
        # Nothing to compare against the threshold; alarming on absent data
        # trains people to ignore alarms.
        assert Metrics().alarms() == []


# ---------------------------------------------------------------------------
# 5.2 The command
# ---------------------------------------------------------------------------


class TestCommand:
    def test_it_states_plainly_that_there_is_no_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(tmp_path / "none.jsonl"))
        import io

        out = io.StringIO()
        assert run_metrics(out=out) == 0
        text = out.getvalue()
        assert "No requests recorded yet" in text
        assert "not a zero rate" in text

    def test_it_reports_the_record_count_with_the_measures(self, tmp_path):
        writer = write(
            tmp_path,
            record(outcome="quoted"),
            record(outcome="no_match"),
        )
        import io

        out = io.StringIO()
        assert run_metrics(out=out, writer=writer) == 0
        text = out.getvalue()
        assert "Records: 2" in text
        for label in (
            "interpretation fallback rate",
            "zero-result rate",
            "extraction review backlog",
            "p95 latency",
            "reply/total disagreement",
        ):
            assert label in text, f"the report omits {label}"

    def test_it_reports_how_many_replies_were_checked(self, tmp_path):
        """The basis for the disagreement figure, stated rather than implied."""
        writer = write(
            tmp_path,
            record(
                outcome="quoted",
                lines=[{"sku": "PL-CP-A4-80-NUSA", "quantity": 20}],
                stated_total="2,664.30",
            ),
        )
        import io

        out = io.StringIO()
        run_metrics(out=out, writer=writer)
        assert "(1 checked)" in out.getvalue()

    def test_the_json_form_is_machine_readable(self, tmp_path):
        writer = write(tmp_path, record())
        import io

        out = io.StringIO()
        assert run_metrics(as_json=True, out=out, writer=writer) == 0
        payload = json.loads(out.getvalue())
        assert payload["record_count"] == 1
        assert payload["has_data"] is True

    def test_it_exits_zero_even_when_alarms_fire(self, tmp_path):
        """It reports, it does not gate.

        A non-zero exit on a threshold would make it unusable in a shell pipeline
        that legitimately continues.
        """
        writer = write(
            tmp_path,
            *[record(outcome="no_match") for _ in range(10)],
        )
        import io

        out = io.StringIO()
        assert run_metrics(out=out, writer=writer) == 0
        assert "ALARM" in out.getvalue()


# ---------------------------------------------------------------------------
# derive() wiring
# ---------------------------------------------------------------------------


class TestDerive:
    def test_it_reads_the_configured_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(tmp_path / "requests.jsonl"))
        write(tmp_path, record(outcome="quoted"))
        assert derive().record_count == 1

    def test_the_window_applies_to_latency_only(self, tmp_path):
        """Rates use the whole log; latency uses the recent window.

        A truncated denominator would make a rare outcome vanish from a rate,
        while latency is the one where recency is the point.
        """
        writer = write(
            tmp_path,
            record(outcome="no_match", timings={"total_ms": 1000.0}),
            record(outcome="quoted", timings={"total_ms": 5.0}),
            record(outcome="quoted", timings={"total_ms": 5.0}),
        )
        derived = derive(writer=writer, window=2)
        assert derived.record_count == 3
        # p95 over the last two records only: both 5.0, not the 1000.0.
        assert derived.p95_latency_ms == 5.0
        # The rate still sees all three.
        assert derived.zero_result_rate == 1 / 3

    def test_a_missing_snapshot_does_not_raise(self, tmp_path):
        writer = write(tmp_path, record())
        derived = derive(writer=writer, db_path=tmp_path / "absent.duckdb")
        assert derived.review_backlog is None
        assert derived.record_count == 1

    def test_the_snapshot_identity_is_reported(self, tmp_path):
        writer = write(tmp_path, record())
        derived = derive(writer=writer)
        assert derived.snapshot["path"]
        assert derived.snapshot["products"] == 72

    def test_the_counts_are_reported(self, tmp_path):
        writer = write(
            tmp_path,
            record(outcome="quoted", interpretation="model"),
            record(outcome="no_match", interpretation="rules"),
        )
        derived = derive(writer=writer)
        assert derived.counts["by_outcome"] == {"quoted": 1, "no_match": 1}
        assert derived.counts["by_interpretation"] == {"model": 1, "rules": 1}

    def test_a_live_read_reports_its_source(self, tmp_path):
        writer = write(tmp_path, record())
        assert derive(writer=writer).source == "live"
        assert derive(writer=writer).run_id is None


# ---------------------------------------------------------------------------
# One eval run, not a union of runs
# ---------------------------------------------------------------------------


class TestEvalRunSelection:
    """The eval log accumulates; a report must describe one run.

    The negative control writes to the same log and deliberately fails, so a
    union of runs would describe no run at all — and the reported numbers would
    silently change every time the harness was re-run.
    """

    def _log(self, tmp_path, monkeypatch, *runs: tuple[str, str]):
        """Write ``(run_id, outcome)`` records to an isolated eval log."""
        target = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(target))
        writer = records.RecordWriter(target)
        for run_id, outcome in runs:
            writer.write(RequestRecord(
                endpoint="eval:1", outcome=outcome, run_id=run_id,
            ))
        return target

    def test_the_most_recent_run_is_what_is_reported(self, tmp_path, monkeypatch):
        self._log(
            tmp_path, monkeypatch,
            ("run-a", "quoted"), ("run-a", "quoted"),
            ("run-b", "no_match"),
        )
        derived = derive(source="eval")
        assert derived.record_count == 1, "the report mixed two runs"
        assert derived.run_id == "run-b"
        assert derived.counts["by_outcome"] == {"no_match": 1}

    def test_a_named_run_is_read_exactly(self, tmp_path, monkeypatch):
        self._log(
            tmp_path, monkeypatch,
            ("run-a", "quoted"), ("run-b", "no_match"),
        )
        derived = derive(source="eval", run_id="run-a")
        assert derived.record_count == 1
        assert derived.run_id == "run-a"
        assert derived.counts["by_outcome"] == {"quoted": 1}

    def test_an_unknown_run_reports_no_data(self, tmp_path, monkeypatch):
        self._log(tmp_path, monkeypatch, ("run-a", "quoted"))
        derived = derive(source="eval", run_id="does-not-exist")
        assert derived.record_count == 0
        assert derived.has_data is False

    def test_a_run_without_an_id_is_ignored(self, tmp_path, monkeypatch):
        """A record with no run id cannot be attributed to a run."""
        target = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(target))
        records.RecordWriter(target).write(
            RequestRecord(endpoint="eval:1", outcome="quoted")
        )
        assert derive(source="eval").record_count == 0
        assert derive(source="eval").has_data is False

    def test_the_empty_eval_report_names_the_eval_path(self, tmp_path, monkeypatch):
        target = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(target))
        import io

        out = io.StringIO()
        run_metrics(out=out, source="eval")
        text = out.getvalue()
        assert str(target) in text, (
            "the empty eval report points at the live log, which is the wrong file"
        )

    def test_two_harness_runs_are_told_apart(self, tmp_path, monkeypatch):
        """The property stated end to end, through the real harness."""
        from paperlane.evaluate import run_eval

        target = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(target))

        import io

        assert run_eval(out=io.StringIO(), compare_strategies=False) == 0
        first = derive(source="eval").run_id
        assert run_eval(out=io.StringIO(), compare_strategies=False) == 0
        second = derive(source="eval").run_id

        assert first and second and first != second
        # The whole file holds both runs; the report holds one.
        every = records._read_path(target)
        assert len(every) > derive(source="eval").record_count
