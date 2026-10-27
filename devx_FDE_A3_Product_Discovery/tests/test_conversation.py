"""Conversation memory: the merge rule, the stores, and what must never happen.

Two things are under test and they fail differently. The merge rule is a pure
function, so it is tested as a table of (previous, current) -> (merged, carried).
The stores are stateful, so they are tested for bounds, eviction, thread safety,
and for the one guarantee that matters most: they never hold the customer's
words.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from paperlane.conversation import (
    MAX_CONVERSATIONS,
    MAX_ID_LENGTH,
    MAX_TURNS,
    Conversation,
    ConversationInvalid,
    InMemoryConversationStore,
    JsonlConversationStore,
    bare_quantity,
    continuation_basis,
    is_continuation,
    iter_stored_text,
    merge_turn,
    record_turn,
    validate_id,
)
from paperlane.criteria import Criteria
from paperlane.interpret import interpret_rules
from paperlane.money import Money


def criteria(**kwargs) -> Criteria:
    """Criteria from explicit fields, for the merge table."""
    return Criteria(**kwargs)


def criterion_from(text: str) -> Criteria:
    """Criteria as the rule interpreter would read this sentence."""
    return interpret_rules(text)


# ---------------------------------------------------------------------------
# The continuation rule
# ---------------------------------------------------------------------------

class TestContinuationRule:
    """design.md D3, as a table.

    The rule is the whole safety argument for memory: a turn that names a new
    subject must not inherit the previous one's constraints.
    """

    def test_a_quantity_only_turn_continues(self):
        previous = criteria(category="Copy paper", size_code="A4", quantity=20)
        current = criteria(quantity=50)
        continued, _ = is_continuation(previous, current)
        assert continued

    def test_a_budget_only_turn_continues(self):
        previous = criteria(category="Copy paper", size_code="A4")
        current = criteria(budget_per_unit=Money(10_000))
        continued, reason = is_continuation(previous, current)
        assert continued
        assert "refines" in reason

    def test_a_turn_that_understood_nothing_starts_fresh(self):
        """Silently re-answering the previous question looks like being ignored."""
        previous = criteria(category="Copy paper", size_code="A4")
        continued, reason = is_continuation(previous, criteria())
        assert not continued
        assert "no requirement" in reason

    def test_a_stated_size_starts_fresh(self):
        previous = criteria(category="Copy paper", size_code="A4", quantity=20)
        current = criteria(size_code="A5")
        continued, reason = is_continuation(previous, current)
        assert not continued
        assert "size_code" in reason

    def test_a_stated_category_starts_fresh(self):
        previous = criteria(size_code="A4", sides="double")
        current = criteria(category="Copy paper")
        continued, _ = is_continuation(previous, current)
        assert not continued

    def test_a_stated_weight_is_a_correction_not_a_new_subject(self):
        """design.md D3: a weight adjusts a thing; it does not name one.

        Treating "make it 100 gsm" as a new subject would discard the size and
        category the customer already gave, which is the opposite of helping.
        """
        previous = criteria(category="Copy paper", size_code="A4")
        current = criteria(weight_gsm=100)
        continued, _ = is_continuation(previous, current)
        assert continued

    def test_a_weight_correction_keeps_the_other_constraints(self):
        previous = criteria(category="Copy paper", size_code="A4", weight_gsm=80)
        current = criteria(weight_gsm=100)
        result = merge_turn(previous, current)
        assert result.criteria.weight_gsm == 100
        assert result.criteria.size_code == "A4"
        assert result.criteria.category == "Copy paper"

    def test_a_budget_only_turn_continues(self):
        previous = criteria(category="Copy paper", size_code="A4", quantity=20)
        current = criteria(budget_per_unit=Money(13_000))
        continued, _ = is_continuation(previous, current)
        assert continued


class TestContinuationFromACommercialOnlyTurn:
    """BUG.md A12 — a first turn may state only a quantity or only a budget.

    A quantity and a budget do not filter the catalog, so
    ``Criteria.has_any_constraint()`` says False for both. Gating the
    *earlier* criteria on that predicate threw away a conversation whose only
    requirement was commercial, and the customer's next sentence started over.
    The broader question — did this turn state *anything* — is the one that
    decides whether there is something to continue.
    """

    def test_a_quantity_only_first_turn_can_be_continued(self):
        previous = criteria(quantity=20)
        continued, _ = is_continuation(previous, criteria(quantity=50))
        assert continued, "20 packs is a statement, so turn two has a basis"

    def test_a_budget_only_first_turn_can_be_continued(self):
        previous = criteria(budget_per_unit=Money(20_000))
        continued, _ = is_continuation(previous, criteria(quantity=20))
        assert continued

    def test_a_named_subject_is_still_fresh(self):
        """A12 must not weaken D3: a size names a new subject."""
        previous = criteria(budget_per_unit=Money(20_000))
        continued, reason = is_continuation(previous, criteria(size_code="A4"))
        assert not continued
        assert "size_code" in reason

    def test_a_commercial_only_turn_is_merged_not_replaced(self):
        previous = criteria(quantity=20)
        current = criteria(budget_per_unit=Money(20_000))
        result = merge_turn(previous, current)
        assert result.continued
        assert result.criteria.quantity == 20
        assert result.criteria.budget_per_unit == Money(20_000)

    def test_an_empty_turn_is_still_not_a_basis(self):
        """The broader predicate must not also revive the empty turn."""
        continued, reason = is_continuation(criteria(), criteria(quantity=5))
        assert not continued
        assert "no earlier" in reason


class TestBareQuantity:
    """"Make it 50" — a refinement whose quantity has no unit word.

    The general quantity parser requires a unit, because a bare number in a fresh
    request is often a size or a weight. A refinement has no such ambiguity, so
    the merge layer reads the number. Getting this wrong in the other direction —
    reading a budget as a quantity — is a wrong total, so that is tested too.
    """

    def test_a_bare_number_in_a_refinement_becomes_the_quantity(self):
        previous = criterion_from("A4 80gsm copy paper, 20 reams")
        current = criterion_from("make it 50")
        result = merge_turn(previous, current)
        assert result.continued
        assert result.criteria.quantity == 50

    def test_a_restated_quantity_is_not_reported_as_remembered(self):
        previous = criterion_from("A4 80gsm copy paper, 20 reams")
        current = criterion_from("make it 50")
        result = merge_turn(previous, current)
        assert "quantity" not in result.carried
        assert "quantity" not in result.criteria.sources

    def test_a_bare_number_keeping_the_rest(self):
        previous = criterion_from("A4 80gsm copy paper, 20 reams")
        current = criterion_from("make it 50")
        result = merge_turn(previous, current)
        assert result.criteria.size_code == "A4"
        assert result.criteria.category == "Copy paper"
        assert result.criteria.weight_gsm == 80

    def test_a_budget_number_is_not_adopted_as_the_quantity(self):
        previous = criterion_from("A4 80gsm copy paper, 20 reams")
        current = criterion_from("and under 130 a pack")
        result = merge_turn(previous, current)
        assert result.criteria.quantity == 20, "130 is the budget, not the quantity"
        assert result.criteria.budget_per_unit == Money(13_000)
        assert "quantity" in result.carried

    def test_a_unit_bearing_quantity_still_wins(self):
        previous = criterion_from("A4 80gsm copy paper, 20 reams")
        current = criterion_from("actually 50 reams")
        result = merge_turn(previous, current)
        assert result.criteria.quantity == 50

    def test_bare_quantity_ignores_a_weight(self):
        assert bare_quantity("make it 80 gsm") is None

    def test_a_bare_number_that_is_also_a_grammage_is_the_quantity(self):
        """BUG.md A17.

        "100" is both a plausible quantity and a catalog grammage, so the rule
        interpreter reads it as 100 gsm before the merge sees the turn. In a
        refinement it is the quantity: the customer is changing the number they
        have been changing, not swapping the paper.
        """
        previous = criterion_from(
            "PaperLane Card A4 160gsm Assorted Pastels, 10 reams"
        )
        result = merge_turn(previous, criterion_from("change it to 100"))

        assert result.continued
        assert result.criteria.quantity == 100
        assert result.criteria.weight_gsm == 160, "100 is the quantity, not a weight"
        assert "weight_gsm" in result.carried

    def test_the_weight_a_bare_quantity_kept_is_disclosed(self):
        """The carried weight is visible, so a wrong reading can be corrected."""
        previous = criterion_from(
            "PaperLane Card A4 160gsm Assorted Pastels, 10 reams"
        )
        result = merge_turn(previous, criterion_from("change it to 130"))
        assert result.criteria.quantity == 130
        assert result.criteria.weight_gsm == 160
        assert "weight_gsm" in result.carried
        assert "quantity" not in result.carried

    def test_an_explicit_weight_is_still_a_correction(self):
        """A17 must not weaken D4: a unit word makes the number a weight."""
        previous = criterion_from("A4 80gsm copy paper, 20 reams")
        result = merge_turn(previous, criterion_from("make it 100 gsm"))

        assert result.criteria.weight_gsm == 100
        assert result.criteria.quantity == 20, "the quantity was not restated"

    def test_bare_quantity_reads_a_plain_number(self):
        assert bare_quantity("make it 50") == 50
        assert bare_quantity("no words here") is None

    def test_no_previous_is_fresh(self):
        continued, reason = is_continuation(None, criteria(quantity=5))
        assert not continued
        assert "no earlier" in reason

    def test_previous_with_no_constraints_is_fresh(self):
        continued, _ = is_continuation(criteria(), criteria(quantity=5))
        assert not continued

    def test_a_new_subject_mid_conversation_does_not_inherit(self):
        """The failure the scope cut was protecting against, stated directly."""
        flyers = interpret_rules("flyers, double sided, 20 packs")
        paper = interpret_rules("A4 copy paper")
        result = merge_turn(flyers, paper)
        assert not result.continued
        # None of the flyer constraints survived.
        assert result.criteria.sides is None
        assert result.criteria.category == "Copy paper"
        assert result.criteria.size_code == "A4"


# ---------------------------------------------------------------------------
# The merge itself
# ---------------------------------------------------------------------------

class TestMerge:
    def test_an_unstated_field_is_carried(self):
        previous = criteria(category="Copy paper", size_code="A4")
        current = criteria(quantity=20)
        # quantity alone is not a subject, so this continues.
        result = merge_turn(previous, current)
        assert result.continued
        assert result.criteria.size_code == "A4"
        assert result.criteria.category == "Copy paper"
        assert "size_code" in result.carried

    def test_an_explicit_field_wins(self):
        previous = criteria(weight_gsm=80, size_code="A4")
        current = criteria(weight_gsm=100)
        result = merge_turn(previous, current)
        assert result.criteria.weight_gsm == 100
        assert "weight_gsm" not in result.carried
        # The untouched field is still carried.
        assert result.criteria.size_code == "A4"

    def test_a_carried_quantity_is_marked(self):
        previous = criteria(size_code="A4", quantity=20)
        current = criteria(budget_per_unit=Money(10_000))
        result = merge_turn(previous, current)
        assert result.criteria.quantity == 20
        assert "quantity" in result.carried

    def test_merging_never_introduces_a_field(self):
        """No constraint may appear that neither turn stated."""
        previous = criteria(size_code="A4")
        current = criteria(quantity=5)
        result = merge_turn(previous, current)
        for name in ("finish", "colour_name", "colour_mode", "sides",
                     "category", "weight_gsm"):
            assert getattr(result.criteria, name) is None

    def test_merging_is_idempotent_for_the_same_turn(self):
        """Re-merging the same turn twice yields the same criteria.

        Note what this does *not* claim: merging an empty turn onto a
        conversation is a fresh request by design (D3), not a no-op, because a
        turn that understood nothing must not silently re-answer the previous
        question.
        """
        previous = criteria(category="Copy paper", size_code="A4")
        current = criteria(quantity=30)
        first = merge_turn(previous, current)
        second = merge_turn(previous, current)
        assert first.criteria.describe() == second.criteria.describe()
        assert first.carried == second.carried

    def test_the_current_turn_text_is_the_merged_text(self):
        previous = criteria(size_code="A4", raw_text="A4 paper")
        current = criteria(quantity=5, raw_text="make it 5")
        result = merge_turn(previous, current)
        assert result.criteria.raw_text == "make it 5"

    def test_previous_notes_are_not_carried(self):
        previous = criteria(size_code="A4", notes=("size: B5 is not stocked",))
        current = criteria(quantity=5)
        result = merge_turn(previous, current)
        assert result.criteria.notes == ()

    def test_carried_fields_are_recorded_in_sources(self):
        previous = criteria(category="Copy paper", size_code="A4")
        current = criteria(quantity=20)
        result = merge_turn(previous, current)
        assert "size_code" in result.criteria.sources
        assert "category" in result.criteria.sources


class TestCriteriaProvenance:
    def test_describe_is_unchanged_by_sources(self):
        plain = criteria(size_code="A4", quantity=20)
        sourced = criteria(size_code="A4", quantity=20,
                           sources=frozenset({"size_code"}))
        assert plain.describe() == sourced.describe()

    def test_describe_carried_returns_only_carried(self):
        c = criteria(size_code="A4", quantity=20, sources=frozenset({"size_code"}))
        carried = c.describe_carried()
        assert carried == {"size": "A4"}

    def test_describe_carried_is_empty_when_nothing_carried(self):
        assert criteria(size_code="A4").describe_carried() == {}

    def test_a_carried_budget_carries_its_basis(self):
        c = criteria(budget_per_unit=Money(10_000),
                     sources=frozenset({"budget_per_unit"}))
        carried = c.describe_carried()
        assert "budget_per_unit" in carried
        assert "budget_basis" in carried


# ---------------------------------------------------------------------------
# Bounds — a security property, not housekeeping
# ---------------------------------------------------------------------------

class TestBounds:
    def test_the_constants_exist(self):
        assert MAX_CONVERSATIONS > 0
        assert MAX_TURNS > 0
        assert MAX_ID_LENGTH > 0

    def test_conversation_count_is_bounded(self):
        store = InMemoryConversationStore(max_conversations=3)
        for index in range(10):
            store.put(Conversation(id=f"c{index}",
                                   criteria=criteria(size_code="A4")))
        assert len(store.ids()) == 3
        # The most recent three survive.
        assert set(store.ids()) == {"c7", "c8", "c9"}

    def test_the_oldest_is_evicted_first(self):
        store = InMemoryConversationStore(max_conversations=2)
        store.put(Conversation(id="old", criteria=criteria(size_code="A4")))
        store.put(Conversation(id="new", criteria=criteria(size_code="A5")))
        store.put(Conversation(id="newest", criteria=criteria(size_code="A3")))
        assert store.get("old") is None
        assert store.get("new") is not None

    def test_reading_counts_as_use(self):
        """A conversation being continued is in use even if it did not change."""
        store = InMemoryConversationStore(max_conversations=2)
        store.put(Conversation(id="a", criteria=criteria(size_code="A4")))
        store.put(Conversation(id="b", criteria=criteria(size_code="A5")))
        store.get("a")            # a is now most recently used
        store.put(Conversation(id="c", criteria=criteria(size_code="A3")))
        assert store.get("a") is not None, "a was read, so it should have survived"
        assert store.get("b") is None

    def test_turn_count_is_bounded(self):
        from paperlane.conversation import Turn

        store = InMemoryConversationStore(max_turns=3)
        conversation = Conversation(id="c", criteria=criteria(size_code="A4"))
        for index in range(10):
            conversation.turns.append(
                Turn(index=index + 1, criteria=criteria(quantity=index + 1))
            )
        store.put(conversation)
        stored = store.get("c")
        assert len(stored.turns) == 3
        assert [t.index for t in stored.turns] == [8, 9, 10]
        # The merged criteria are not truncated — they are the state.
        assert stored.criteria.size_code == "A4"

    def test_an_id_is_length_bounded(self):
        with pytest.raises(ConversationInvalid):
            validate_id("x" * (MAX_ID_LENGTH + 1))

    def test_a_blank_id_is_rejected(self):
        with pytest.raises(ConversationInvalid):
            validate_id("   ")

    def test_an_id_is_trimmed(self):
        assert validate_id("  abc  ") == "abc"


# ---------------------------------------------------------------------------
# What a store must never hold
# ---------------------------------------------------------------------------

class TestTurnNumbering:
    """BUG.md A14 — the turn number must not saturate at the retained cap.

    ``turn_index`` was ``len(turns) + 1`` while ``put`` trims ``turns`` to
    ``MAX_TURNS``: past that, every turn reported the same number, and
    ``records.py`` says turns are distinguished by it. The number is a
    property of the conversation's history, not of how much of it is retained.
    """

    def test_the_turn_number_keeps_advancing_past_the_cap(self):
        store = InMemoryConversationStore(max_turns=3)
        conversation = Conversation(id="c")
        for _ in range(10):
            result = merge_turn(None, criteria(quantity=5))
            conversation = record_turn(conversation, result)
            store.put(conversation)
        stored = store.get("c")
        assert len(stored.turns) == 3, "the history is still bounded"
        assert [t.index for t in stored.turns] == [8, 9, 10]
        assert stored.turn_index == 11, "the next turn number is the 11th"

    def test_turn_numbers_are_strictly_increasing(self):
        store = InMemoryConversationStore(max_turns=3)
        conversation = Conversation(id="c")
        numbers = []
        for _ in range(10):
            conversation = record_turn(conversation, merge_turn(None, criteria(quantity=5)))
            store.put(conversation)
            numbers.append(store.get("c").turns[-1].index)
        assert numbers == list(range(1, 11))

    def test_the_number_survives_a_restart(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        store = JsonlConversationStore(path, max_turns=2)
        conversation = Conversation(id="c")
        for _ in range(5):
            conversation = record_turn(conversation, merge_turn(None, criteria(quantity=5)))
            store.put(conversation)
        reopened = JsonlConversationStore(path, max_turns=2)
        assert reopened.get("c").turn_index == 6


class TestAnEmptyTurnDoesNotForget:
    """BUG.md A13 — a turn that understood nothing is answered fresh, not erased.

    D3 says such a turn is a **fresh request**: it must not silently re-answer the
    previous question. It does not say the conversation's requirements are
    discarded, and discarding them made one unparseable sentence ("hello there",
    "too expensive") end the customer's ability to refine — the opposite of what
    memory is for. The turn is answered from an empty request and is still
    recorded; the criteria the customer actually stated are kept for the next
    turn to continue from.
    """

    def test_an_empty_result_is_flagged(self):
        assert merge_turn(None, criteria()).empty is True
        assert merge_turn(criteria(size_code="A4"), criteria()).empty is True
        assert merge_turn(None, criteria(quantity=5)).empty is False

    def test_the_criteria_survive_an_empty_turn(self):
        conversation = Conversation(id="c")
        conversation = record_turn(conversation, merge_turn(None, criterion_from("A4 copy paper")))
        empty = merge_turn(conversation.criteria, criteria())
        assert empty.empty
        conversation = record_turn(conversation, empty)
        assert conversation.criteria.size_code == "A4"
        assert conversation.criteria.category == "Copy paper"

    def test_the_next_turn_continues(self):
        conversation = Conversation(id="c")
        conversation = record_turn(conversation, merge_turn(None, criterion_from("A4 copy paper")))
        conversation = record_turn(conversation, merge_turn(conversation.criteria, criteria()))
        following = merge_turn(continuation_basis(conversation), criterion_from("make it 50"))
        assert following.continued
        assert following.criteria.size_code == "A4"
        assert following.criteria.quantity == 50

    def test_the_empty_turn_is_still_recorded(self):
        conversation = Conversation(id="c")
        conversation = record_turn(conversation, merge_turn(None, criteria()))
        assert len(conversation.turns) == 1
        assert conversation.turn_index == 2

    def test_a_stated_subject_still_replaces_the_criteria(self):
        """Only an empty turn preserves; naming a subject still discards (D3)."""
        conversation = Conversation(id="c")
        conversation = record_turn(conversation, merge_turn(None, criterion_from("A4 copy paper, 20 reams")))
        conversation = record_turn(conversation, merge_turn(conversation.criteria, criterion_from("A5 copy paper")))
        assert conversation.criteria.size_code == "A5"
        assert conversation.criteria.quantity is None, "the new subject starts clean"


class TestNoTextStored:
    def test_the_store_holds_no_request_text(self):
        store = InMemoryConversationStore()
        request = "A4 80gsm copy paper, 20 reams, from Somchai at Acme"
        parsed = interpret_rules(request)
        store.put(record_turn(Conversation(id="c"), merge_turn(None, parsed)))

        # The customer's sentence must not be findable anywhere in the stored
        # state, including the raw_text field that Criteria carries in flight.
        held = list(iter_stored_text(store))
        for fragment in ("Somchai", "Acme", "20 reams"):
            assert not any(fragment in text for text in held), (
                f"{fragment!r} reached the store"
            )

    def test_the_jsonl_store_holds_no_request_text(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        store = JsonlConversationStore(path)
        request = "flyers for Somchai at Acme, double sided"
        parsed = interpret_rules(request)
        store.put(record_turn(Conversation(id="c"), merge_turn(None, parsed)))
        written = path.read_text()
        assert "Somchai" not in written
        assert "Acme" not in written

    def test_credentials_do_not_reach_the_store(self):
        store = InMemoryConversationStore()
        secret = "sk-" + "sentinel" + "0" * 24
        parsed = interpret_rules(f"A4 copy paper {secret}")
        store.put(record_turn(Conversation(id="c"), merge_turn(None, parsed)))
        held = list(iter_stored_text(store))
        assert not any(secret in text for text in held)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_writes_leave_a_consistent_store(self):
        store = InMemoryConversationStore(max_conversations=200)
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                for turn in range(20):
                    key = f"c{index % 5}"
                    existing = store.get(key) or Conversation(id=key)
                    result = merge_turn(
                        existing.criteria or None,
                        criteria(quantity=turn + 1),
                    )
                    store.put(record_turn(existing, result))
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"workers raised: {errors[:3]}"
        for key in store.ids():
            conversation = store.get(key)
            assert conversation is not None
            assert conversation.criteria.quantity is not None


# ---------------------------------------------------------------------------
# The file store
# ---------------------------------------------------------------------------

class TestJsonlStore:
    def test_a_conversation_survives_a_restart(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        first = JsonlConversationStore(path)
        first.put(Conversation(id="c", criteria=criteria(size_code="A4",
                                                         quantity=20)))
        # A new process reads the same file.
        second = JsonlConversationStore(path)
        found = second.get("c")
        assert found is not None
        assert found.criteria.size_code == "A4"
        assert found.criteria.quantity == 20

    def test_the_newest_state_wins(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        store = JsonlConversationStore(path)
        store.put(Conversation(id="c", criteria=criteria(quantity=5)))
        store.put(Conversation(id="c", criteria=criteria(quantity=50)))
        reopened = JsonlConversationStore(path)
        assert reopened.get("c").criteria.quantity == 50

    def test_forget_survives_a_restart(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        store = JsonlConversationStore(path)
        store.put(Conversation(id="c", criteria=criteria(quantity=5)))
        store.forget("c")
        reopened = JsonlConversationStore(path)
        assert reopened.get("c") is None

    def test_forgetting_an_unknown_id_reports_nothing_forgotten(self, tmp_path):
        store = JsonlConversationStore(tmp_path / "conversations.jsonl")
        assert store.forget("never-existed") is False

    def test_a_truncated_line_does_not_lose_the_history(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        store = JsonlConversationStore(path)
        store.put(Conversation(id="c", criteria=criteria(quantity=5)))
        # Simulate a process killed mid-write.
        with path.open("a") as handle:
            handle.write('{"id": "d", "criteria": {"size_c')
        reopened = JsonlConversationStore(path)
        assert reopened.get("c") is not None

    def test_a_money_budget_round_trips_exactly(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        store = JsonlConversationStore(path)
        store.put(Conversation(
            id="c", criteria=criteria(budget_per_unit=Money(12_345))
        ))
        reopened = JsonlConversationStore(path)
        assert reopened.get("c").criteria.budget_per_unit.satang == 12_345

    def test_the_file_store_keeps_at_most_the_maximum(self, tmp_path):
        path = tmp_path / "conversations.jsonl"
        store = JsonlConversationStore(path, max_conversations=2)
        for index in range(6):
            store.put(Conversation(id=f"c{index}", criteria=criteria(quantity=1)))
        assert len(store.ids()) == 2
        reopened = JsonlConversationStore(path, max_conversations=2)
        assert len(reopened.ids()) == 2


# ---------------------------------------------------------------------------
# Copying
# ---------------------------------------------------------------------------

class TestDefensiveCopying:
    def test_mutating_a_returned_conversation_does_not_change_the_store(self):
        store = InMemoryConversationStore()
        store.put(Conversation(id="c", criteria=criteria(quantity=5)))
        got = store.get("c")
        got.criteria = criteria(quantity=999)
        again = store.get("c")
        assert again.criteria.quantity == 5

    def test_record_turn_does_not_mutate_its_argument(self):
        conversation = Conversation(id="c")
        result = merge_turn(None, criteria(quantity=5))
        updated = record_turn(conversation, result)
        assert conversation.turns == []
        assert len(updated.turns) == 1
