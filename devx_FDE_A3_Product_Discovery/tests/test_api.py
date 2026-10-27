"""HTTP surface tests: the contracts a caller depends on.

Every test here drives the real application against the committed snapshot. No
model is configured in this environment, which is deliberate — it means the whole
suite proves the "no model available" path rather than assuming it.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperlane.api import (
    OUTCOME_REQUIRED_FIELDS,
    OUTCOMES,
    check_outcome_contract,
    create_app,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def missing_snapshot_client() -> TestClient:
    """A client pointed at a snapshot that does not exist."""
    absent = Path(tempfile.mkdtemp()) / "absent.duckdb"
    return TestClient(create_app(db_path=absent), raise_server_exceptions=False)


def ask(client: TestClient, text: str, **extra):
    """Post a request with the model disabled, so the suite is deterministic."""
    payload = {"request": text, "use_model": False}
    payload.update(extra)
    return client.post("/api/ask", json=payload)


# ---------------------------------------------------------------------------
# 6.1 Structured quoting, with no model available
# ---------------------------------------------------------------------------


class TestStructuredQuote:
    def test_returns_candidates_and_figures(self, client):
        r = client.post("/api/quote", json={"size": "A4", "weight_gsm": 80,
                                            "quantity": 20})
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"] == "quoted"
        assert body["candidates"]
        assert body["figures"]["total"]

    def test_figures_are_arithmetically_consistent(self, client):
        body = client.post(
            "/api/quote", json={"size": "A4", "weight_gsm": 80, "quantity": 20}
        ).json()
        figures = body["figures"]

        def amount(text: str) -> int:
            return int(round(float(text.replace(",", "")) * 100))

        goods = sum(amount(line["line_total"]) for line in figures["lines"])
        assert goods == amount(figures["subtotal"])
        assert amount(figures["vat"]) == round(
            (amount(figures["subtotal"]) + amount(figures["delivery"])) * 0.07
        )
        assert amount(figures["total"]) == (
            amount(figures["subtotal"])
            + amount(figures["delivery"])
            + amount(figures["vat"])
        )

    def test_no_model_is_consulted(self, client):
        body = client.post("/api/quote", json={"size": "A4"}).json()
        # The structured endpoint is model-free by construction; it says so.
        assert body["meta"]["interpretation"] == "structured"

    def test_stored_size_codes_are_accepted(self, client):
        # A structured caller sends the catalog's own codes: LTR, not "letter".
        r = client.post("/api/quote", json={
            "category": "Flyer printing", "size": "LTR", "sides": "single",
            "colour_mode": "Full colour (CMYK)", "quantity": 5,
        })
        assert r.status_code == 200
        assert r.json()["outcome"] == "quoted"

    def test_vocabulary_is_resolved_not_trusted(self, client):
        # "letter" and "LTR" must reach the same place, or the two entry points
        # disagree about the same request.
        a = client.post("/api/quote", json={"size": "letter", "quantity": 1})
        b = client.post("/api/quote", json={"size": "LTR", "quantity": 1})
        assert a.status_code == b.status_code == 200
        assert a.json()["criteria"]["size"] == b.json()["criteria"]["size"] == "LTR"


# ---------------------------------------------------------------------------
# 6.2 Conversational endpoint
# ---------------------------------------------------------------------------


class TestConversational:
    def test_returns_reply_and_structure(self, client):
        body = ask(client, "A4 copy paper, 80 gsm, 20 reams").json()
        assert body["reply"]
        assert body["candidates"]
        assert body["figures"]
        assert body["meta"]

    def test_interpretation_is_visible(self, client):
        # The task's requirement: a wrong answer must be traceable to either
        # interpretation or filtering. That needs the criteria in the response.
        body = ask(client, "A4 copy paper, 80 gsm, 20 reams").json()
        criteria = body["criteria"]
        assert criteria["size"] == "A4"
        assert criteria["weight_gsm"] == 80
        assert criteria["quantity"] == 20

    def test_interpretation_path_is_disclosed(self, client):
        body = ask(client, "A4 copy paper").json()
        assert body["meta"]["interpretation"] == "rules"
        assert "interpretation_detail" in body["meta"]

    def test_metadata_names_the_snapshot(self, client):
        body = ask(client, "A4 copy paper").json()
        snapshot = body["meta"]["snapshot"]
        assert snapshot["path"].endswith(".duckdb")
        assert snapshot["products"] == 72
        assert snapshot["price_tiers"] == 105

    def test_quantity_override_wins_over_the_text(self, client):
        body = ask(client, "A4 copy paper, 20 reams", quantity=3).json()
        assert body["criteria"]["quantity"] == 3


# ---------------------------------------------------------------------------
# 6.3 The four-outcome enum and its per-outcome fields
# ---------------------------------------------------------------------------


class TestOutcomeContract:
    def test_the_outcome_set_is_closed(self):
        assert set(OUTCOMES) == {"quoted", "clarified", "no_match", "refused"}

    def test_every_outcome_declares_required_fields(self):
        for outcome in OUTCOMES:
            assert OUTCOME_REQUIRED_FIELDS[outcome], outcome

    @pytest.mark.parametrize(
        "outcome,request_text",
        [
            ("quoted", "A4 copy paper, 80 gsm, 20 reams"),
            ("clarified", "hello there"),
            ("no_match", "paper 400 gsm"),
            ("refused", "ivory A4 paper"),
        ],
    )
    def test_each_outcome_is_reachable_with_its_fields(
        self, client, outcome, request_text
    ):
        body = ask(client, request_text).json()
        assert body["outcome"] == outcome
        assert check_outcome_contract(outcome, body) == []

    def test_a_quote_without_figures_is_a_contract_violation(self):
        problems = check_outcome_contract("quoted", {"reply": "x", "candidates": []})
        assert any("figures" in p for p in problems)
        assert any("candidates" in p for p in problems)

    def test_a_clarification_without_questions_is_a_violation(self):
        assert check_outcome_contract("clarified", {"reply": "x"})

    def test_an_unearned_price_is_a_violation(self):
        # A no-match must never carry figures: it found nothing to price.
        problems = check_outcome_contract(
            "no_match", {"reply": "x", "figures": {"total": "1.00"}}
        )
        assert any("figures" in p for p in problems)

    def test_an_unknown_outcome_is_rejected(self):
        assert check_outcome_contract("maybe", {"reply": "x"})


# ---------------------------------------------------------------------------
# 6.4 Client-error contract
# ---------------------------------------------------------------------------


class TestClientErrors:
    @pytest.mark.parametrize(
        "payload",
        [
            {"request": "   "},          # blank
            {},                          # missing
            {"request": "x" * 5000},     # too long
        ],
    )
    def test_bad_conversational_bodies_are_client_errors(self, client, payload):
        r = client.post("/api/ask", json=payload)
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "invalid_request"
        assert body["detail"]

    def test_malformed_json_is_a_client_error(self, client):
        r = client.post(
            "/api/ask", content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_request"

    @pytest.mark.parametrize("quantity", [0, -1, 999_999])
    def test_implausible_quantities_are_client_errors(self, client, quantity):
        r = client.post("/api/quote", json={"size": "A4", "quantity": quantity})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_request"

    @pytest.mark.parametrize(
        "payload,field",
        [
            ({"size": "B5"}, "size"),
            ({"category": "Tissue"}, "category"),
            ({"finish": "Holographic"}, "finish"),
        ],
    )
    def test_invalid_criteria_name_the_field(self, client, payload, field):
        r = client.post("/api/quote", json=payload)
        assert r.status_code == 422
        body = r.json()
        assert body["error"] == "invalid_request"
        assert body["field"] == field

    def test_no_stack_trace_is_exposed(self, client):
        r = client.post("/api/quote", json={"size": "B5"})
        text = r.text.lower()
        for leak in ("traceback", "file \"", "site-packages", "paperlane/api"):
            assert leak not in text, leak

    def test_error_shape_is_uniform(self, client):
        # Two different error sources — our own validation and the framework's —
        # must produce the same shape, or a caller has to parse two formats.
        ours = client.post("/api/quote", json={"size": "B5"}).json()
        framework = client.post("/api/ask", json={}).json()
        for body in (ours, framework):
            assert body["error"] == "invalid_request"
            assert "detail" in body

    def test_unknown_sku_names_the_sku(self, client):
        r = client.post(
            "/api/quote/lines", json={"lines": [{"sku": "PL-FAKE-1", "quantity": 1}]}
        )
        assert r.status_code == 422
        assert "PL-FAKE-1" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 6.5 Missing snapshot
# ---------------------------------------------------------------------------


class TestMissingSnapshot:
    def test_ask_reports_the_remedy(self, missing_snapshot_client):
        r = ask(missing_snapshot_client, "A4 paper")
        assert r.status_code == 503
        body = r.json()
        assert body["error"] == "no_snapshot"
        # The requirement: the remedy must be *stated*, not implied.
        assert "run.sh ingest" in body["remedy"]
        assert body["snapshot_path"].endswith(".duckdb")

    def test_quote_reports_the_remedy(self, missing_snapshot_client):
        r = missing_snapshot_client.post("/api/quote", json={"size": "A4"})
        assert r.status_code == 503
        assert "run.sh ingest" in r.json()["remedy"]

    def test_products_reports_the_remedy(self, missing_snapshot_client):
        r = missing_snapshot_client.get("/api/products")
        assert r.status_code == 503
        assert "run.sh ingest" in r.json()["remedy"]

    def test_health_is_200_but_unhealthy_with_a_remedy(self, missing_snapshot_client):
        # Health is a report, not a failure: it must answer even when the thing
        # it reports on is missing.
        r = missing_snapshot_client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["snapshot_present"] is False
        assert body["healthy"] is False
        assert "run.sh ingest" in body["remedy"]


# ---------------------------------------------------------------------------
# 6.6 Model-unavailable degradation
# ---------------------------------------------------------------------------


class TestModelDegradation:
    def test_an_unreachable_model_still_answers(self, client):
        from paperlane.model import ModelClient, ModelConfig

        # Configured but pointing nowhere: the worst realistic case, because
        # the client exists and every call will fail.
        broken = ModelClient(ModelConfig(
            base_url="http://127.0.0.1:9/v1", api_key="k", model="9inference",
        ))
        with_broken = TestClient(create_app(model_client=broken))

        r = with_broken.post(
            "/api/ask", json={"request": "A4 copy paper, 80 gsm, 20 reams"}
        )
        # A normal outcome, not a 500.
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"] == "quoted"
        assert body["meta"]["interpretation"] == "rules"
        assert "model unavailable" in body["meta"]["interpretation_detail"]

    def test_use_model_false_never_calls_out(self, client):
        body = ask(client, "A4 copy paper").json()
        assert body["meta"]["interpretation"] == "rules"
        assert body["meta"]["interpretation_detail"] == "no model client supplied"

    def test_health_reports_model_state(self, client):
        body = client.get("/api/health").json()
        assert "model_configured" in body
        assert "model_reachable" in body


# ---------------------------------------------------------------------------
# 6.7 Catalog inspection, health, comparison
# ---------------------------------------------------------------------------


class TestInspection:
    def test_health_names_the_snapshot_and_counts(self, client):
        body = client.get("/api/health").json()
        assert body["snapshot_present"] is True
        assert body["path"].endswith(".duckdb")
        assert body["products"] == 72
        assert body["price_tiers"] == 105
        assert body["healthy"] is True

    def test_products_lists_the_catalog(self, client):
        body = client.get("/api/products").json()
        assert body["count"] == 72
        assert len(body["products"]) == 72

    def test_products_filters_by_size(self, client):
        body = client.get("/api/products?size=A4").json()
        assert body["count"] > 0
        assert all(p["size_code"] == "A4" for p in body["products"])

    def test_products_filters_by_weight_range(self, client):
        body = client.get("/api/products?weight_min=100&weight_max=200").json()
        assert all(100 <= p["weight_gsm"] <= 200 for p in body["products"])

    def test_products_filters_by_stock(self, client):
        body = client.get("/api/products?in_stock_only=true").json()
        assert all(p["stock_status"] == "in_stock" for p in body["products"])
        assert body["count"] == 70        # 72 minus the two out-of-stock items

    def test_products_honours_the_limit(self, client):
        body = client.get("/api/products?limit=5").json()
        assert body["count"] == 72
        assert body["returned"] == 5
        assert len(body["products"]) == 5

    def test_diff_with_no_baseline_says_so(self, client):
        # "Nothing changed" and "nothing to compare against" are different
        # answers, and only one of them is reassuring.
        body = client.get("/api/diff").json()
        assert "comparable" in body
        if body["comparable"] is False:
            assert body["reason"]
        else:
            assert "no_change" in body


# ---------------------------------------------------------------------------
# The single page
# ---------------------------------------------------------------------------


class TestPage:
    def test_index_serves_the_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "PaperLane" in r.text

    def test_fragment_route_renders_an_outcome(self, client):
        r = client.post("/ask", data={"request": "A4 copy paper, 80 gsm, 20 reams"})
        assert r.status_code == 200
        assert "panel quoted" in r.text

    def test_fragment_escapes_the_reply(self, client):
        # The reply contains crawled text. It is untrusted input and must never
        # be interpreted as markup.
        r = client.post("/ask", data={"request": "<script>alert(1)</script> A4"})
        assert "<script>alert(1)</script>" not in r.text

    def test_fragment_rejects_a_bad_quantity(self, client):
        r = client.post("/ask", data={"request": "A4 paper", "quantity": "0"})
        assert "Bad quantity" in r.text

    def test_fragment_handles_a_blank_request(self, client):
        r = client.post("/ask", data={"request": "   "})
        assert "Need a request" in r.text


# ---------------------------------------------------------------------------
# Multi-line quoting
# ---------------------------------------------------------------------------


class TestMultiLine:
    def test_prices_several_skus_with_one_delivery_charge(self, client):
        body = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80", "quantity": 20},
            {"sku": "PL-PR-A4-MT-100-10", "quantity": 5},
        ]}).json()
        # PR7: delivery is charged once per order, not once per line. The
        # per-line bug was measured at 321.00 too high on this very basket.
        assert body["figures"]["delivery"] == "0.00"
        assert len(body["figures"]["lines"]) == 2

    def test_delivery_is_charged_once_below_the_threshold(self, client):
        body = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80", "quantity": 1},
            {"sku": "PL-CP-A4-80-ECO", "quantity": 1},
        ]}).json()
        assert body["figures"]["delivery"] == "150.00"

    def test_empty_line_list_is_rejected(self, client):
        r = client.post("/api/quote/lines", json={"lines": []})
        assert r.status_code == 422

    def test_an_out_of_stock_line_is_refused(self, client):
        # BUG.md A22. PR8 is unconditional: this path prices known SKUs through
        # pricing.quote() and never consulted stock, so it returned 200 with a
        # total for an item that cannot ship.
        body = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CL-A4-100-IVY", "quantity": 1},
        ]}).json()
        assert body["outcome"] == "refused"
        assert "figures" not in body
        assert check_outcome_contract(body["outcome"], body) == []
        refused = body["refused"]
        assert [item["sku"] for item in refused] == ["PL-CL-A4-100-IVY"]
        assert refused[0]["available"] is False
        assert refused[0]["stock_status"] == "out_of_stock"
        # The price is still stated, as it is on /api/ask, so the page and the
        # quote can be compared for an out-of-stock row too.
        assert refused[0]["unit_price"] == "168.00"

    def test_a_basket_with_one_unavailable_line_prices_nothing(self, client):
        """One unorderable line refuses the order rather than silently dropping it.

        Quoting the rest and omitting the line would give a total the customer
        reads as complete. Nothing is priced until the basket is orderable.
        """
        body = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80", "quantity": 1},
            {"sku": "PL-CL-A4-100-IVY", "quantity": 1},
        ]}).json()
        assert body["outcome"] == "refused"
        assert "figures" not in body
        assert [item["sku"] for item in body["refused"]] == ["PL-CL-A4-100-IVY"]

    def test_the_refusal_names_every_unavailable_line(self, client):
        body = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CL-A4-100-IVY", "quantity": 1},
            {"sku": "PL-PR-A4-GL-170-44", "quantity": 2},
        ]}).json()
        assert body["outcome"] == "refused"
        assert sorted(item["sku"] for item in body["refused"]) == [
            "PL-CL-A4-100-IVY", "PL-PR-A4-GL-170-44",
        ]
        assert all(item["available"] is False for item in body["refused"])

    def test_a_fully_available_basket_still_quotes(self, client):
        body = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80", "quantity": 20},
        ]}).json()
        assert body["outcome"] == "quoted"
        assert body["figures"]["lines"][0]["sku"] == "PL-CP-A4-80"


# ---------------------------------------------------------------------------
# docs/api.md (6.8)
# ---------------------------------------------------------------------------


class TestDocumentedExamples:
    """Every example in docs/api.md is executed here.

    A documented example that has never been run is a guess. These tests are what
    keep the document honest.
    """

    def test_documented_ask_example(self, client):
        r = client.post("/api/ask", json={
            "request": "A4 copy paper, 80 gsm, 20 reams", "use_model": False,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["outcome"] == "quoted"
        assert body["criteria"] == {
            "category": "Copy paper", "size": "A4",
            "weight_gsm": 80, "quantity": 20,
        }

    def test_documented_quote_example(self, client):
        r = client.post("/api/quote", json={
            "category": "Flyer printing", "size": "LTR", "sides": "double",
            "colour_mode": "Full colour (CMYK)", "quantity": 5,
        })
        assert r.status_code == 200
        assert r.json()["outcome"] == "quoted"

    def test_documented_clarify_example(self, client):
        body = ask(client, "I need colour").json()
        assert body["outcome"] == "clarified"
        assert body["questions"]

    def test_documented_refusal_example(self, client):
        body = ask(client, "ivory A4 paper").json()
        assert body["outcome"] == "refused"
        assert body["refused"]

    def test_documented_no_match_example(self, client):
        body = ask(client, "paper 400 gsm").json()
        assert body["outcome"] == "no_match"
        assert "figures" not in body

    def test_documented_error_example(self, client):
        body = client.post("/api/quote", json={"size": "B5"}).json()
        assert body == {
            "error": "invalid_request",
            "detail": "B5 is a paper size this catalog does not stock",
            "field": "size",
        }

    def test_documented_health_example(self, client):
        body = client.get("/api/health").json()
        for key in ("snapshot_present", "path", "products", "price_tiers",
                    "healthy", "model_configured"):
            assert key in body

    def test_documented_lines_example(self, client):
        body = client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80", "quantity": 20},
            {"sku": "PL-PR-A4-MT-100-10", "quantity": 5},
        ]}).json()
        assert body["outcome"] == "quoted"
        assert body["figures"]["delivery"] == "0.00"


# ---------------------------------------------------------------------------
# The serve entry point
# ---------------------------------------------------------------------------


class TestServeEntryPoint:
    def test_refuses_to_start_without_a_snapshot(self, monkeypatch, tmp_path):
        # Starting a service whose every request 503s is worse than not
        # starting: the operator sees "running" and the users see nothing.
        from paperlane import catalog as catalog_module

        monkeypatch.setattr(
            catalog_module, "DEFAULT_DB_PATH", Path(tmp_path) / "absent.duckdb"
        )
        from paperlane.api import run_server

        assert run_server(port=0) == 1

    def test_the_default_port_does_not_collide_with_the_served_site(self):
        # The site is served on 8000. Binding the app there would fail.
        from paperlane.cli import build_parser

        args = build_parser().parse_args(["serve"])
        assert args.port != 8000


# ---------------------------------------------------------------------------
# Regression: the quantity question must reach the production path
# ---------------------------------------------------------------------------


class TestQuantityQuestionIsLive:
    """The clarification branch must work through the API, not only in tests.

    This was a real defect. `_quantity_changes_the_answer` read tier data from
    ``product["tiers"]``, which ``load_products()`` does not populate — tiers
    live in the price facts. Tests passed because they passed a ``product_tiers``
    argument the API never supplied, so the branch was dead in production and
    only alive under test. Asking for a budget with no quantity silently returned
    a quote at quantity 1 instead of asking.
    """

    def test_asking_with_a_budget_but_no_quantity_clarifies(self, client):
        body = ask(client, "letter-size, under 250 a pack").json()
        assert body["outcome"] == "clarified"
        assert any(q["field"] == "quantity" for q in body["questions"])

    def test_a_budget_that_every_quantity_meets_does_not_ask(self, client):
        # The guard that keeps the question honest: if the verdict is the same
        # at every quantity, the question cannot change the answer.
        body = ask(client, "A4 copy paper under 250 a pack").json()
        assert body["outcome"] == "quoted"
        assert not any(q["field"] == "quantity"
                       for q in body.get("questions", []))

    def test_supplying_the_quantity_produces_a_quote(self, client):
        body = ask(client, "letter-size, under 250 a pack", quantity=20).json()
        assert body["outcome"] == "quoted"
        assert body["figures"]["total"]
