"""Conversation memory through the HTTP surface.

The merge rule is proven in `test_conversation.py`. What these tests pin is the
wiring: that a conversation continues, that a new subject does not inherit, that
the reply discloses what it remembered, that forgetting works, and — most
importantly — that a request naming no conversation behaves exactly as it did
before the feature existed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperlane import records
from paperlane.api import create_app


@pytest.fixture
def client() -> TestClient:
    """A fresh application, and therefore a fresh conversation store, per test."""
    return TestClient(create_app())


def ask(client: TestClient, text: str, conversation_id: str | None = None, **extra):
    payload = {"request": text, "use_model": False}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    payload.update(extra)
    return client.post("/api/ask", json=payload)


def records_written() -> list[dict]:
    path = records.record_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Continuation
# ---------------------------------------------------------------------------

class TestContinuation:
    def test_a_refined_quantity_is_quoted(self, client):
        first = ask(client, "A4 80gsm copy paper, 20 reams", "c1").json()
        assert first["outcome"] == "quoted"

        second = ask(client, "make it 50", "c1").json()
        assert second["outcome"] == "quoted"
        assert second["criteria"]["quantity"] == 50
        assert second["criteria"]["size"] == "A4"
        assert all(line["quantity"] == 50 for line in second["candidates"])

    def test_the_turn_count_advances(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        second = ask(client, "make it 50", "c1").json()
        assert second["conversation"]["turn"] == 2

    def test_a_budget_refinement_keeps_the_product(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        second = ask(client, "and under 130 a pack", "c1").json()
        assert second["criteria"]["size"] == "A4"
        assert second["criteria"]["quantity"] == 20
        assert second["criteria"]["budget_per_unit"] == "130.00"

    def test_a_new_size_starts_fresh(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        second = ask(client, "A5 copy paper", "c1").json()
        assert second["criteria"]["size"] == "A5"
        # The A4 turn's weight and quantity are not carried.
        assert second["criteria"].get("weight_gsm") is None
        assert second["criteria"].get("quantity") is None
        assert second["conversation"]["carried"] == []

    def test_a_new_category_does_not_inherit_the_old_one(self, client):
        ask(client, "A4 copy paper, 20 reams", "c1")
        second = ask(client, "double sided flyers", "c1").json()
        assert second["criteria"].get("category") != "Copy paper"


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------

class TestCommercialOnlyFirstTurn:
    """BUG.md A12 at the wiring, where the defect actually lived.

    The unit test proves the predicate; this proves the callers pass the stored
    criteria instead of `None`. Four call sites shared the narrow test, so a
    fix to `is_continuation` alone would leave the API, the page and the CLI
    still starting over.
    """

    def test_a_quantity_only_first_turn_is_continued(self, client):
        first = ask(client, "20 reams", "c1").json()
        assert first["criteria"].get("quantity") == 20

        second = ask(client, "make it 50", "c1").json()
        assert second["criteria"].get("quantity") == 50
        assert second["conversation"]["turn"] == 2

    def test_a_budget_only_first_turn_is_continued(self, client):
        first = ask(client, "under 200 a pack", "c1").json()
        assert first["criteria"].get("budget_per_unit") == "200.00"

        second = ask(client, "20 reams", "c1").json()
        assert second["criteria"].get("budget_per_unit") == "200.00"
        assert second["criteria"].get("quantity") == 20
        assert "budget_per_unit" in second["conversation"]["carried"]

    def test_a_named_subject_still_starts_fresh(self, client):
        """A12 must not weaken D3: naming a subject still discards the rest."""
        ask(client, "20 reams", "c1")
        second = ask(client, "A4 copy paper", "c1").json()
        assert second["criteria"].get("quantity") is None
        assert second["criteria"].get("size") == "A4"


class TestAnEmptyTurnDoesNotForget:
    """BUG.md A13 at the wiring: the turn is fresh, the conversation is not lost."""

    def test_the_next_turn_still_continues(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        middle = ask(client, "too expensive", "c1").json()
        assert middle["outcome"] == "clarified"
        assert middle["criteria"] == {}, "answered fresh, not re-answered"

        third = ask(client, "make it 50", "c1").json()
        assert third["outcome"] == "quoted"
        assert third["criteria"]["size"] == "A4"
        assert third["criteria"]["weight_gsm"] == 80
        assert third["criteria"]["quantity"] == 50
        assert "Remembered from your earlier message" in third["reply"]

    def test_the_turn_is_still_counted(self, client):
        ask(client, "A4 copy paper", "c1")
        ask(client, "hello there", "c1")
        third = ask(client, "make it 50", "c1").json()
        assert third["conversation"]["turn"] == 3


class TestDisclosure:
    def test_the_reply_names_what_it_remembered(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        reply = ask(client, "make it 50", "c1").json()["reply"]
        assert "Remembered from your earlier message" in reply
        assert "size A4" in reply
        assert "80 gsm" in reply

    def test_a_carried_quantity_is_named_explicitly(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        reply = ask(client, "and under 130 a pack", "c1").json()["reply"]
        assert "a quantity of 20" in reply

    def test_a_restated_quantity_is_not_called_remembered(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        reply = ask(client, "make it 50", "c1").json()["reply"]
        assert "a quantity of 20" not in reply

    def test_a_fresh_request_says_nothing_about_earlier_turns(self, client):
        body = ask(client, "A4 80gsm copy paper, 20 reams", "c1").json()
        assert "Remembered" not in body["reply"]
        assert body["conversation"]["carried"] == []
        assert body["conversation"]["carried_described"] == {}

    def test_the_response_carries_the_structure_too(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        body = ask(client, "make it 50", "c1").json()
        assert set(body["conversation"]["carried"]) >= {"size_code", "category"}
        assert body["conversation"]["carried_described"]["size"] == "A4"


# ---------------------------------------------------------------------------
# Off by default — the equivalence that must not drift
# ---------------------------------------------------------------------------

class TestOffByDefault:
    def test_a_request_without_an_id_has_no_conversation_key(self, client):
        body = ask(client, "A4 80gsm copy paper, 20 reams").json()
        assert "conversation" not in body

    def test_a_request_without_an_id_never_touches_the_store(self):
        class ExplodingStore:
            """Any access is a failure: no id means no conversation exists."""

            def get(self, conversation_id):
                raise AssertionError(f"store read for {conversation_id!r}")

            def put(self, conversation):
                raise AssertionError(f"store written for {conversation.id!r}")

            def forget(self, conversation_id):
                raise AssertionError(f"store forgotten for {conversation_id!r}")

            def ids(self):
                raise AssertionError("store listed")

        with TestClient(create_app(conversation_store=ExplodingStore())) as bare:
            response = ask(bare, "A4 80gsm copy paper, 20 reams")
            assert response.status_code == 200

    def test_single_turn_replies_are_unchanged(self, client):
        """The same request with and without an id must read identically.

        A fresh conversation is not the same thing as no conversation — but for
        the *first* turn it must produce the same answer, or the feature changed
        single-turn behaviour.
        """
        standalone = ask(client, "A4 80gsm copy paper, 20 reams").json()
        first_turn = ask(client, "A4 80gsm copy paper, 20 reams", "c1").json()
        assert first_turn["reply"] == standalone["reply"]
        assert first_turn["criteria"] == standalone["criteria"]


# ---------------------------------------------------------------------------
# Forgetting
# ---------------------------------------------------------------------------

class TestForget:
    def test_forgetting_makes_the_next_turn_fresh(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        response = client.delete("/api/conversations/c1")
        assert response.status_code == 200
        assert response.json()["forgotten"] is True

        after = ask(client, "make it 50", "c1").json()
        assert after["conversation"]["turn"] == 1
        assert after["criteria"] == {}

    def test_forgetting_an_unknown_conversation_is_not_an_error(self, client):
        response = client.delete("/api/conversations/never-existed")
        assert response.status_code == 200
        body = response.json()
        assert body["forgotten"] is False
        assert "no such conversation" in body["detail"]

    def test_a_blank_id_is_a_client_error(self, client):
        response = ask(client, "A4 copy paper", "   ")
        assert response.status_code == 422

    def test_an_over_long_id_is_a_client_error(self, client):
        response = ask(client, "A4 copy paper", "x" * 200)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# An unusable merge
# ---------------------------------------------------------------------------

class TestInvalidMerge:
    """Task 4.2: a merged value is validated in full, and asks rather than quotes.

    The merge can produce a request the catalog cannot price — a bare "make it
    500000" is a quantity out of range. The failure that matters is the quiet
    one: falling back to the previous turn's quantity, which quotes a number the
    customer did not ask for and presents it as an answer.
    """

    def test_an_out_of_range_refinement_is_refused(self, client):
        ask(client, "A4 copy paper, 20 reams", "c1")
        response = ask(client, "make it 500000", "c1")
        assert response.status_code == 422
        body = response.json()
        assert body["error"] == "invalid_request"
        assert body["field"] == "quantity"

    def test_the_refusal_does_not_fall_back_to_the_previous_quantity(self, client):
        ask(client, "A4 copy paper, 20 reams", "c1")
        body = ask(client, "make it 500000", "c1").json()
        assert "20" not in body["detail"]
        assert "candidates" not in body, "nothing was priced"

    def test_the_conversation_is_not_advanced_by_a_rejected_turn(self, client):
        """A refused merge must not become the state the next turn builds on."""
        ask(client, "A4 copy paper, 20 reams", "c1")
        ask(client, "make it 500000", "c1")
        after = ask(client, "make it 30", "c1").json()
        assert after["criteria"]["quantity"] == 30

    def test_an_out_of_range_turn_is_still_recorded(self, client):
        """A request that could not be priced is still a handled request."""
        ask(client, "A4 copy paper, 20 reams", "c1")
        before = len(records_written())
        ask(client, "make it 500000", "c1")
        written = records_written()
        assert len(written) == before + 1
        entry = written[-1]
        assert entry["outcome"] == "failed"
        assert entry["error"], "the record must say why nothing was priced"
        assert entry["turn_index"] == 2, "it is still turn two of the conversation"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

class TestRecords:
    def test_a_multi_turn_record_states_its_position_and_carried_fields(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        before = len(records_written())
        ask(client, "make it 50", "c1")
        written = records_written()
        assert len(written) == before + 1
        entry = written[-1]
        assert entry["turn_index"] == 2
        assert "size_code" in entry["carried_fields"]
        assert "quantity" not in entry["carried_fields"]

    def test_a_single_turn_record_carries_neither(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams")
        entry = records_written()[-1]
        assert "turn_index" not in entry
        assert "carried_fields" not in entry

    def test_a_multi_turn_record_carries_no_request_text(self, client):
        ask(client, "A4 80gsm copy paper, 20 reams", "c1")
        entry = records_written()[-1]
        assert "request_text" not in entry
        assert entry["request_chars"] > 0

    def test_the_recorded_turn_number_keeps_advancing(self, client):
        """BUG.md A14 — past MAX_TURNS it used to report the same number."""
        from paperlane.conversation import MAX_TURNS

        ask(client, "A4 copy paper", "c1")
        for _ in range(MAX_TURNS + 4):
            ask(client, "but red", "c1")
        numbers = [
            entry["turn_index"] for entry in records_written()
            if entry.get("turn_index") is not None
        ]
        assert numbers == list(range(1, len(numbers) + 1)), numbers


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

class TestPage:
    """The page keeps a conversation, so a salesperson can refine a request.

    The page and the JSON endpoint must merge identically — a page that
    remembered differently would be a second assistant wearing the same name.
    """

    def _conversation_id(self, client: TestClient) -> str:
        import re

        page = client.get("/").text
        match = re.search(r'name="conversation_id"[^>]*value="([^"]+)"', page, re.S)
        assert match is not None, "the page must carry a conversation id"
        return match.group(1)

    def test_each_page_load_gets_its_own_conversation(self, client):
        first = self._conversation_id(client)
        second = self._conversation_id(client)
        assert first != second

    def test_a_second_turn_on_the_page_is_refined(self, client):
        cid = self._conversation_id(client)
        client.post("/ask", data={
            "request": "A4 80gsm copy paper, 20 reams", "conversation_id": cid,
        })
        second = client.post("/ask", data={
            "request": "make it 50", "conversation_id": cid,
        })
        assert second.status_code == 200
        assert "50 &times;" in second.text or "50 ×" in second.text
        assert "Remembered from your earlier message" in second.text

    def test_the_page_shows_which_turn_it_is(self, client):
        cid = self._conversation_id(client)
        client.post("/ask", data={"request": "A4 copy paper, 20 reams",
                                  "conversation_id": cid})
        second = client.post("/ask", data={"request": "make it 50",
                                           "conversation_id": cid})
        assert "Turn 2" in second.text
        assert "remembered:" in second.text

    def test_a_page_request_without_an_id_has_no_conversation_bar(self, client):
        response = client.post("/ask", data={"request": "A4 copy paper, 20 reams"})
        assert response.status_code == 200
        assert "conversation-bar" not in response.text

    def test_the_page_never_echoes_the_conversation_id(self, client):
        """The id is caller-supplied, so it must not be reflected into the page.

        It is a valid id (under the length bound), not an unusable one — which is
        exactly why this matters: a well-formed hostile id reaches the store and
        must still not appear in the HTML.
        """
        cid = "<script>alert(1)</script>"
        response = client.post("/ask", data={"request": "A4 copy paper",
                                             "conversation_id": cid})
        assert response.status_code == 200
        assert "<script>alert(1)</script>" not in response.text
        assert "conversation-bar" in response.text, "the panel still renders"
