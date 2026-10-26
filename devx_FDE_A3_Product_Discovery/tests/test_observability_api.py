"""Observability wired into the request path: what gets recorded, and what does not.

The distinction these tests defend is the one the design argues for: only the
requests that interpret and quote produce records. Recording a health check would
dilute the fallback and zero-result rates with traffic that structurally cannot
exhibit either, which turns a health measure into noise.

Everything here drives the real application. No handler is called directly, so
what is asserted is what a caller would actually cause.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperlane import records
from paperlane.api import create_app
from paperlane.records import RecordWriter


@pytest.fixture()
def log(tmp_path: Path) -> Path:
    """The record file this test's requests will be written to."""
    return tmp_path / "requests.jsonl"


@pytest.fixture()
def client(log: Path) -> TestClient:
    return TestClient(create_app(record_writer=RecordWriter(log)))


def read(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line]


# ---------------------------------------------------------------------------
# 2.1 /api/ask
# ---------------------------------------------------------------------------


class TestAskRecord:
    def test_a_successful_ask_produces_one_record(self, client, log):
        response = client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        assert response.status_code == 200
        entries = read(log)
        assert len(entries) == 1
        assert entries[0]["endpoint"] == "/api/ask"
        assert entries[0]["outcome"] == "quoted"

    def test_the_record_states_the_interpretation_path(self, client, log):
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        entry = read(log)[0]
        assert entry["interpretation"] == "rules"
        assert entry["model_configured"] is False

    def test_a_model_configured_fallback_records_a_reason(self, log):
        """The silent-degradation case, at the request level.

        A model is configured and the rule path serves the request anyway. The
        record must say why, or the fallback is invisible — which is the exact
        failure this whole change exists to prevent.
        """
        class FailingClient:
            def extract_criteria(self, text: str):
                raise RuntimeError("provider returned 503")

        client = TestClient(create_app(
            model_client=FailingClient(), record_writer=RecordWriter(log)
        ))
        response = client.post("/api/ask", json={"request": "A4 80gsm 20 reams"})
        assert response.status_code == 200

        entry = read(log)[0]
        assert entry["model_configured"] is True
        assert entry["interpretation"] == "rules"
        assert entry.get("fallback_reason"), (
            "a model-configured request served by rules recorded no reason"
        )
        assert "503" in entry["fallback_reason"]

    def test_a_model_served_request_records_no_fallback_reason(self, log):
        """The other side of the assertion: no reason when nothing fell back.

        Without this, a record that always carried a reason would pass the test
        above while telling the reader nothing.
        """
        from paperlane.model import ModelResult

        class WorkingClient:
            def extract_criteria(self, text: str):
                # ``ModelResult.criteria`` is the raw model dict, which
                # ``interpret`` merges onto the rule pass.
                return ModelResult(criteria={"size_code": "A4"}, strategy="stub")

        client = TestClient(create_app(
            model_client=WorkingClient(), record_writer=RecordWriter(log)
        ))
        response = client.post("/api/ask", json={"request": "A4 paper please"})
        assert response.status_code == 200

        entry = read(log)[0]
        assert entry["model_configured"] is True
        assert entry["interpretation"] in ("model", "mixed")
        assert "fallback_reason" not in entry

    def test_the_record_carries_the_candidate_and_item_counts(self, client, log):
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        entry = read(log)[0]
        assert entry["candidates_considered"] == 72
        assert entry["items_returned"] >= 1

    def test_the_record_carries_the_quoted_and_stated_totals(self, client, log):
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        entry = read(log)[0]
        assert entry["quoted_total"]
        assert entry["stated_total"] == entry["quoted_total"]
        assert entry["lines"]


# ---------------------------------------------------------------------------
# 2.2 Every quoting endpoint, and none of the inspection ones
# ---------------------------------------------------------------------------


