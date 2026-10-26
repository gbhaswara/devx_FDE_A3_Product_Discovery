"""The semantic layer's contract with the assistant and the HTTP surface.

Three things are asserted here that the unit tests cannot cover:

1. The **unconfigured response is unchanged** — not "orders the same way", but
   the same keys. That is what lets an existing caller ignore this capability.
2. A **failing provider still answers**, and says that it degraded.
3. The **measurement command** produces counts, and says "not measured" rather
   than reporting a zero when there is no provider.

No test here needs a network: the scorer is injected, or configured to fail.
"""

from __future__ import annotations

import io
import json

import pytest

from paperlane.assistant import answer
from paperlane.criteria import Criteria
from paperlane.embeddings import EmbeddingUnavailable
from paperlane.search import SEMANTIC_APPLIED, SEMANTIC_OFF, SEMANTIC_UNAVAILABLE


class FixedScorer:
    """Deterministic scores, so the ordering can be asserted offline."""

    degraded = False

    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    def scores(self, skus):
        return {sku: self._scores[sku] for sku in skus if sku in self._scores}


class DeadScorer:
    degraded = True

    def scores(self, skus):
        raise EmbeddingUnavailable("embedding request failed: ConnectError")


@pytest.fixture
def products():
    return [
        {
            "sku": "PL-CP-A4-80", "name": "A4 80gsm Copy Paper",
            "category": "Copy paper", "size_code": "A4", "weight_gsm": 80,
            "finish": "uncoated", "stock_status": "in_stock", "pack_sheets": 500,
            "unit_word": "Ream of 500 sheets", "on_sale": False,
            "list_price_satang": 12000, "sale_price_satang": None,
        },
        {
            "sku": "PL-CP-A4-80-ECO", "name": "A4 80gsm Copy Paper Eco",
            "category": "Copy paper", "size_code": "A4", "weight_gsm": 80,
            "finish": "uncoated", "stock_status": "in_stock", "pack_sheets": 500,
            "unit_word": "Ream of 500 sheets", "on_sale": False,
            "list_price_satang": 12000, "sale_price_satang": None,
        },
    ]


@pytest.fixture
def facts(products):
    from paperlane.money import Money
    from paperlane.pricing import PriceFacts

    return {
        p["sku"]: PriceFacts(
            sku=p["sku"], list_price=Money(p["list_price_satang"]),
            sale_price=None, tiers=(),
        )
        for p in products
    }


class TestAssistantReporting:
    def test_unconfigured_reply_reports_off_and_no_similarity(
        self, products, facts
    ):
        reply = answer(Criteria(size_code="A4", quantity=1), products, facts)
        assert reply.semantic == SEMANTIC_OFF
        assert reply.semantic_detail is None
        assert all(c.similarity is None for c in reply.candidates)

    def test_enabled_reply_reports_applied(self, products, facts):
        reply = answer(
            Criteria(size_code="A4", quantity=1), products, facts,
            scorer=FixedScorer({"PL-CP-A4-80": 0.2, "PL-CP-A4-80-ECO": 0.9}),
        )
        assert reply.semantic == SEMANTIC_APPLIED
        assert all(c.similarity is not None for c in reply.candidates)

    def test_similarity_breaks_a_price_tie(self, products, facts):
        # Both are 120.00, so similarity is the only thing that can separate
        # them — which is exactly the scope of this feature.
        reply = answer(
            Criteria(size_code="A4", quantity=1), products, facts,
            scorer=FixedScorer({"PL-CP-A4-80": 0.2, "PL-CP-A4-80-ECO": 0.9}),
        )
        assert [c.sku for c in reply.candidates][0] == "PL-CP-A4-80-ECO"

    def test_failing_provider_still_answers_and_reports_degradation(
        self, products, facts
    ):
        reply = answer(
            Criteria(size_code="A4", quantity=1), products, facts,
            scorer=DeadScorer(),
        )
        assert reply.outcome == "quoted"
        assert reply.quote is not None
        assert reply.semantic == SEMANTIC_UNAVAILABLE
        assert "ConnectError" in (reply.semantic_detail or "")
        # Degraded ordering: the pre-semantic order, which is by SKU.
        assert [c.sku for c in reply.candidates] == [
            "PL-CP-A4-80", "PL-CP-A4-80-ECO"
        ]

    def test_semantic_status_absent_from_dict_when_off(self, products, facts):
        reply = answer(Criteria(size_code="A4", quantity=1), products, facts)
        assert "semantic" not in reply.as_dict()

    def test_semantic_status_present_in_dict_when_applied(self, products, facts):
        reply = answer(
            Criteria(size_code="A4", quantity=1), products, facts,
            scorer=FixedScorer({"PL-CP-A4-80": 0.2, "PL-CP-A4-80-ECO": 0.9}),
        )
        payload = reply.as_dict()
        assert payload["semantic"] == SEMANTIC_APPLIED

    def test_similarity_does_not_appear_in_the_reply_text(self, products, facts):
        # The score is for a reviewer inspecting the structure, not for the
        # customer's prose.
        reply = answer(
            Criteria(size_code="A4", quantity=1), products, facts,
            scorer=FixedScorer({"PL-CP-A4-80": 0.123456, "PL-CP-A4-80-ECO": 0.9}),
        )
        assert "0.123" not in reply.text
        assert "similar" not in reply.text.lower()


