"""The optional semantic layer: the client, the receipt checks, the cache.

The property this file exists to defend is that **the semantic layer cannot
change which products come back** — only their order — and that it is absent,
not merely inert, when no provider is configured.

Nothing here reaches the network unless a test is marked ``needs_embedding``.
The suite must pass under ``unshare -rn``, where loopback is down, and an
unconditional embed call would break that.
"""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import needs_embedding

from paperlane.embeddings import (
    CACHE,
    NORM_TOLERANCE,
    SEMANTIC_APPLIED,
    SEMANTIC_OFF,
    SEMANTIC_UNAVAILABLE,
    CacheKey,
    EmbeddingClient,
    EmbeddingConfig,
    EmbeddingUnavailable,
    SemanticScorer,
    cosine,
    product_text,
    scorer_for,
)
from paperlane.search import RANKING_ORDER, _rank_key, search
from paperlane.criteria import Criteria


# ---------------------------------------------------------------------------
# A stub transport, so the client can be tested without a provider
# ---------------------------------------------------------------------------


def stub_client(handler, *, timeout: float = 2.0) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)


def config(base_url: str = "http://localhost:11434", model: str = "bge-m3") -> EmbeddingConfig:
    return EmbeddingConfig(base_url=base_url, model=model)


def unit_vector(width: int = 4, index: int = 0) -> list[float]:
    """A genuinely unit-length basis vector."""
    vector = [0.0] * width
    vector[index] = 1.0
    return vector


