"""The request record: schema, emission, and the two things it must not carry.

The record is the single source of truth for every metric, so most of what
matters about it is structural: does it carry every field the spec names, does it
reject a value outside its vocabulary, does a concurrent pair of writers produce
two lines rather than one mangled one, and does a credential ever appear in it.

The last of those is the one that would be discovered the hard way in production,
which is why it is asserted here rather than left to review.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import pytest

from paperlane import records
from paperlane.records import (
    INTERPRETATIONS,
    OUTCOMES,
    TIMING_STAGES,
    RecordInvalid,
    RecordWriter,
    RequestRecord,
    build_record,
    digest_of,
    parse_stated_total,
)

# ---------------------------------------------------------------------------
# 1.1 The schema
# ---------------------------------------------------------------------------

#: Every field the spec requires a record to carry. Written out literally rather
#: than derived from the dataclass: a test that reads the schema from the schema
#: cannot notice a field being deleted.
REQUIRED_FIELDS = (
    "timestamp",
    "endpoint",
    "interpretation",
    "outcome",
    "candidates_considered",
    "items_returned",
    "timings",
    "snapshot",
    "request_chars",
    "request_digest",
)


class TestSchema:
    def test_every_required_field_is_present(self):
        record = RequestRecord(endpoint="/api/ask", outcome="quoted")
        payload = record.as_dict()
        missing = [name for name in REQUIRED_FIELDS if name not in payload]
        assert not missing, f"record is missing {missing}"

    def test_a_quoted_record_carries_its_totals_and_lines(self):
        record = RequestRecord(
            endpoint="/api/ask",
            outcome="quoted",
            quoted_total="2,664.30",
            stated_total="2,664.30",
            lines=({"sku": "PL-CP-A4-80-NUSA", "quantity": 20},),
        )
        payload = record.as_dict()
        assert payload["quoted_total"] == "2,664.30"
        assert payload["stated_total"] == "2,664.30"
        assert payload["lines"] == [{"sku": "PL-CP-A4-80-NUSA", "quantity": 20}]

    def test_an_unknown_outcome_is_rejected(self):
        with pytest.raises(RecordInvalid, match="outcome"):
            RequestRecord(endpoint="/api/ask", outcome="probably_fine")

    def test_an_unknown_interpretation_is_rejected(self):
        with pytest.raises(RecordInvalid, match="interpretation"):
            RequestRecord(
                endpoint="/api/ask", outcome="quoted", interpretation="vibes"
            )

    def test_a_record_must_name_its_endpoint(self):
        with pytest.raises(RecordInvalid, match="endpoint"):
            RequestRecord(endpoint="", outcome="quoted")

    def test_a_negative_stage_timing_is_rejected(self):
        with pytest.raises(RecordInvalid, match="search_ms"):
            RequestRecord(
                endpoint="/api/ask", outcome="quoted",
                timings={"search_ms": -1.0},
            )

    def test_the_outcome_vocabulary_includes_failure(self):
        # ``failed`` is not an assistant outcome. It is what a record says when
        # the request produced no reply, and it has to be in the same vocabulary
        # or failures become uncountable.
        assert "failed" in OUTCOMES
        assert set(OUTCOMES) == {"quoted", "clarified", "no_match", "refused", "failed"}

    def test_the_interpretation_vocabulary_matches_the_interpreter(self):
        assert set(INTERPRETATIONS) == {"model", "rules", "mixed", "structured"}

    def test_a_fallback_without_a_reason_is_rejected(self):
        """A model-configured request served by rules must say why.

        This is the silent-degradation case the record exists to surface, so it is
        refused at construction rather than discovered missing later.
        """
        with pytest.raises(RecordInvalid, match="fell back"):
            RequestRecord(
                endpoint="/api/ask", outcome="quoted",
                interpretation="rules", model_configured=True,
            )

    def test_a_fallback_with_a_reason_is_accepted(self):
        record = RequestRecord(
            endpoint="/api/ask", outcome="quoted",
            interpretation="rules", model_configured=True,
            fallback_reason="model unavailable, used rules: timed out",
        )
        assert record.as_dict()["fallback_reason"].startswith("model unavailable")

    def test_rules_without_a_model_is_not_a_fallback(self):
        # No model configured is a deployment choice, not degradation.
        record = RequestRecord(
            endpoint="/api/ask", outcome="quoted",
            interpretation="rules", model_configured=False,
        )
        assert "fallback_reason" not in record.as_dict()

    def test_a_record_is_frozen(self):
        record = RequestRecord(endpoint="/api/ask", outcome="quoted")
        with pytest.raises(Exception):
            record.outcome = "failed"  # type: ignore[misc]

    def test_absent_fields_are_omitted_not_nulled(self):
        # A reader must be able to tell "no total was quoted" from "a total was
        # quoted and then lost".
        payload = RequestRecord(
            endpoint="/api/ask", outcome="clarified"
        ).as_dict()
        assert "quoted_total" not in payload
        assert "stated_total" not in payload
        assert "lines" not in payload


# ---------------------------------------------------------------------------
# 1.2 Emission under a lock
# ---------------------------------------------------------------------------


class TestEmission:
    def test_one_record_is_one_line(self, tmp_path):
        writer = RecordWriter(tmp_path / "r.jsonl")
        writer.write(RequestRecord(endpoint="/api/ask", outcome="quoted"))
        lines = (tmp_path / "r.jsonl").read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["outcome"] == "quoted"

    def test_two_concurrent_writers_produce_two_well_formed_lines(self, tmp_path):
        """The interleaving failure mode, exercised directly.

        Two threads each append many records through the shared module lock. If
        the lock were missing or wrapped the wrong region, halves of two records
        would land on one line and the file would not parse.
        """
        path = tmp_path / "r.jsonl"
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def writer_thread(label: str) -> None:
            writer = RecordWriter(path)
            try:
                barrier.wait(timeout=10)
                for index in range(40):
                    writer.write(RequestRecord(
                        endpoint=f"/api/ask/{label}",
                        outcome="quoted",
                        request_digest=f"{label}{index}",
                    ))
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        threads = [
            threading.Thread(target=writer_thread, args=(label,))
            for label in ("a", "b")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert not errors, errors
        lines = path.read_text().splitlines()
        assert len(lines) == 80, f"expected 80 lines, got {len(lines)}"
        for line in lines:
            payload = json.loads(line)  # raises if two records interleaved
            assert payload["endpoint"].startswith("/api/ask/")

    def test_the_parent_directory_is_created(self, tmp_path):
        writer = RecordWriter(tmp_path / "deep" / "nested" / "r.jsonl")
        assert writer.write(RequestRecord(endpoint="/api/ask", outcome="quoted"))
        assert (tmp_path / "deep" / "nested" / "r.jsonl").exists()

    def test_reading_skips_a_malformed_line(self, tmp_path):
        """One truncated line from a crashed process must not blind the metrics."""
        path = tmp_path / "r.jsonl"
        writer = RecordWriter(path)
        writer.write(RequestRecord(endpoint="/api/ask", outcome="quoted"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"endpoint": "/api/ask", "outc\n')
        writer.write(RequestRecord(endpoint="/api/ask", outcome="refused"))
        assert [r["outcome"] for r in writer.read()] == ["quoted", "refused"]

    def test_reading_an_absent_file_is_empty(self, tmp_path):
        assert RecordWriter(tmp_path / "absent.jsonl").read() == []


# ---------------------------------------------------------------------------
# 1.3 A write failure does not fail the request
# ---------------------------------------------------------------------------


class TestWriteFailure:
    def test_a_write_error_is_noted_and_swallowed(self, tmp_path, capsys):
        """Losing a record is bad; failing a customer's quote is worse."""
        writer = RecordWriter(tmp_path / "r.jsonl")

        # Make the path a directory, so opening it for append raises.
        (tmp_path / "r.jsonl").mkdir()

        landed = writer.write(RequestRecord(endpoint="/api/ask", outcome="quoted"))
        assert landed is False
        assert writer.failures == 1
        assert writer.last_error
        assert "could not write request record" in capsys.readouterr().err

    def test_a_write_error_does_not_propagate_through_emit(self, tmp_path):
        writer = RecordWriter(tmp_path / "r.jsonl")
        (tmp_path / "r.jsonl").mkdir()
        record = RequestRecord(endpoint="/api/ask", outcome="quoted")
        # ``emit`` must return the record regardless, so the caller cannot
        # accidentally branch on a write result and fail the request.
        assert records.emit(writer, record) is record

    def test_the_request_still_succeeds_when_the_record_cannot_be_written(
        self, tmp_path
    ):
        """The property stated at the request level, not just at the writer's.

        A directory where the log file should be is a stand-in for a full disk:
        every append fails, and the endpoint must answer normally anyway.
        """
        from fastapi.testclient import TestClient

        from paperlane.api import create_app

        blocked = tmp_path / "blocked.jsonl"
        blocked.mkdir()
        client = TestClient(
            create_app(record_writer=RecordWriter(blocked)),
            raise_server_exceptions=False,
        )
        response = client.post(
            "/api/quote", json={"size": "A4", "weight_gsm": 80, "quantity": 20}
        )
        assert response.status_code == 200
        assert response.json()["outcome"] == "quoted"