class TestEndpointCoverage:
    def test_one_record_per_handled_request(self, client, log):
        client.post("/api/ask", json={"request": "A4 80gsm 20 reams",
                                     "use_model": False})
        client.post("/api/quote", json={"size": "A4", "weight_gsm": 80,
                                        "quantity": 20})
        client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80-NUSA", "quantity": 10},
        ]})
        client.post("/ask", data={"request": "A4 80gsm 20 reams"})

        entries = read(log)
        assert len(entries) == 4
        assert [e["endpoint"] for e in entries] == [
            "/api/ask", "/api/quote", "/api/quote/lines", "/ask",
        ]

    def test_the_html_fragment_produces_a_record(self, client, log):
        response = client.post("/ask", data={"request": "A4 80gsm 20 reams"})
        assert response.status_code == 200
        assert len(read(log)) == 1

    @pytest.mark.parametrize("path", ["/api/products", "/api/health", "/api/diff"])
    def test_catalog_inspection_produces_no_record(self, client, log, path):
        """Recording these would dilute both rates with ineligible traffic."""
        response = client.get(path)
        assert response.status_code == 200
        assert read(log) == [], f"{path} wrote a record"

    def test_a_basket_records_its_lines(self, client, log):
        """The one endpoint that charges delivery once per order.

        Without a record it would contribute nothing to the disagreement metric,
        which is precisely the endpoint most likely to get per-order arithmetic
        wrong.
        """
        client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80-NUSA", "quantity": 10},
            {"sku": "PL-CP-A5-80", "quantity": 5},
        ]})
        entry = read(log)[0]
        assert entry["endpoint"] == "/api/quote/lines"
        assert len(entry["lines"]) == 2
        assert entry["quoted_total"]
        # Nothing was printed to a customer on this path, so no figure was
        # *stated*; the metric must not invent one.
        assert "stated_total" not in entry


# ---------------------------------------------------------------------------
# 2.3 Failed requests
# ---------------------------------------------------------------------------


class TestFailedRequests:
    def test_a_validation_error_produces_a_failure_record(self, client, log):
        """A failure with no trace is the hardest kind to count."""
        response = client.post("/api/ask", json={"request": "zzzz", "use_model": False})
        # Whatever the outcome, the request was handled and must be recorded.
        assert response.status_code in (200, 422)
        entries = read(log)
        assert len(entries) == 1, "a failed request left no record"

    def test_an_unknown_sku_is_recorded_as_a_failure(self, client, log):
        response = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-DOES-NOT-EXIST", "quantity": 1},
        ]})
        assert response.status_code == 422
        entry = read(log)[0]
        assert entry["outcome"] == "failed"
        assert "unknown SKU" in entry["error"]

    def test_a_validation_error_names_the_failure(self, client, log):
        response = client.post("/api/quote", json={
            "size": "A4", "weight_gsm": 80, "quantity": -5,
        })
        assert response.status_code == 422
        entry = read(log)[0]
        assert entry["outcome"] == "failed"
        assert entry["error"]

    def test_a_missing_snapshot_still_produces_a_record(self, tmp_path, log):
        client = TestClient(
            create_app(
                db_path=tmp_path / "absent.duckdb",
                record_writer=RecordWriter(log),
            ),
            raise_server_exceptions=False,
        )
        response = client.post("/api/ask", json={"request": "A4 80gsm",
                                                "use_model": False})
        assert response.status_code == 503
        entries = read(log)
        assert len(entries) == 1
        assert entries[0]["outcome"] == "failed"

    def test_an_empty_html_request_is_recorded(self, client, log):
        response = client.post("/ask", data={"request": "   "})
        assert response.status_code == 200
        entry = read(log)[0]
        assert entry["outcome"] == "failed"
        assert "empty request" in entry["error"]

    def test_a_bad_quantity_is_recorded(self, client, log):
        """The HTML form takes quantity as free text, so it can be nonsense."""
        response = client.post("/ask", data={"request": "A4 80gsm", "quantity": "999999"})
        assert response.status_code == 200
        entry = read(log)[0]
        assert entry["outcome"] == "failed"
        assert "quantity" in entry["error"]

    def test_an_uninterpretable_html_request_is_recorded(self, client, log):
        """``CriteriaInvalid`` returns a clarification, but it is still a miss."""
        response = client.post("/ask", data={"request": "A4 0gsm paper"})
        assert response.status_code == 200
        entry = read(log)[0]
        assert entry["outcome"] == "failed"
        assert "grammage" in entry["error"]