def ok(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# ---------------------------------------------------------------------------
# 1.1 / 1.5 Configuration: absent, half-configured, no credential
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_absent_configuration_is_unconfigured(self, monkeypatch):
        monkeypatch.delenv("PAPERLANE_EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("PAPERLANE_EMBED_MODEL", raising=False)
        assert EmbeddingConfig.from_env().configured is False

    def test_half_configuration_is_unconfigured(self, monkeypatch):
        # A guessed model name would score against a model the operator did not
        # choose, which is worse than not scoring at all.
        monkeypatch.setenv("PAPERLANE_EMBED_BASE_URL", "http://localhost:11434")
        monkeypatch.delenv("PAPERLANE_EMBED_MODEL", raising=False)
        assert EmbeddingConfig.from_env().configured is False

        monkeypatch.delenv("PAPERLANE_EMBED_BASE_URL", raising=False)
        monkeypatch.setenv("PAPERLANE_EMBED_MODEL", "bge-m3")
        assert EmbeddingConfig.from_env().configured is False

    def test_unconfigured_scorer_is_none_and_attempts_no_call(self, monkeypatch):
        monkeypatch.delenv("PAPERLANE_EMBED_BASE_URL", raising=False)
        monkeypatch.delenv("PAPERLANE_EMBED_MODEL", raising=False)

        def explode(request):  # pragma: no cover - must never run
            raise AssertionError("no network call may be attempted when unconfigured")

        assert scorer_for(
            "A4 copy paper", [{"sku": "X"}],
            client=EmbeddingClient(config("", ""), client=stub_client(explode)),
        ) is None

    def test_unconfigured_client_refuses_without_network(self):
        def explode(request):  # pragma: no cover - must never run
            raise AssertionError("no network call may be attempted when unconfigured")

        client = EmbeddingClient(config("", ""), client=stub_client(explode))
        with pytest.raises(EmbeddingUnavailable):
            client.embed(["anything"])

    def test_no_authorization_header_is_sent(self):
        seen = {}

        def handler(request):
            seen["headers"] = dict(request.headers)
            return ok({"embeddings": [unit_vector()]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        client.embed(["paper"])
        assert "authorization" not in {k.lower() for k in seen["headers"]}

    def test_no_api_key_setting_exists(self):
        # The endpoint is local; there is no key to read, so there is none to
        # leak. Asserting the absence keeps a future "just add an API key"
        # change from quietly introducing a credential path.
        assert not hasattr(EmbeddingConfig.from_env(), "api_key")


# ---------------------------------------------------------------------------
# 1.2 The request and response shape
# ---------------------------------------------------------------------------


class TestWireShape:
    def test_request_body_is_model_and_input(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return ok({"embeddings": [unit_vector(), unit_vector(index=1)]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        client.embed(["one", "two"])
        assert seen["url"].endswith("/api/embed")
        assert seen["body"] == {"model": "bge-m3", "input": ["one", "two"]}

    def test_embeddings_parse_into_float_vectors(self):
        def handler(request):
            # ints in the response, floats out: JSON does not distinguish, and
            # the ranker needs floats.
            return ok({"embeddings": [[0.0, 1.0, 0.0, 0.0]]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        vectors = client.embed(["one"])
        assert vectors == [(0.0, 1.0, 0.0, 0.0)]
        assert all(isinstance(v, float) for v in vectors[0])

    def test_wrong_count_raises(self):
        def handler(request):
            return ok({"embeddings": [unit_vector()]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="expected 2 embeddings"):
            client.embed(["one", "two"])

    def test_missing_embeddings_key_raises(self):
        def handler(request):
            return ok({"model": "bge-m3"})

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="no 'embeddings' array"):
            client.embed(["one"])

    def test_empty_input_makes_no_call(self):
        def explode(request):  # pragma: no cover - must never run
            raise AssertionError("empty input must not call the provider")

        client = EmbeddingClient(config(), client=stub_client(explode))
        assert client.embed([]) == []


# ---------------------------------------------------------------------------
# 1.3 Receipt checks: a malformed vector must raise, not score
# ---------------------------------------------------------------------------


class TestReceiptChecks:
    def test_mismatched_dimension_raises(self):
        def handler(request):
            return ok({"embeddings": [unit_vector(4), unit_vector(8)]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="dimension"):
            client.embed(["one", "two"])

    def test_dimension_change_between_calls_raises(self):
        width = {"value": 4}

        def handler(request):
            return ok({"embeddings": [unit_vector(width["value"])]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        client.embed(["one"])
        width["value"] = 8
        with pytest.raises(EmbeddingUnavailable, match="changed dimension"):
            client.embed(["one"])

    @pytest.mark.parametrize("literal", ["1e400", "-1e400"])
    def test_non_finite_value_raises(self, literal):
        # The reachable path: `1e400` is valid JSON and Python's parser turns it
        # into `inf`, so a provider can deliver a non-finite value inside a
        # well-formed body. NaN compares false against everything and would not
        # raise on its own — it would just produce an order that looks plausible
        # and is not.
        body = '{"embeddings": [[1.0, %s, 0.0, 0.0]]}' % literal

        def handler(request):
            return httpx.Response(200, text=body)

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="non-finite"):
            client.embed(["one"])

    def test_unnormalised_vector_raises(self):
        # A provider returning raw vectors would make cosine a plain dot
        # product of arbitrary magnitudes. Reject it rather than score it.
        def handler(request):
            return ok({"embeddings": [[3.0, 4.0, 0.0, 0.0]]})  # norm 5.0

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="not unit length"):
            client.embed(["one"])

    def test_float32_normalisation_is_accepted(self):
        # Measured worst case on bge-m3 is 6.5e-7 off unit length. The tolerance
        # must accept that or every real response would be rejected.
        vector = [0.0] * 4
        vector[0] = 1.0 - 6.5e-7

        def handler(request):
            return ok({"embeddings": [vector]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        assert len(client.embed(["one"])) == 1

    def test_tolerance_is_documented_and_generous(self):
        assert NORM_TOLERANCE >= 1e-6
        assert NORM_TOLERANCE <= 1e-2

    def test_non_vector_entry_raises(self):
        def handler(request):
            return ok({"embeddings": ["not a vector"]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="not a vector"):
            client.embed(["one"])


# ---------------------------------------------------------------------------
# 1.4 Typed failure for transport and HTTP errors
# ---------------------------------------------------------------------------


class TestFailureIsTyped:
    def test_connection_refused_is_typed(self):
        def handler(request):
            raise httpx.ConnectError("refused")

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="ConnectError"):
            client.embed(["one"])

    def test_timeout_is_typed(self):
        def handler(request):
            raise httpx.ReadTimeout("slow")

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="ReadTimeout"):
            client.embed(["one"])

    def test_http_500_is_typed(self):
        def handler(request):
            return httpx.Response(500, text="boom")

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="HTTP 500"):
            client.embed(["one"])

    def test_non_json_body_is_typed(self):
        def handler(request):
            return httpx.Response(200, text="<html>nope</html>")

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable, match="not JSON"):
            client.embed(["one"])

    def test_default_timeout_covers_a_cold_model_load(self):
        # Measured: cold load costs 2.0s (1 text) to 2.8s (72 texts); warm costs
        # 0.02s and 0.64s. A 2s timeout failed the first request after every
        # restart, so the feature degraded on first use and looked broken.
        assert EmbeddingConfig().timeout >= 5.0

    def test_failure_message_carries_no_request_text(self):
        # The message can reach a response, and the request may be a customer's
        # own words.
        def handler(request):
            raise httpx.ConnectError("refused")

        client = EmbeddingClient(config(), client=stub_client(handler))
        with pytest.raises(EmbeddingUnavailable) as caught:
            client.embed(["my secret customer sentence"])
        assert "secret customer" not in str(caught.value)


# ---------------------------------------------------------------------------
# 2.1 Product text
# ---------------------------------------------------------------------------


class TestProductText:
    def test_contains_every_describing_field(self):
        product = {
            "name": "Rainbow Pastel A4 80gsm Pastel Blue",
            "category": "Coloured paper",
            "finish": "uncoated",
            "weight_gsm": 80,
            "size_code": "A4",
            "colour_name": "pastel blue",
            "colour_mode": None,
        }
        text = product_text(product)
        for expected in ("Rainbow Pastel", "Coloured paper", "uncoated", "80gsm", "A4", "pastel blue"):
            assert expected in text

    def test_missing_fields_produce_no_artefacts(self):
        # The failure mode: str(None) becomes "None", which embeds as content.
        text = product_text({"name": "Plain", "category": "Copy paper"})
        assert "None" not in text
        assert "  " not in text
        assert text == "Plain Copy paper"

    def test_colour_mode_included_for_printed_goods(self):
        text = product_text({
            "name": "Flyer", "category": "Flyer printing",
            "colour_mode": "Full colour (CMYK)", "sides": "double",
        })
        assert "Full colour (CMYK)" in text
        assert "double" in text

    def test_real_products_all_produce_text(self, snapshot_products):
        for product in snapshot_products:
            text = product_text(product)
            assert text.strip()
            assert "None" not in text


# ---------------------------------------------------------------------------
# 2.2 Cosine similarity
# ---------------------------------------------------------------------------


class TestCosine:
    def test_identical_vectors_score_one(self):
        assert cosine(unit_vector(), unit_vector()) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert cosine(unit_vector(4, 0), unit_vector(4, 1)) == pytest.approx(0.0)

    def test_opposite_vectors_score_minus_one(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine(a, b) == pytest.approx(-1.0)

    def test_does_not_renormalise(self):
        # If it divided by the norms again, a vector of length 2 would still
        # score 1.0 against itself. It must not: the dot product is the answer,
        # and the receipt checks are what guarantee unit length.
        doubled = [2.0, 0.0]
        assert cosine(doubled, doubled) == pytest.approx(4.0)

    def test_dimension_mismatch_raises(self):
        with pytest.raises(ValueError, match="dimension mismatch"):
            cosine([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_symmetry(self):
        a = [0.6, 0.8, 0.0]
        b = [0.0, 0.8, 0.6]
        assert cosine(a, b) == pytest.approx(cosine(b, a))


# ---------------------------------------------------------------------------
# 2.3 Per-snapshot cache
# ---------------------------------------------------------------------------


class TestCache:
    def setup_method(self):
        CACHE.clear()

    def teardown_method(self):
        CACHE.clear()

    def key(self, built_at: str = "2026-01-01T00:00:00", count: int = 2) -> CacheKey:
        return CacheKey(
            base_url="http://localhost:11434", model="bge-m3",
            built_at=built_at, product_count=count,
        )

    def products(self, n: int = 2) -> list[dict]:
        return [
            {"sku": f"S{i}", "name": f"Product {i}", "category": "Copy paper"}
            for i in range(n)
        ]

    def test_cache_hit_avoids_a_second_provider_call(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            body = json.loads(request.content)
            return ok({"embeddings": [unit_vector() for _ in body["input"]]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        from paperlane.embeddings import product_vectors

        products = self.products()
        first = product_vectors(products, key=self.key(), client=client)
        second = product_vectors(products, key=self.key(), client=client)
        assert calls["n"] == 1
        assert first == second

    def test_changed_build_time_invalidates(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            body = json.loads(request.content)
            return ok({"embeddings": [unit_vector() for _ in body["input"]]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        from paperlane.embeddings import product_vectors

        products = self.products()
        product_vectors(products, key=self.key(built_at="A"), client=client)
        product_vectors(products, key=self.key(built_at="B"), client=client)
        assert calls["n"] == 2

    def test_changed_product_count_invalidates(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            body = json.loads(request.content)
            return ok({"embeddings": [unit_vector() for _ in body["input"]]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        from paperlane.embeddings import product_vectors

        product_vectors(self.products(2), key=self.key(count=2), client=client)
        product_vectors(self.products(3), key=self.key(count=3), client=client)
        assert calls["n"] == 2

    def test_changed_model_invalidates(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            body = json.loads(request.content)
            return ok({"embeddings": [unit_vector() for _ in body["input"]]})

        client = EmbeddingClient(config(), client=stub_client(handler))
        from paperlane.embeddings import product_vectors

        products = self.products()
        product_vectors(products, key=self.key(), client=client)
        product_vectors(
            products,
            key=CacheKey("http://localhost:11434", "other-model", "2026-01-01T00:00:00", 2),
            client=client,
        )
        assert calls["n"] == 2

    def test_snapshot_fingerprint_reads_built_at_and_count(self):
        from paperlane.embeddings import snapshot_fingerprint

        built_at, count = snapshot_fingerprint()
        assert built_at
        assert count == 72


# ---------------------------------------------------------------------------
# The scorer, and degradation
# ---------------------------------------------------------------------------


class TestScorer:
    def setup_method(self):
        CACHE.clear()

    def teardown_method(self):
        CACHE.clear()

    def test_scorer_scores_only_the_skus_asked_about(self):
        def handler(request):
            body = json.loads(request.content)
            return ok({"embeddings": [unit_vector() for _ in body["input"]]})

        scorer = SemanticScorer(
            request_text="paper",
            products=[{"sku": "A", "name": "a"}, {"sku": "B", "name": "b"}],
            config=config(),
            client=EmbeddingClient(config(), client=stub_client(handler)),
            key=CacheKey("http://x", "bge-m3", "t", 2),
        )
        assert set(scorer.scores(["A"])) == {"A"}

    def test_failure_is_sticky(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            raise httpx.ConnectError("refused")

        scorer = SemanticScorer(
            request_text="paper",
            products=[{"sku": "A", "name": "a"}],
            config=config(),
            client=EmbeddingClient(config(), client=stub_client(handler)),
            key=CacheKey("http://x", "bge-m3", "t", 1),
        )
        with pytest.raises(EmbeddingUnavailable):
            scorer.scores(["A"])
        with pytest.raises(EmbeddingUnavailable):
            scorer.scores(["A"])
        # The alternatives path must not retry a provider already known dead,
        # or the request pays the timeout twice.
        assert calls["n"] == 1
        assert scorer.degraded is True

    def test_empty_request_text_yields_no_scorer(self):
        # A structured request carries no wording. Embedding "" would score
        # every product against nothing.
        assert scorer_for(
            "   ", [{"sku": "A"}], config=config(),
            client=EmbeddingClient(config(), client=stub_client(lambda r: ok({}))),
        ) is None


# ---------------------------------------------------------------------------
# 3.1 / 3.3 The ranking key and both call sites
# ---------------------------------------------------------------------------


def candidate(sku: str, satang: int, *, similarity=None, status="in_stock"):
    from paperlane.search import Candidate
    from paperlane.money import Money
    from paperlane.pricing import PriceFacts

    money = Money(satang)
    return Candidate(
        sku=sku, name=sku, product={"sku": sku}, facts=PriceFacts(
            sku=sku, list_price=money, sale_price=None, tiers=(),
        ),
        match_reasons=(), unit_price=money, line_total=money, quantity=1,
        tier_applied=None, available=status == "in_stock",
        stock_status=status, back_in_stock_date=None, similarity=similarity,
    )


class TestRankKey:
    def test_disabled_key_is_exactly_the_old_tuple(self):
        c = candidate("A", 1000)
        assert _rank_key(c) == (0, 1000, "A")
        assert _rank_key(c, use_similarity=False) == (0, 1000, "A")

    def test_enabled_key_inserts_similarity_after_price(self):
        c = candidate("A", 1000, similarity=0.5)
        assert _rank_key(c, use_similarity=True) == (0, 1000, -0.5, "A")

    def test_availability_still_outranks_similarity(self):
        # A similar but out-of-stock item must not outrank an available one.
        available = candidate("A", 1000, similarity=0.1)
        out = candidate("B", 100, similarity=0.9, status="out_of_stock")
        ordered = sorted([out, available], key=lambda c: _rank_key(c, use_similarity=True))
        assert [c.sku for c in ordered] == ["A", "B"]

    def test_documented_order_names_the_conditional_term(self):
        assert RANKING_ORDER == (
            "availability_penalty", "budget_margin", "similarity", "sku"
        )


class FakeScorer:
    """A scorer with fixed scores, so ranking can be tested offline."""

    def __init__(self, scores: dict[str, float]):
        self._scores = scores
        self.degraded = False

    def scores(self, skus):
        return {sku: self._scores[sku] for sku in skus if sku in self._scores}


class FailingScorer:
    degraded = True

    def scores(self, skus):
        raise EmbeddingUnavailable("provider unreachable")


def products(*skus: str) -> list[dict]:
    return [
        {
            "sku": sku, "name": f"Product {sku}", "category": "Copy paper",
            "size_code": "A4", "weight_gsm": 80, "finish": "uncoated",
            "stock_status": "in_stock",
        }
        for sku in skus
    ]


def facts_for(products_list, satang: int = 1000):
    from paperlane.money import Money
    from paperlane.pricing import PriceFacts

    return {
        p["sku"]: PriceFacts(
            sku=p["sku"], list_price=Money(satang), sale_price=None, tiers=(),
        )
        for p in products_list
    }


class TestRankingIntegration:
    def test_similarity_reorders_matches(self):
        rows = products("AAA", "BBB")
        result = search(
            Criteria(size_code="A4"), rows, facts_for(rows),
            scorer=FakeScorer({"AAA": 0.1, "BBB": 0.9}),
        )
        # Cheapest-first would put them in SKU order; similarity reverses it.
        assert [c.sku for c in result.matches] == ["BBB", "AAA"]
        assert result.semantic == SEMANTIC_APPLIED

    def test_no_scorer_is_the_previous_order(self):
        rows = products("BBB", "AAA")
        result = search(Criteria(size_code="A4"), rows, facts_for(rows))
        assert [c.sku for c in result.matches] == ["AAA", "BBB"]
        assert result.semantic == SEMANTIC_OFF

    def test_membership_is_identical_with_and_without(self):
        rows = products("AAA", "BBB", "CCC")
        facts = facts_for(rows)
        off = search(Criteria(size_code="A4"), rows, facts)
        on = search(
            Criteria(size_code="A4"), rows, facts,
            scorer=FakeScorer({"AAA": 0.1, "BBB": 0.9, "CCC": 0.5}),
        )
        assert {c.sku for c in off.matches} == {c.sku for c in on.matches}

    def test_similarity_cannot_introduce_a_filtered_item(self):
        # An item the filter rejects is absent from the candidate list before
        # any score is consulted, so no score can bring it back.
        rows = products("AAA") + [
            {
                "sku": "ZZZ", "name": "A5 item", "category": "Copy paper",
                "size_code": "A5", "weight_gsm": 80, "finish": "uncoated",
                "stock_status": "in_stock",
            }
        ]
        facts = facts_for(rows)
        result = search(
            Criteria(size_code="A4"), rows, facts,
            scorer=FakeScorer({"AAA": 0.0, "ZZZ": 1.0}),
        )
        assert [c.sku for c in result.matches] == ["AAA"]

    def test_similarity_cannot_exclude_a_qualifying_item(self):
        rows = products("AAA", "BBB")
        result = search(
            Criteria(size_code="A4"), rows, facts_for(rows),
            scorer=FakeScorer({"AAA": 0.0, "BBB": 0.0}),
        )
        assert {c.sku for c in result.matches} == {"AAA", "BBB"}

    def test_alternatives_path_also_orders_by_similarity(self):
        # search() and _relax() share the flag; without this they could drift.
        rows = products("AAA", "BBB")
        rows[0]["size_code"] = "A5"
        rows[1]["size_code"] = "A5"
        facts = facts_for(rows)
        result = search(
            Criteria(size_code="A4"), rows, facts,
            scorer=FakeScorer({"AAA": 0.1, "BBB": 0.9}),
        )
        assert result.relaxed == "size"
        assert [c.sku for c in result.alternatives] == ["BBB", "AAA"]

    def test_failing_provider_degrades_to_previous_order(self):
        rows = products("BBB", "AAA")
        result = search(
            Criteria(size_code="A4"), rows, facts_for(rows),
            scorer=FailingScorer(),
        )
        assert [c.sku for c in result.matches] == ["AAA", "BBB"]
        assert result.semantic == SEMANTIC_UNAVAILABLE
        assert result.semantic_detail

    def test_similarity_is_reported_per_candidate(self):
        rows = products("AAA")
        result = search(
            Criteria(size_code="A4"), rows, facts_for(rows),
            scorer=FakeScorer({"AAA": 0.42}),
        )
        assert result.matches[0].similarity == pytest.approx(0.42)

    def test_similarity_absent_from_dict_when_disabled(self):
        rows = products("AAA")
        result = search(Criteria(size_code="A4"), rows, facts_for(rows))
        assert "similarity" not in result.matches[0].as_dict()

    def test_similarity_present_in_dict_when_enabled(self):
        rows = products("AAA")
        result = search(
            Criteria(size_code="A4"), rows, facts_for(rows),
            scorer=FakeScorer({"AAA": 0.42}),
        )
        assert result.matches[0].as_dict()["similarity"] == pytest.approx(0.42)

    def test_no_candidates_makes_no_scoring_call(self):
        # The unit that must be free. In practice a no-match request still
        # reaches _relax, and those alternatives do need ranking — but the
        # matches path itself must never score an empty candidate list.
        from paperlane.search import _similarity_for

        class Counting:
            degraded = False
            calls = 0

            def scores(self, skus):
                Counting.calls += 1
                return {}

        scores, semantic, detail = _similarity_for(Counting(), [])
        assert scores is None
        assert semantic == SEMANTIC_OFF
        assert detail is None
        assert Counting.calls == 0

    def test_clarification_makes_no_scoring_call(self):
        # A question is asked before search is reached, so a request the
        # assistant cannot yet act on never contacts the provider.
        from paperlane.assistant import answer

        class Counting:
            degraded = False
            calls = 0

            def scores(self, skus):
                Counting.calls += 1
                return {}

        rows = products("AAA")
        reply = answer(
            Criteria(), rows, facts_for(rows), scorer=Counting()
        )
        assert reply.outcome == "clarified"
        assert Counting.calls == 0

    def test_matches_path_scores_once_when_something_qualifies(self):
        class Counting:
            degraded = False
            calls = 0

            def scores(self, skus):
                Counting.calls += 1
                return {sku: 0.5 for sku in skus}

        rows = products("AAA")
        search(Criteria(size_code="A4"), rows, facts_for(rows), scorer=Counting())
        assert Counting.calls == 1

    def test_equal_similarity_still_orders_by_sku(self):
        rows = products("BBB", "AAA")
        result = search(
            Criteria(size_code="A4"), rows, facts_for(rows),
            scorer=FakeScorer({"AAA": 0.5, "BBB": 0.5}),
        )
        assert [c.sku for c in result.matches] == ["AAA", "BBB"]

    def test_two_runs_same_order(self):
        rows = products("AAA", "BBB", "CCC")
        facts = facts_for(rows)
        scorer_scores = {"AAA": 0.2, "BBB": 0.8, "CCC": 0.5}
        first = [c.sku for c in search(
            Criteria(size_code="A4"), rows, facts, scorer=FakeScorer(scorer_scores)
        ).matches]
        for _ in range(3):
            again = [c.sku for c in search(
                Criteria(size_code="A4"), rows, facts, scorer=FakeScorer(scorer_scores)
            ).matches]
            assert again == first


# ---------------------------------------------------------------------------
# 4.1 The load-bearing invariant, across the whole recorded set
# ---------------------------------------------------------------------------


class TestMembershipInvariantAcrossRecordedCases:
    def test_every_case_returns_the_same_sku_set(self, snapshot_products):
        """For every recorded case, enabling similarity changes order only.

        Tested across the whole set rather than spot-checked, because this is
        the guarantee the entire capability rests on. The scores are synthetic
        but deterministic and adversarial: the *most* similar product is the
        one the previous ranking put *last*, so any case where similarity could
        change membership has the best chance to show it.

        Alternatives are compared through ``_relax``, which returns the whole
        qualifying set. The reply shows only the top five of it, and enabling
        similarity legitimately changes *which* five — that is ordering, not
        membership. Comparing the truncated lists would have conflated the two
        and reported a display cap as a correctness bug.
        """
        from paperlane.catalog import load_price_facts
        from paperlane.evaluate import load_cases
        from paperlane.interpret import interpret_rules, validate
        from paperlane.search import _relax

        facts = load_price_facts()
        skus = [p["sku"] for p in snapshot_products]
        # Reverse-order scores: the last SKU is most similar.
        adversarial = {
            sku: (index + 1) / len(skus) for index, sku in enumerate(reversed(skus))
        }

        checked = 0
        for case in load_cases():
            criteria = validate(interpret_rules(case.request))
            if case.quantity is not None:
                from dataclasses import replace

                criteria = replace(criteria, quantity=case.quantity)

            off = search(criteria, snapshot_products, facts)
            on = search(
                criteria, snapshot_products, facts, scorer=FakeScorer(adversarial)
            )
            assert {c.sku for c in off.matches} == {c.sku for c in on.matches}, (
                f"case {case.number} membership changed: "
                f"{sorted(c.sku for c in off.matches)} vs "
                f"{sorted(c.sku for c in on.matches)}"
            )

            qty = criteria.quantity or 1
            off_all, off_attr = _relax(criteria, snapshot_products, facts, qty)
            on_all, on_attr = _relax(
                criteria, snapshot_products, facts, qty, scorer=FakeScorer(adversarial)
            )
            assert {c.sku for c in off_all} == {c.sku for c in on_all}, (
                f"case {case.number} qualifying alternatives changed"
            )
            assert off_attr == on_attr, f"case {case.number} relaxed a different rule"

            # The displayed five must come from that qualifying set, never from
            # outside it.
            assert {c.sku for c in on.alternatives} <= {c.sku for c in on_all}
            checked += 1
        assert checked == 28


# ---------------------------------------------------------------------------
# 2.4 / 5.3 Provider-dependent tests, skipped when no provider is present
# ---------------------------------------------------------------------------


@needs_embedding
class TestAgainstTheRealProvider:
    def test_all_products_embed_in_one_call_and_are_deterministic(self, snapshot_products):
        client = EmbeddingClient(EmbeddingConfig.from_env())
        first = client.embed([product_text(p) for p in snapshot_products])
        second = client.embed([product_text(p) for p in snapshot_products])
        assert len(first) == 72
        assert first == second
        assert client.dimension == 1024

    def test_real_similarity_is_semantic(self):
        # The feature is only worth having if paraphrase scores above unrelated
        # text. Measured, not assumed.
        client = EmbeddingClient(EmbeddingConfig.from_env())
        request, close, far = client.embed([
            "cheap writing paper",
            "A4 80gsm copy paper",
            "A4 170gsm gloss flyer",
        ])
        assert cosine(request, close) > cosine(request, far)

    def test_search_with_a_real_scorer_keeps_membership(self, snapshot_products):
        from paperlane.catalog import load_price_facts

        config = EmbeddingConfig.from_env()
        facts = load_price_facts()
        criteria = Criteria(size_code="A4", weight_gsm=80)
        off = search(criteria, snapshot_products, facts)
        scorer = scorer_for("cheap writing paper", snapshot_products)
        assert scorer is not None
        on = search(criteria, snapshot_products, facts, scorer=scorer)
        assert {c.sku for c in off.matches} == {c.sku for c in on.matches}
        assert on.semantic == SEMANTIC_APPLIED
        assert all(c.similarity is not None for c in on.matches)