class TestApiSurface:
    def client(self, monkeypatch, *, provider: bool):
        from fastapi.testclient import TestClient

        from paperlane.api import create_app

        if provider:
            monkeypatch.setenv("PAPERLANE_EMBED_BASE_URL", "http://localhost:9")
            monkeypatch.setenv("PAPERLANE_EMBED_MODEL", "bge-m3:latest")
        else:
            monkeypatch.delenv("PAPERLANE_EMBED_BASE_URL", raising=False)
            monkeypatch.delenv("PAPERLANE_EMBED_MODEL", raising=False)
        return TestClient(create_app())

    def test_unconfigured_response_has_no_semantic_keys(self, monkeypatch):
        client = self.client(monkeypatch, provider=False)
        body = client.post(
            "/api/quote", json={"size": "A4", "weight_gsm": 80, "quantity": 1}
        ).json()
        assert "semantic" not in body
        assert all("similarity" not in c for c in body["candidates"])

    def test_unreachable_provider_degrades_but_answers(self, monkeypatch):
        # Port 9 is the discard port; nothing listens there.
        client = self.client(monkeypatch, provider=True)
        response = client.post(
            "/api/ask", json={"request": "A4 80gsm copy paper", "use_model": False}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "quoted"
        assert body["semantic"] == SEMANTIC_UNAVAILABLE
        assert body["semantic_detail"]
        assert body["figures"]["total"]


class TestMeasurementCommand:
    def test_reports_counts_not_a_narrative(self):
        from paperlane.similarity import measure, render

        # An injected scorer keeps the comparison itself testable offline.
        def factory(text: str):
            return FixedScorer({})

        measurement = measure(scorer_factory=factory)
        assert measurement.ran == 28

        buffer = io.StringIO()
        render(measurement, out=buffer)
        text = buffer.getvalue()
        assert "Cases run: 28" in text
        assert "Cases whose order changed:" in text
        assert "Regressions" in text

    def test_equal_scores_change_nothing(self):
        from paperlane.similarity import measure

        measurement = measure(scorer_factory=lambda text: FixedScorer({}))
        assert measurement.changed_order == 0

    def test_zero_is_stated_plainly(self):
        from paperlane.similarity import measure, render

        buffer = io.StringIO()
        render(measure(scorer_factory=lambda text: FixedScorer({})), out=buffer)
        assert "inert" in buffer.getvalue()

    def test_unmeasured_is_reported_as_unmeasured(self, monkeypatch):
        from paperlane.similarity import measure, render

        monkeypatch.delenv("PAPERLANE_EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("PAPERLANE_EMBED_MODEL", raising=False)
        measurement = measure()
        buffer = io.StringIO()
        render(measurement, out=buffer)
        assert "NOT MEASURED" in buffer.getvalue()
        assert "Cases run" not in buffer.getvalue()

    def test_json_output_is_machine_readable(self):
        from paperlane.similarity import measure

        payload = measure(scorer_factory=lambda text: FixedScorer({})).as_dict()
        assert payload["cases_run"] == 28
        assert "cases_with_order_changed" in payload
        assert isinstance(payload["detail"], list)
        json.dumps(payload)  # must not raise

    def test_verdict_rule_is_declared_not_fitted(self):
        from paperlane.similarity import CaseEffect

        # Fixed before any result was seen: up is an improvement, down is a
        # regression, unchanged is neither.
        up = CaseEffect(number=1, request="r", expected_first="B", rank_off=2, rank_on=0)
        down = CaseEffect(number=2, request="r", expected_first="B", rank_off=0, rank_on=2)
        same = CaseEffect(number=3, request="r", expected_first="B", rank_off=1, rank_on=1)
        absent = CaseEffect(number=4, request="r", expected_first=None)
        assert up.verdict == "improvement"
        assert down.verdict == "regression"
        assert same.verdict == "neutral"
        assert absent.verdict == "neutral"