# ---------------------------------------------------------------------------
# 2.4 Per-stage timings
# ---------------------------------------------------------------------------


class TestStageTimings:
    def test_the_three_stages_are_recorded(self, client, log):
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        timings = read(log)[0]["timings"]
        for stage in ("interpret_ms", "search_ms", "price_ms", "total_ms"):
            assert stage in timings, f"{stage} is missing"

    def test_the_stages_do_not_exceed_the_total(self, client, log):
        """A breakdown exceeding its own total means the instrumentation is
        measuring different requests."""
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        timings = read(log)[0]["timings"]
        stage_sum = (
            timings["interpret_ms"] + timings["search_ms"] + timings["price_ms"]
        )
        assert stage_sum <= timings["total_ms"], (
            f"stages sum to {stage_sum}ms but the total is {timings['total_ms']}ms"
        )

    def test_every_stage_is_non_negative(self, client, log):
        for request in ("A4 80gsm 20 reams", "zzzz"):
            client.post("/api/ask", json={"request": request, "use_model": False})
        for entry in read(log):
            for stage, value in entry["timings"].items():
                assert value >= 0, f"{stage} is negative: {value}"

    def test_a_clarification_records_zero_for_the_stages_it_skipped(self, client, log):
        """Absent stages would make the sum untestable and "not run" ambiguous."""
        client.post("/api/ask", json={"request": "paper", "use_model": False})
        timings = read(log)[0]["timings"]
        for stage in ("interpret_ms", "search_ms", "price_ms", "total_ms"):
            assert stage in timings
        assert timings["search_ms"] == 0.0
        assert timings["price_ms"] == 0.0


# ---------------------------------------------------------------------------
# 5.1 /api/metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_an_empty_record_set_reports_as_empty(self, client):
        payload = client.get("/api/metrics").json()
        assert payload["record_count"] == 0
        assert payload["has_data"] is False
        assert payload["fallback_rate"] is None
        assert payload["zero_result_rate"] is None
        assert payload["p95_latency_ms"] is None
        assert payload["note"]

    def test_it_reports_the_five_measures(self, client):
        payload = client.get("/api/metrics").json()
        for name in (
            "fallback_rate",
            "zero_result_rate",
            "review_backlog",
            "p95_latency_ms",
            "disagreement_count",
        ):
            assert name in payload

    def test_it_reports_the_basis(self, client, log):
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        payload = client.get("/api/metrics").json()
        assert payload["record_count"] == 1
        assert payload["window"] >= 1
        assert payload["has_data"] is True

    def test_it_derives_from_the_requests_just_handled(self, client, log):
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        before = client.get("/api/metrics").json()
        assert before["record_count"] == 1

        client.post("/api/ask", json={"request": "zzzz", "use_model": False})
        after = client.get("/api/metrics").json()
        assert after["record_count"] == 2

    def test_the_metrics_endpoint_writes_no_record_of_itself(self, client, log):
        """Reading metrics is not a handled request."""
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        client.get("/api/metrics")
        client.get("/api/metrics")
        assert len(read(log)) == 1

    def test_it_does_not_fail_with_no_snapshot(self, tmp_path, log):
        client = TestClient(
            create_app(
                db_path=tmp_path / "absent.duckdb",
                record_writer=RecordWriter(log),
            ),
            raise_server_exceptions=False,
        )
        payload = client.get("/api/metrics").json()
        assert payload["review_backlog"] is None
        assert payload["has_data"] is False


# ---------------------------------------------------------------------------
# 1.3 / 6.1 Recording off, and no credential in the log
# ---------------------------------------------------------------------------


