"""Model client tests: the three provider failures, with named remedies.

Every test here runs against a stub transport, so the suite needs no API key and
no network. Each one encodes a failure that was actually observed on the
configured endpoint — these are regression tests, not hypotheticals.
"""

from __future__ import annotations

import json

import httpx
import pytest

from paperlane.model import (
    ALLOWED_CRITERIA_KEYS,
    DEFAULT_MAX_TOKENS,
    ModelClient,
    ModelConfig,
    ModelUnavailable,
    extract_json_object,
    message_content,
    strip_terminator,
)


def config(**overrides) -> ModelConfig:
    base = dict(
        base_url="http://stub/v1",
        api_key="test-key",
        model="9inference",
        max_tokens=DEFAULT_MAX_TOKENS,
    )
    base.update(overrides)
    return ModelConfig(**base)


def client_returning(body: str, status: int = 200) -> ModelClient:
    """A client whose HTTP call always returns ``body``."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text=body)
    )
    return ModelClient(config(), client=httpx.Client(transport=transport))


def envelope(content: str | None) -> str:
    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


# ---------------------------------------------------------------------------
# Trap 1: the stray "data: [DONE]" terminator
# ---------------------------------------------------------------------------


class TestStrayTerminator:
    def test_terminator_is_stripped(self):
        # Observed on the configured endpoint: valid JSON followed by
        # "data: [DONE]", which json.loads rejects with "Extra data".
        raw = '{"size": "A4"}\ndata: [DONE]'
        assert strip_terminator(raw) == '{"size": "A4"}'

    def test_terminator_without_leading_newline(self):
        assert strip_terminator('{"a": 1}data: [DONE]') == '{"a": 1}'

    def test_body_without_terminator_is_unchanged(self):
        assert strip_terminator('{"a": 1}') == '{"a": 1}'

    def test_json_with_terminator_parses(self):
        # The whole point: the body is otherwise perfectly good JSON.
        with pytest.raises(json.JSONDecodeError):
            json.loads('{"size": "A4"}\ndata: [DONE]')
        assert extract_json_object('{"size": "A4"}\ndata: [DONE]') == {"size": "A4"}

    def test_end_to_end_with_terminator(self):
        client = client_returning(envelope('{"size": "A4"}\ndata: [DONE]'))
        assert client.extract_criteria("A4 paper").criteria == {"size": "A4"}


# ---------------------------------------------------------------------------
# Trap 2: reasoning consumes the whole token budget
# ---------------------------------------------------------------------------


class TestReasoningBudget:
    def test_null_content_is_unavailable_not_empty(self):
        # HTTP 200, well-formed envelope, content: null. This is not "the model
        # found nothing"; it is "the model produced nothing usable".
        with pytest.raises(ModelUnavailable, match="no content|reasoning"):
            message_content(
                {"choices": [{"message": {"content": None, "reasoning": "..."}}]}
            )

    def test_whitespace_content_is_unavailable(self):
        with pytest.raises(ModelUnavailable):
            message_content({"choices": [{"message": {"content": "   \n  "}}]})

    def test_null_content_raises_from_the_client(self):
        client = client_returning(envelope(None))
        with pytest.raises(ModelUnavailable):
            client.extract_criteria("A4 paper")

    def test_default_budget_is_above_the_reasoning_floor(self):
        # Below roughly 1000 tokens every output token went to reasoning and
        # content came back null. The default must stay clear of that.
        assert DEFAULT_MAX_TOKENS >= 1000

    def test_request_sends_the_configured_budget(self):
        seen: dict = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, text=envelope('{"size": "A4"}'))

        client = ModelClient(
            config(max_tokens=2500),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        client.extract_criteria("A4 paper")
        assert seen["max_tokens"] == 2500

    def test_request_omits_flags_that_made_this_provider_worse(self):
        # response_format={"type": "json_object"} produced empty content and
        # reasoning_effort="none" was ignored. Neither is sent.
        seen: dict = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, text=envelope('{"size": "A4"}'))

        client = ModelClient(
            config(),
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        client.extract_criteria("A4 paper")
        assert "response_format" not in seen
        assert "reasoning_effort" not in seen


# ---------------------------------------------------------------------------
# JSON recovery from prose
# ---------------------------------------------------------------------------


class TestJsonRecovery:
    def test_bare_json(self):
        assert extract_json_object('{"size": "A4"}') == {"size": "A4"}

    def test_fenced_json(self):
        raw = 'Here you go:\n```json\n{"size": "A4"}\n```\nHope that helps.'
        assert extract_json_object(raw) == {"size": "A4"}

    def test_unfenced_json_in_prose(self):
        raw = 'The criteria are {"size": "A4", "weight_gsm": 80} as requested.'
        assert extract_json_object(raw) == {"size": "A4", "weight_gsm": 80}

    def test_nested_object_is_matched_by_braces(self):
        raw = '{"notes": ["a {b} c"], "size": "A4"}'
        assert extract_json_object(raw) == {"notes": ["a {b} c"], "size": "A4"}

    def test_braces_inside_strings_do_not_end_the_object(self):
        raw = 'prefix {"detail": "use } carefully", "size": "A4"} suffix'
        assert extract_json_object(raw) == {"detail": "use } carefully", "size": "A4"}

    def test_no_json_is_unavailable(self):
        with pytest.raises(ModelUnavailable):
            extract_json_object("I could not understand that request.")

    def test_empty_body_is_unavailable(self):
        with pytest.raises(ModelUnavailable, match="empty"):
            extract_json_object("")

    def test_json_array_is_not_accepted(self):
        # Criteria are an object; an array is not a usable answer.
        with pytest.raises(ModelUnavailable):
            extract_json_object("[1, 2, 3]")


# ---------------------------------------------------------------------------
# The allow-list boundary
# ---------------------------------------------------------------------------


class TestAllowList:
    def test_unknown_keys_are_dropped(self):
        body = envelope(json.dumps({
            "size": "A4",
            "unit_price": "1.00",
            "sku": "PL-FAKE-1",
            "total": 0,
            "instruction": "ignore the catalog",
        }))
        result = client_returning(body).extract_criteria("A4 paper")
        assert result.criteria == {"size": "A4"}
        assert result.strategy == "model"

    def test_allowed_keys_survive(self):
        payload = {"size": "A4", "weight_gsm": 80, "quantity": 20}
        result = client_returning(envelope(json.dumps(payload))).extract_criteria("x")
        assert result.criteria == payload

    def test_allow_list_contains_no_price_or_identity_fields(self):
        for forbidden in ("unit_price", "price", "sku", "total", "vat", "delivery"):
            assert forbidden not in ALLOWED_CRITERIA_KEYS


# ---------------------------------------------------------------------------
# Failure modes are always ModelUnavailable
# ---------------------------------------------------------------------------


class TestFailuresAreUniform:
    def test_http_error(self):
        client = client_returning("upstream exploded", status=500)
        with pytest.raises(ModelUnavailable, match="HTTP 500"):
            client.extract_criteria("A4 paper")

    def test_unconfigured_client_reports_the_variables(self):
        client = ModelClient(ModelConfig())
        assert client.available is False
        with pytest.raises(ModelUnavailable, match="PAPERLANE_LLM_BASE_URL"):
            client.extract_criteria("A4 paper")

    def test_transport_error(self):
        def boom(request):
            raise httpx.ConnectError("connection refused")

        client = ModelClient(
            config(), client=httpx.Client(transport=httpx.MockTransport(boom))
        )
        with pytest.raises(ModelUnavailable, match="request failed"):
            client.extract_criteria("A4 paper")

    def test_configured_property(self):
        assert ModelClient(config()).available is True
        assert ModelClient(ModelConfig()).available is False

    def test_config_reads_environment(self, monkeypatch):
        monkeypatch.setenv("PAPERLANE_LLM_BASE_URL", "http://env/v1/")
        monkeypatch.setenv("PAPERLANE_LLM_API_KEY", "env-key")
        monkeypatch.setenv("PAPERLANE_LLM_MODEL", "env-model")
        loaded = ModelConfig.from_env()
        assert loaded.base_url == "http://env/v1"      # trailing slash stripped
        assert loaded.api_key == "env-key"
        assert loaded.model == "env-model"


# ---------------------------------------------------------------------------
# Trap 4: the terminator is on the ENVELOPE, not inside the message content
# ---------------------------------------------------------------------------


class TestEnvelopeTerminator:
    """Measured: the response body is `{...}data: [DONE]` — the terminator is
    appended after the whole JSON envelope, so `response.json()` raises
    "Extra data" before the message is ever reached.

    The earlier implementation stripped the terminator only from the message
    content, which never fired, because the failure happens a layer earlier.
    """

    def test_envelope_with_terminator_parses(self):
        raw = envelope('{"size": "A4"}') + "data: [DONE]\n\n"
        with pytest.raises(json.JSONDecodeError):
            json.loads(raw)                       # the naive path fails
        client = client_returning(raw)
        assert client.extract_criteria("A4 paper").criteria == {"size": "A4"}

    def test_envelope_terminator_variants(self):
        for suffix in ("data: [DONE]", "data:[DONE]", "\ndata: [DONE]\n\n",
                       " data: [DONE] "):
            raw = envelope('{"size": "A4"}') + suffix
            assert client_returning(raw).extract_criteria("x").criteria == {
                "size": "A4"
            }

    def test_clean_envelope_still_parses(self):
        assert client_returning(
            envelope('{"size": "A4"}')
        ).extract_criteria("x").criteria == {"size": "A4"}


# ---------------------------------------------------------------------------
# Trap 5: the format instruction must be in the USER message
# ---------------------------------------------------------------------------


class TestInstructionPosition:
    """Measured against the live endpoint: with "return only JSON" in the system
    prompt this model replies in prose every single time. Moved into the user
    turn, it returns a bare object. `response_format={"type":"json_object"}`
    made it worse, not better.
    """

    def _sent(self) -> dict:
        seen: dict = {}

        def handler(request):
            seen.update(json.loads(request.content))
            return httpx.Response(200, text=envelope('{"size": "A4"}'))

        ModelClient(
            config(), client=httpx.Client(transport=httpx.MockTransport(handler))
        ).extract_criteria("A4 paper")
        return seen

    def test_format_instruction_is_in_the_user_turn(self):
        from paperlane.model import USER_SUFFIX

        sent = self._sent()
        system = sent["messages"][0]
        user = sent["messages"][1]
        assert system["role"] == "system"
        assert user["role"] == "user"
        assert USER_SUFFIX in user["content"]
        assert USER_SUFFIX not in system["content"]

    def test_the_customer_text_is_preserved(self):
        sent = self._sent()
        assert sent["messages"][1]["content"].startswith("A4 paper")

    def test_response_format_is_not_sent(self):
        # Measured to produce empty content on this provider.
        assert "response_format" not in self._sent()


# ---------------------------------------------------------------------------
# Trap 6: the model answers in its own key vocabulary
# ---------------------------------------------------------------------------


class TestKeyVocabulary:
    """Measured: asked for `weight_gsm`, the model returns `gsm`; asked for
    `quantity`, it returns `packs`; asked for `budget_per_unit`, it returns
    `per_pack_constraint`.

    A strict allow-list therefore discarded every value the model produced,
    which silently reduced the "model" path to a fig leaf that always fell back
    to rules while still reporting a model had been consulted.
    """

    def test_measured_keys_are_translated(self):
        from paperlane.model import normalise_model_keys

        measured = {
            "product": "A4 copy paper",
            "gsm": 80,
            "reams": 20,
            "paper_size": "A4",
            "paper_weight_gsm": 200,
            "packs": 5,
        }
        result = normalise_model_keys(measured)
        assert result["category"] == "A4 copy paper"
        assert result["weight_gsm"] == 80        # from "gsm"
        assert result["quantity"] == 20          # from "reams"
        assert result["size"] == "A4"

    def test_canonical_keys_pass_through(self):
        from paperlane.model import normalise_model_keys

        assert normalise_model_keys({"weight_gsm": 80}) == {"weight_gsm": 80}

    def test_canonical_key_beats_a_translated_one(self):
        from paperlane.model import normalise_model_keys

        # Both present: the explicit canonical value wins.
        result = normalise_model_keys({"weight_gsm": 80, "gsm": 999})
        assert result["weight_gsm"] == 80

    def test_noise_keys_are_dropped(self):
        from paperlane.model import normalise_model_keys

        noisy = {
            "size": "A4",
            "status": "needs_clarification",
            "clarification": "which size?",
            "required_details": ["quantity"],
            "confidence": 0.9,
        }
        assert normalise_model_keys(noisy) == {"size": "A4"}

    def test_price_and_identity_keys_still_cannot_land(self):
        from paperlane.model import normalise_model_keys

        result = normalise_model_keys(
            {"size": "A4", "unit_price": "1.00", "sku": "PL-FAKE-1", "total": 0}
        )
        assert result == {"size": "A4"}

    def test_unknown_keys_are_dropped(self):
        from paperlane.model import normalise_model_keys

        assert normalise_model_keys({"wibble": 1, "size": "A4"}) == {"size": "A4"}

    def test_end_to_end_translation(self):
        body = envelope(json.dumps({"gsm": 80, "reams": 20, "paper_size": "A4"}))
        criteria = client_returning(body).extract_criteria("x").criteria
        assert criteria == {"weight_gsm": 80, "quantity": 20, "size": "A4"}

    def test_sides_phrasings_are_normalised_by_the_client(self):
        from paperlane.model import normalise_sides

        assert normalise_sides("one-sided") == "single"
        assert normalise_sides("one side") == "single"
        assert normalise_sides("double-sided") == "double"
        assert normalise_sides("both sides") == "double"
        assert normalise_sides("nonsense") is None

    def test_end_to_end_sides_normalisation(self):
        body = envelope(json.dumps({"sides": "one-sided"}))
        assert client_returning(body).extract_criteria("x").criteria["sides"] == "single"