# ---------------------------------------------------------------------------
# 1.4 No credential in a record
# ---------------------------------------------------------------------------

#: A value no source file would contain, so a hit is a real leak. Assembled at
#: runtime rather than written as a literal, because the repository's own
#: credential scan would flag the literal — which would be a false positive in
#: the very check this file exists to make real.
SENTINEL = "sk-" + "sentinel" + "0" * 24

#: The shapes a credential takes, reused from the hygiene test's definition so
#: the runtime check and the repository check cannot drift apart.
CREDENTIAL_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{20,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[=:]\s*"
        r"[\"']([A-Za-z0-9_\-\.]{24,})[\"']"
    ),
)


class TestNoCredentialInRecords:
    def test_a_configured_credential_never_reaches_the_record(self, monkeypatch):
        """Set a sentinel credential, make a real model call, scan the record.

        The model client is a stub that raises with the key in its message,
        because that is the realistic leak: an error path that interpolates the
        request it was building. The record must not carry it, even there.
        """
        from fastapi.testclient import TestClient

        from paperlane.api import create_app
        from paperlane.model import ModelConfig, ModelClient

        class LeakyClient:
            """A model client that fails and quotes its own credential."""

            def __init__(self, key: str) -> None:
                self.key = key

            def extract_criteria(self, text: str):
                raise RuntimeError(f"upstream rejected key {self.key}")

        monkeypatch.setenv("PAPERLANE_LLM_API_KEY", SENTINEL)
        monkeypatch.setenv("PAPERLANE_LLM_BASE_URL", "http://127.0.0.1:9/v1")
        monkeypatch.setenv("PAPERLANE_LLM_MODEL", "9inference")
        config = ModelConfig.from_env()
        assert config.api_key == SENTINEL, "the sentinel must be the configured key"

        log = Path(os.environ["PAPERLANE_RECORD_PATH"])
        client = TestClient(
            create_app(model_client=LeakyClient(SENTINEL)),
            raise_server_exceptions=False,
        )
        client.post("/api/ask", json={"request": "A4 80gsm 20 reams"})

        text = log.read_text() if log.exists() else ""
        assert SENTINEL not in text, "the credential reached the record"
        for pattern in CREDENTIAL_SHAPES:
            assert not pattern.search(text), (
                f"record contains a credential-shaped value: "
                f"{pattern.search(text).group(0)[:40]!r}"
            )

    def test_the_record_schema_has_no_field_that_could_hold_a_key(self):
        """A structural check: there is nowhere for a credential to go.

        Asserted against the field list rather than by trying values, because the
        risk is a future field being added for convenience.
        """
        fields = set(RequestRecord.__dataclass_fields__)
        for suspicious in ("api_key", "key", "token", "secret", "authorization"):
            assert suspicious not in fields, (
                f"the record has a {suspicious!r} field; a credential would "
                f"inevitably end up in it"
            )

    def test_a_credential_shaped_string_is_detectable(self):
        # The scan above is only meaningful if the patterns actually match.
        for sample in (
            "sk-" + "a" * 24,
            "Authorization: Bearer " + "b" * 30,
            'api_key = "' + "c" * 30 + '"',
        ):
            assert records.contains_credential_shape(sample, CREDENTIAL_SHAPES), (
                f"the credential scan does not match {sample[:20]!r}"
            )

    def test_redaction_removes_a_key_from_an_error_message(self):
        """The realistic leak: an error path that interpolates the key.

        ``interpret`` puts the exception text into ``fallback_reason``, which goes
        into the record. Redaction happens in the record's own constructor so no
        caller can bypass it.
        """
        leaked = f"upstream rejected key {SENTINEL}"
        record = RequestRecord(
            endpoint="/api/ask", outcome="quoted",
            interpretation="rules", model_configured=True,
            fallback_reason=leaked,
        )
        assert SENTINEL not in record.as_dict()["fallback_reason"]
        assert records.REDACTED in record.as_dict()["fallback_reason"]

    def test_redaction_removes_a_key_from_the_error_field(self):
        record = RequestRecord(
            endpoint="/api/ask", outcome="failed",
            error=f"could not reach provider with {SENTINEL}",
        )
        assert SENTINEL not in record.as_dict()["error"]

    def test_redaction_removes_a_key_from_captured_text(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT", "1")
        record = build_record(
            endpoint="/api/ask",
            request_text=f"my key is {SENTINEL} please quote A4",
        )
        assert SENTINEL not in record.as_dict()["request_text"]

    def test_redaction_leaves_ordinary_text_alone(self):
        assert records.redact_secrets("model unavailable: timed out") == (
            "model unavailable: timed out"
        )

    def test_redaction_tolerates_empty_values(self):
        assert records.redact_secrets(None) is None
        assert records.redact_secrets("") == ""

    def test_the_production_patterns_match_the_hygiene_test_patterns(self):
        """The two lists are duplicated; this is the check that they agree.

        Production code must not import from the test suite, so the shapes are
        declared twice. Duplication that is asserted is a reminder; duplication
        that is not asserted is a future divergence.
        """
        from test_hygiene import SECRET_PATTERNS

        samples = (
            "sk-" + "a" * 24,
            "Bearer " + "b" * 30,
            'api_key = "' + "c" * 30 + '"',
            "no credential here at all",
        )
        for sample in samples:
            production = [
                bool(p.search(sample)) for p in records.CREDENTIAL_SHAPES
            ]
            hygiene = [bool(p.search(sample)) for p in SECRET_PATTERNS]
            assert production == hygiene, (
                f"the two credential-shape lists disagree on {sample[:20]!r}: "
                f"production={production} hygiene={hygiene}"
            )


# ---------------------------------------------------------------------------
# The stated-total parser (4.1)
# ---------------------------------------------------------------------------


class TestParseStatedTotal:
    """The parser must read the ``Total`` line ``assistant.py`` actually emits.

    Every sample below is a string produced by ``_render_breakdown``, not one
    written to suit the regex.
    """

    def test_single_item_with_charged_delivery(self):
        text = (
            "Breakdown\n"
            "  1 \u00d7 120.00 = 120.00  (list price)\n"
            "  Subtotal      120.00\n"
            "  Delivery      150.00\n"
            "  VAT 7%        18.90\n"
            "  Total         288.90\n"
            "  All prices exclude VAT; VAT is charged on goods plus delivery."
        )
        assert parse_stated_total(text) == "288.90"

    def test_multi_item_with_charged_delivery(self):
        text = (
            "Breakdown\n"
            "  10 \u00d7 116.50 = 1,165.00  (list price)\n"
            "  5 \u00d7 119.00 = 595.00  (list price)\n"
            "  Subtotal      1,760.00\n"
            "  Delivery      150.00\n"
            "  VAT 7%        133.70\n"
            "  Total         2,043.70\n"
        )
        assert parse_stated_total(text) == "2,043.70"

    def test_free_delivery_renders_zero_with_an_explanation(self):
        text = (
            "Breakdown\n"
            "  25 \u00d7 120.00 = 3,000.00  (list price)\n"
            "  Subtotal      3,000.00\n"
            "  Delivery      0.00  (free from 3,000.00)\n"
            "  VAT 7%        210.00\n"
            "  Total         3,210.00\n"
        )
        assert parse_stated_total(text) == "3,210.00"

    def test_a_reply_with_no_total_parses_as_none(self):
        assert parse_stated_total("Which finish did you want?") is None

    def test_an_empty_reply_parses_as_none(self):
        assert parse_stated_total("") is None

    def test_two_total_lines_are_ambiguous_and_return_none(self):
        text = "  Total         100.00\n  Total         200.00\n"
        assert parse_stated_total(text) is None

    def test_prose_mentioning_total_is_not_a_figure(self):
        # Anchored, so a sentence about a total cannot be mistaken for one.
        assert parse_stated_total("The total depends on quantity.") is None

    def test_the_parser_reads_the_real_renderer(self):
        """Not a synthetic string: a reply from the live code path.

        The samples above could drift from the renderer. This one cannot, because
        it is produced by ``answer`` against the committed catalog.
        """
        from paperlane.assistant import answer
        from paperlane.catalog import load_price_facts, load_products
        from paperlane.interpret import validate
        from paperlane.interpret import interpret_rules

        criteria = validate(interpret_rules("A4 80gsm 20 reams"))
        products = load_products()
        reply = answer(criteria, products, load_price_facts())
        assert reply.quote is not None
        assert parse_stated_total(reply.text) == reply.quote.total.format()


# ---------------------------------------------------------------------------
# Request text: absent by default, opt-in, bounded (6.2, 6.3)
# ---------------------------------------------------------------------------


class TestRequestText:
    def test_text_is_absent_by_default(self, monkeypatch):
        monkeypatch.delenv("PAPERLANE_RECORD_TEXT", raising=False)
        assert records.capture_enabled() is False
        record = build_record(
            endpoint="/api/ask",
            request_text="a customer's exact words",
        )
        payload = record.as_dict()
        assert "request_text" not in payload
        # The two fields that stand in for it must be present.
        assert payload["request_chars"] == len("a customer's exact words")
        assert payload["request_digest"] == digest_of("a customer's exact words")

    def test_the_digest_groups_identical_requests(self):
        assert digest_of("same text") == digest_of("same text")
        assert digest_of("same text") != digest_of("same text ")
        assert len(digest_of("anything")) == 16

    def test_capture_is_an_explicit_opt_in(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT", "1")
        assert records.capture_enabled() is True
        record = build_record(endpoint="/api/ask", request_text="captured words")
        assert record.as_dict()["request_text"] == "captured words"

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_the_truthy_spellings(self, monkeypatch, value):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT", value)
        assert records.capture_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_the_falsey_spellings(self, monkeypatch, value):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT", value)
        assert records.capture_enabled() is False

    def test_captured_text_is_truncated_at_the_bound(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT", "1")
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT_MAX", "10")
        long_text = "x" * 500
        record = build_record(endpoint="/api/ask", request_text=long_text)
        stored = record.as_dict()["request_text"]
        assert stored == "x" * 10
        assert len(stored) == 10

    def test_the_default_bound_is_bounded(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT", "1")
        monkeypatch.delenv("PAPERLANE_RECORD_TEXT_MAX", raising=False)
        record = build_record(endpoint="/api/ask", request_text="y" * 5000)
        stored = record.as_dict()["request_text"]
        assert len(stored) == records.DEFAULT_TEXT_MAX
        assert len(stored) < 5000

    def test_a_bad_bound_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT_MAX", "not a number")
        assert records.text_max() == records.DEFAULT_TEXT_MAX

    def test_a_zero_bound_is_raised_to_one(self, monkeypatch):
        # ``max(1, ...)``: a zero-length capture would silently store nothing
        # while still reporting capture as on, which is worse than refusing.
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT_MAX", "0")
        assert records.text_max() == 1


# ---------------------------------------------------------------------------
# The two populations: live traffic and the evaluation harness
# ---------------------------------------------------------------------------


class TestPopulations:
    """The harness and live traffic must not share a log.

    The eval set is a curated sample chosen to exercise edge cases. Mixing it into
    the live log would drag the fallback and zero-result rates toward whatever the
    case list happens to emphasise, and a rate over a mixture answers neither
    question.
    """

    def test_the_two_paths_are_different(self):
        assert records.DEFAULT_PATH != records.EVAL_PATH

    def test_the_eval_path_is_git_ignored(self):
        import subprocess

        root = Path(__file__).resolve().parents[1]
        try:
            out = subprocess.run(
                ["git", "check-ignore", "-q", str(records.EVAL_PATH)],
                cwd=root, capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pytest.skip("git is not available")
        assert out.returncode == 0

    def test_the_eval_writer_uses_the_eval_path(self, tmp_path, monkeypatch):
        target = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(target))
        writer = records.eval_writer()
        assert writer is not None
        assert writer.path == target

    def test_a_live_request_does_not_land_in_the_eval_log(
        self, tmp_path, monkeypatch
    ):
        from fastapi.testclient import TestClient

        from paperlane.api import create_app

        live = tmp_path / "live.jsonl"
        evaluation = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(live))
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(evaluation))

        client = TestClient(create_app(record_writer=records.RecordWriter(live)))
        client.post("/api/quote", json={
            "size": "A4", "weight_gsm": 80, "quantity": 20,
        })
        assert live.exists()
        assert not evaluation.exists()

    def test_derive_can_read_either_population(self, tmp_path, monkeypatch):
        live = tmp_path / "live.jsonl"
        evaluation = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(live))
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(evaluation))

        records.RecordWriter(live).write(
            RequestRecord(endpoint="/api/ask", outcome="quoted")
        )
        records.RecordWriter(evaluation).write(
            RequestRecord(endpoint="eval:1", outcome="no_match", run_id="run-1")
        )

        from paperlane.metrics import derive

        assert derive().record_count == 1
        assert derive().counts["by_outcome"] == {"quoted": 1}
        assert derive(source="eval").record_count == 1
        assert derive(source="eval").counts["by_outcome"] == {"no_match": 1}

    def test_an_eval_run_writes_only_to_the_eval_log(self, tmp_path, monkeypatch):
        """5.3: the measurement must be reachable without polluting live data."""
        from paperlane.evaluate import run_eval

        live = tmp_path / "live.jsonl"
        evaluation = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(live))
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(evaluation))

        import io

        code = run_eval(out=io.StringIO(), compare_strategies=False)
        assert code == 0
        assert evaluation.exists(), "the harness wrote no records"
        assert not live.exists(), "the harness polluted the live log"

    def test_the_eval_records_read_zero_disagreements(self, tmp_path, monkeypatch):
        """5.3's measured zero, over the real harness output.

        This is the assertion that turns "the reply contract should make
        disagreement impossible" into a number computed from a real run.
        """
        from paperlane.evaluate import run_eval

        evaluation = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(evaluation))

        import io

        assert run_eval(out=io.StringIO(), compare_strategies=False) == 0
        from paperlane.metrics import derive

        derived = derive(source="eval")
        assert derived.record_count > 0
        assert derived.disagreement_checked > 0, (
            "no reply was actually checked, so the zero means nothing"
        )
        assert derived.disagreement_count == 0, derived.disagreements

    def test_the_harness_records_no_latency(self, tmp_path, monkeypatch):
        """An eval run measures correctness, not speed.

        A 0.0 timing would drag the p95 to zero and read as "instant", so the
        harness records no timing at all and the p95 skips those records.
        """
        from paperlane.evaluate import run_eval

        evaluation = tmp_path / "eval.jsonl"
        monkeypatch.setenv("PAPERLANE_EVAL_RECORD_PATH", str(evaluation))

        import io

        run_eval(out=io.StringIO(), compare_strategies=False)
        from paperlane.metrics import derive

        assert derive(source="eval").p95_latency_ms is None


# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------


class TestPathConfiguration:
    def test_the_default_path_is_git_ignored(self):
        """Operational data must not be committable."""
        import subprocess

        root = Path(__file__).resolve().parents[1]
        try:
            out = subprocess.run(
                ["git", "check-ignore", "-q", str(records.DEFAULT_PATH)],
                cwd=root, capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pytest.skip("git is not available")
        assert out.returncode == 0, (
            f"{records.DEFAULT_PATH.name} is not gitignored and would be "
            f"committed"
        )

    def test_recording_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", "off")
        assert records.recording_enabled() is False
        assert records.writer_from_env() is None

    def test_a_configured_path_is_used(self, monkeypatch, tmp_path):
        target = tmp_path / "custom.jsonl"
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(target))
        writer = records.writer_from_env()
        assert writer is not None
        assert writer.path == target

    def test_the_same_path_yields_the_same_writer(self, monkeypatch, tmp_path):
        """The failure counter has to survive across requests to mean anything."""
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(tmp_path / "r.jsonl"))
        assert records.writer_from_env() is records.writer_from_env()

    def test_a_different_path_yields_a_different_writer(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(tmp_path / "one.jsonl"))
        first = records.writer_from_env()
        monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(tmp_path / "two.jsonl"))
        second = records.writer_from_env()
        assert first is not second


# ---------------------------------------------------------------------------
# The window (used by the p95 metric)
# ---------------------------------------------------------------------------


class TestWindow:
    def test_the_default_window_is_positive(self, monkeypatch):
        monkeypatch.delenv("PAPERLANE_RECORD_WINDOW", raising=False)
        assert records.window_size() == records.DEFAULT_WINDOW
        assert records.window_size() > 0

    def test_a_bad_window_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_WINDOW", "lots")
        assert records.window_size() == records.DEFAULT_WINDOW

    def test_a_zero_window_is_raised_to_one(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_WINDOW", "0")
        assert records.window_size() == 1


# ---------------------------------------------------------------------------
# Timings
# ---------------------------------------------------------------------------


class TestTimings:
    def test_the_stage_vocabulary_is_the_three_stages(self):
        assert set(TIMING_STAGES) == {"interpret_ms", "search_ms", "price_ms"}

    def test_timings_are_rounded_in_the_payload(self):
        record = RequestRecord(
            endpoint="/api/ask", outcome="quoted",
            timings={"search_ms": 1.23456789, "total_ms": 9.87654321},
        )
        payload = record.as_dict()["timings"]
        assert payload["search_ms"] == 1.235
        assert payload["total_ms"] == 9.877