class TestRecordingOff:
    def test_a_request_succeeds_with_recording_disabled(self, log):
        client = TestClient(create_app(record_writer=None))
        response = client.post("/api/quote", json={
            "size": "A4", "weight_gsm": 80, "quantity": 20,
        })
        assert response.status_code == 200
        assert response.json()["outcome"] == "quoted"
        assert read(log) == []

    def test_metrics_still_respond_with_recording_disabled(self):
        client = TestClient(create_app(record_writer=None))
        payload = client.get("/api/metrics").json()
        assert payload["has_data"] is False


class TestNoCredentialReachesTheLog:
    #: Assembled at runtime so this repository's own credential scan does not
    #: flag the fixture that tests for leaked credentials.
    SENTINEL = "sk-" + "logcheck" + "0" * 23

    def test_a_failing_model_does_not_put_its_key_in_the_record(self, log, monkeypatch):
        """The realistic leak, driven through the real request path.

        ``interpret`` puts the exception text into the fallback detail; that
        detail becomes ``fallback_reason``; that lands in the record. If a
        provider client quotes its own key, the record must not carry it.
        """
        monkeypatch.setenv("PAPERLANE_LLM_API_KEY", self.SENTINEL)
        sentinel = self.SENTINEL  # captured: inside the class below, ``self`` is the client

        class LeakyClient:
            def extract_criteria(self, text: str):
                raise RuntimeError(f"401 for key {sentinel}")

        client = TestClient(create_app(
            model_client=LeakyClient(), record_writer=RecordWriter(log)
        ))
        client.post("/api/ask", json={"request": "A4 80gsm 20 reams"})

        text = log.read_text()
        assert self.SENTINEL not in text, "the credential reached the log"
        assert records.REDACTED in text, (
            "the credential was removed but not marked, so a reader cannot tell "
            "an error was redacted"
        )

    def test_ordinary_records_contain_no_credential_shape(self, client, log):
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        text = log.read_text()
        for pattern in records.CREDENTIAL_SHAPES:
            assert not pattern.search(text), (
                f"a record contains {pattern.search(text).group(0)[:30]!r}"
            )


# ---------------------------------------------------------------------------
# 6.2 Request text absent by default
# ---------------------------------------------------------------------------


class TestNoRequestTextByDefault:
    def test_the_text_is_absent_and_the_stand_ins_are_present(self, client, log):
        phrase = "A4 80gsm 20 reams please"
        client.post("/api/ask", json={"request": phrase, "use_model": False})
        entry = read(log)[0]
        assert "request_text" not in entry
        assert entry["request_chars"] == len(phrase)
        assert entry["request_digest"] == records.digest_of(phrase)

    def test_the_text_does_not_appear_anywhere_in_the_file(self, client, log):
        """Not just absent from the field — absent from the whole line."""
        phrase = "my very distinctive request wording"
        client.post("/api/ask", json={"request": phrase, "use_model": False})
        assert phrase not in log.read_text()

    def test_the_metrics_still_work_without_the_text(self, client, log):
        """The digest-and-length position must not cost any metric.

        All five depend on path, outcome, counts and timing — none on wording.
        """
        client.post(
            "/api/ask", json={"request": "A4 80gsm 20 reams", "use_model": False}
        )
        payload = client.get("/api/metrics").json()
        assert payload["record_count"] == 1
        assert payload["zero_result_rate"] is not None
        assert payload["review_backlog"] is not None
        assert payload["p95_latency_ms"] is not None
        assert payload["disagreement_count"] is not None

    def test_capture_can_be_opted_into_and_is_bounded(self, log, monkeypatch):
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT", "1")
        monkeypatch.setenv("PAPERLANE_RECORD_TEXT_MAX", "20")
        client = TestClient(create_app(record_writer=RecordWriter(log)))
        client.post("/api/ask", json={
            "request": "A4 80gsm " + "x" * 200, "use_model": False,
        })
        entry = read(log)[0]
        assert entry["request_text"]
        assert len(entry["request_text"]) == 20
