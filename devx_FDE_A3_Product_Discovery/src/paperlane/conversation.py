"""Conversation memory: carrying requirements from one turn to the next.

The design constraint that shapes this module is stated in ``design.md`` D1: the
merge happens **after** interpretation, over typed ``Criteria``, and the model
never sees the conversation. Every constraint in a merged result is therefore
traceable to a turn that stated it. A model that could see the transcript could
produce a constraint appearing in no turn, which in the output is
indistinguishable from a hallucination.

The consequence is that the merge rule has to do the work a human would: decide
whether this turn continues the last one, and which fields survive. That rule is
:func:`merge_turn`, a pure function, so it is testable as a table rather than
through a server.

Two things are deliberately *not* here:

* **No request text.** The store holds ``Criteria``. The observability spec's
  decision about raw text applies to conversations for the same reason, and a
  conversation is the more dangerous place to keep it.
* **No implicit sessions.** A conversation exists because a caller named one.
  Nothing is inferred from the request text, and no request without an id
  touches a store at all.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterator, Protocol

from .criteria import Criteria

#: How many distinct conversations are retained. A caller supplies the id, so
#: without a bound this store is a memory-exhaustion vector: send a fresh id per
#: request and the process grows without limit. The bound is therefore a
#: security property, not housekeeping, and a test asserts it.
MAX_CONVERSATIONS = 100

#: How many turns per conversation are retained. Beyond this a conversation is
#: usually archaeology -- the customer has changed their mind enough times that
#: the merged criteria no longer describe anything they said. The merged
#: *criteria* are kept regardless; only the retained turn count is capped.
MAX_TURNS = 20

#: The maximum length of a conversation id. Long enough for a UUID, short enough
#: that a caller cannot use the id itself as a payload.
MAX_ID_LENGTH = 128

#: Fields whose presence means the customer named a new subject. Used by the
#: continuation rule -- see ``design.md`` D3.
#:
#: Weight is deliberately **not** here. "Make it 100 gsm instead" is a
#: correction to a paper that is already the subject, and treating it as a new
#: subject would discard the size and category the customer had already given.
#: A product kind or a size is the customer naming a *thing*; a weight is the
#: customer adjusting one.
SUBJECT_FIELDS = ("category", "size_code")


class ConversationInvalid(ValueError):
    """A conversation id that cannot be used."""


@dataclass(frozen=True)
class Turn:
    """One turn, as the store retains it.

    Carries the criteria *after* merging, plus what was carried into them. The
    request text is absent by construction -- there is no field for it, so it
    cannot be stored by accident.
    """

    index: int
    criteria: Criteria
    carried: frozenset[str] = frozenset()
    outcome: str | None = None


@dataclass
class Conversation:
    """A conversation: the current criteria and the turns that produced them."""

    id: str
    criteria: Criteria = field(default_factory=Criteria)
    turns: list[Turn] = field(default_factory=list)
    #: How many turns this conversation has ever had. Kept apart from
    #: ``len(turns)`` because the store trims the retained history to
    #: ``MAX_TURNS``: deriving the turn number from the retained list made it
    #: saturate at ``MAX_TURNS + 1`` and stopped distinguishing turns (A14).
    turns_seen: int = 0

    @property
    def turn_index(self) -> int:
        """The index the *next* turn will have, 1-based.

        ``len(turns)`` is a floor, not the source: a conversation assembled by
        hand, or read from a file written before this counter existed, still
        numbers its next turn after the turns it is holding.
        """
        return max(self.turns_seen, len(self.turns)) + 1


@dataclass(frozen=True)
class MergeResult:
    """What a merge decided.

    ``continued`` is False for a fresh request, which is the signal a caller uses
    to replace the conversation's criteria rather than extend them.
    """

    criteria: Criteria
    carried: frozenset[str] = frozenset()
    continued: bool = False
    #: Why the verdict was reached, for the reply and for the tests. Never shown
    #: to a customer verbatim.
    reason: str = ""


def _stated(criteria: Criteria, name: str) -> bool:
    """Did this turn state ``name`` explicitly?"""
    value = getattr(criteria, name, None)
    if value is None:
        return False
    # An empty note tuple is the default, not a statement; a zero quantity is
    # rejected by validation before this point, so it never appears here.
    return True


def _states_something(criteria: Criteria) -> bool:
    """Did this turn state any requirement at all, filterable or commercial?

    A budget or a quantity is a statement even though neither filters the
    catalog, so this is broader than :meth:`Criteria.has_any_constraint`.
    """
    if criteria.has_any_constraint():
        return True
    if criteria.quantity is not None:
        return True
    if criteria.budget_per_unit is not None:
        return True
    return False


#: A bare number, with no unit word: "make it 50", "actually 30".
#:
#: Consulted only for a turn already being treated as a refinement, and only
#: when that turn produced no quantity. The general quantity parser requires a
#: unit ("50 reams") on purpose: a bare number in a *fresh* request is usually a
#: size or a weight, and reading "A4 80gsm" as a quantity of 80 would be a
#: serious misreading. In a refinement there is no such ambiguity — the subject
#: is already fixed, so a lone number can only be the quantity.
_BARE_QUANTITY = re.compile(r"(?<![\d.])(\d{1,6})(?![\d.]*\s*(?:gsm|g/m2|mm|%))", re.I)


def bare_quantity(text: str) -> int | None:
    """A lone number in a refinement turn, as the new quantity."""
    if not text:
        return None
    for match in _BARE_QUANTITY.finditer(text):
        value = int(match.group(1))
        if value > 0:
            return value
    return None


def is_continuation(previous: Criteria | None, current: Criteria) -> tuple[bool, str]:
    """Does ``current`` refine ``previous``, or start a new subject?

    A turn is a continuation when it names no new subject -- no category or size
    -- and a fresh request when it names one. See ``design.md`` D3 for why this
    is the rule and what it costs.

    A turn that understood *nothing* is a fresh request, unless it carries a bare
    number ("make it 50"), which in a refinement can only be the quantity.
    Treating an empty turn as a continuation would silently re-answer the
    previous question, which looks exactly like the assistant ignoring what was
    just said.
    """
    if previous is None or not _states_something(previous):
        return False, "no earlier requirements to continue"

    for name in SUBJECT_FIELDS:
        if _stated(current, name):
            return False, f"the turn states {name}, which names a new subject"

    if not _states_something(current):
        if bare_quantity(current.raw_text) is None:
            return False, "the turn stated no requirement to merge"
        return True, "the turn restates the quantity"

    return True, "the turn refines the earlier requirements"


def continuation_basis(conversation: Conversation) -> Criteria | None:
    """The stored criteria a new turn merges onto, or ``None`` if there is none.

    Exists so the "is there anything to continue" question is asked in exactly
    one place. It was previously asked at every call site with
    ``criteria.has_any_constraint()``, which is False for a turn whose only
    requirement was a quantity or a budget — so such a conversation was thrown
    away and the next turn started over (BUG.md A12).
    """
    return conversation.criteria if _states_something(conversation.criteria) else None


#: Every field that can carry forward. ``raw_text`` is excluded on purpose: the
#: merged criteria describe requirements, and the previous turn's sentence is
#: not one of them.
MERGEABLE_FIELDS = (
    "category",
    "size_code",
    "weight_gsm",
    "weight_gsm_min",
    "weight_gsm_max",
    "colour_name",
    "colour_mode",
    "finish",
    "sides",
    "quantity",
    "budget_per_unit",
    "budget_basis",
    "colour_ambiguous",
)


def merge_turn(
    previous: Criteria | None,
    current: Criteria,
) -> MergeResult:
    """Merge one turn onto the conversation's criteria. Pure.

    Field by field: the current turn wins where it stated a value, and the
    earlier value survives only where it did not. ``None`` means "not stated"
    everywhere in ``Criteria``, which is what makes this expressible at all.

    ``raw_text`` is always the current turn's, because the merged criteria are
    being used to answer *this* request.
    """
    continued, reason = is_continuation(previous, current)
    if not continued or previous is None:
        return MergeResult(criteria=current, carried=frozenset(),
                           continued=False, reason=reason)

    merged = current
    carried: set[str] = set()

    # "Make it 50" states no quantity the general parser can see, because it has
    # no unit word. In a refinement the subject is fixed, so a bare number is the
    # new quantity and is applied *here* rather than carried — the customer just
    # stated it, so it must not be disclosed as remembered.
    #
    # Skipped when the turn states a budget: "under 130 a pack" also contains a
    # bare number, and reading the budget as the quantity is a wrong total, not a
    # cosmetic slip. Ambiguity resolves to "not stated", which leaves the earlier
    # quantity in place.
    # ponytail: a turn carrying both a bare quantity and a budget keeps the
    # budget and drops the bare number. Resolve per-number (skip the one the
    # budget consumed) if that ever shows up in a real request.
    if merged.quantity is None and merged.budget_per_unit is None:
        restated = bare_quantity(merged.raw_text)
        if restated is not None:
            merged = replace(merged, quantity=restated)

    for name in MERGEABLE_FIELDS:
        if _stated(merged, name):
            # An explicit value always wins. This is what makes a correction
            # correct: "no, 100 gsm" after "80 gsm" must yield 100 gsm.
            continue
        earlier = getattr(previous, name, None)
        if earlier is None:
            continue
        # `colour_ambiguous=False` and `budget_basis`'s default are values, not
        # statements, so they are only carried when they differ from the default.
        if name == "colour_ambiguous" and earlier is False:
            continue
        if name == "budget_basis" and earlier == Criteria().budget_basis:
            continue
        merged = replace(merged, **{name: earlier})
        carried.add(name)

    # The previous turn's notes are disclosure about the *previous* text, so
    # they are not carried. A stale "size: B5 is not stocked" attached to a new
    # turn would read as a fresh finding.

    # Sources are the union of what was carried now and what was already carried
    # before, minus anything this turn restated -- a field the customer just
    # said again is current, not remembered.
    inherited = set(previous.sources) & carried
    merged = replace(merged, sources=frozenset(carried | inherited))

    return MergeResult(criteria=merged, carried=frozenset(carried),
                       continued=True, reason=reason)


def validate_id(conversation_id: str) -> str:
    """Reject an id that cannot be used as a label."""
    if not isinstance(conversation_id, str):
        raise ConversationInvalid("a conversation id must be a string")
    trimmed = conversation_id.strip()
    if not trimmed:
        raise ConversationInvalid("a conversation id must not be blank")
    if len(trimmed) > MAX_ID_LENGTH:
        raise ConversationInvalid(
            f"a conversation id must be at most {MAX_ID_LENGTH} characters"
        )
    return trimmed


class ConversationStore(Protocol):
    """What every store must do. Deliberately tiny."""

    def get(self, conversation_id: str) -> Conversation | None: ...
    def put(self, conversation: Conversation) -> None: ...
    def forget(self, conversation_id: str) -> bool: ...
    def ids(self) -> list[str]: ...


class InMemoryConversationStore:
    """The default: bounded, thread-safe, and gone when the process is.

    Least-recently-used eviction. "Used" means read or written, because a
    conversation that is being continued is being used even if its criteria did
    not change.
    """

    def __init__(
        self,
        *,
        max_conversations: int = MAX_CONVERSATIONS,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.max_conversations = max_conversations
        self.max_turns = max_turns
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def get(self, conversation_id: str) -> Conversation | None:
        key = validate_id(conversation_id)
        with self._lock:
            found = self._items.pop(key, None)
            if found is None:
                return None
            # Re-insert to mark as most recently used.
            self._items[key] = found
            return _copy(found)

    def put(self, conversation: Conversation) -> None:
        key = validate_id(conversation.id)
        with self._lock:
            stored = _copy(conversation)
            stored.turns = stored.turns[-self.max_turns:]
            self._items.pop(key, None)
            self._items[key] = stored
            while len(self._items) > self.max_conversations:
                oldest = next(iter(self._items))
                del self._items[oldest]

    def forget(self, conversation_id: str) -> bool:
        key = validate_id(conversation_id)
        with self._lock:
            return self._items.pop(key, None) is not None

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._items)


class JsonlConversationStore:
    """A file-backed store, so a CLI conversation survives the process.

    Append-only: each ``put`` writes a whole conversation state as one line, and
    the newest line for an id wins on load. That is simpler than rewriting the
    file and it means a crash mid-write costs at most the last turn.

    The file is bounded the same way the in-memory store is: on load, only the
    newest ``max_conversations`` ids are kept, and each conversation keeps only
    its newest ``max_turns`` turns.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_conversations: int = MAX_CONVERSATIONS,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self.path = Path(path)
        self.max_conversations = max_conversations
        self.max_turns = max_turns
        self._lock = threading.Lock()
        self._items: dict[str, Conversation] = {}
        self._load()

    # -- persistence ----------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # A truncated final line from a killed process is expected,
                    # not a reason to lose the whole history.
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("forgotten"):
                    # A deletion, which must beat any earlier state for that id.
                    try:
                        self._items.pop(validate_id(record["id"]), None)
                    except (KeyError, ConversationInvalid):
                        pass
                    continue
                conversation = _from_json(record)
                if conversation is None:
                    continue
                self._items.pop(conversation.id, None)
                self._items[conversation.id] = conversation
        while len(self._items) > self.max_conversations:
            oldest = next(iter(self._items))
            del self._items[oldest]

    def _append(self, conversation: Conversation) -> None:
        self._append_raw(_to_json(conversation))

    def _append_raw(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    # -- protocol -------------------------------------------------------

    def get(self, conversation_id: str) -> Conversation | None:
        key = validate_id(conversation_id)
        with self._lock:
            found = self._items.pop(key, None)
            if found is None:
                return None
            self._items[key] = found
            return _copy(found)

    def put(self, conversation: Conversation) -> None:
        key = validate_id(conversation.id)
        with self._lock:
            stored = _copy(conversation)
            stored.turns = stored.turns[-self.max_turns:]
            self._items.pop(key, None)
            self._items[key] = stored
            while len(self._items) > self.max_conversations:
                oldest = next(iter(self._items))
                del self._items[oldest]
            self._append(stored)

    def forget(self, conversation_id: str) -> bool:
        key = validate_id(conversation_id)
        with self._lock:
            removed = self._items.pop(key, None) is not None
            if removed:
                # A tombstone, so a restart does not resurrect the conversation
                # by replaying an older line. It is a distinct record kind, not
                # an empty conversation: a conversation with no criteria is a
                # legitimate state (a turn that understood nothing) and would
                # otherwise be indistinguishable from a deletion.
                self._append_raw({"id": key, "forgotten": True})
        return removed

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._items)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _criteria_to_json(criteria: Criteria) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name in MERGEABLE_FIELDS + ("notes", "sources"):
        value = getattr(criteria, name, None)
        if value is None:
            continue
        if isinstance(value, frozenset):
            payload[name] = sorted(value)
        elif isinstance(value, tuple):
            payload[name] = list(value)
        elif name == "budget_per_unit":
            # A Money, not a Decimal: store the integer satang, which is the
            # project's canonical money representation and round-trips exactly.
            payload[name] = value.satang
        else:
            payload[name] = value
    return payload


def _criteria_from_json(payload: dict[str, Any]) -> Criteria:
    from .money import Money

    kwargs: dict[str, Any] = {}
    for name in MERGEABLE_FIELDS + ("notes", "sources"):
        if name not in payload:
            continue
        value = payload[name]
        if name == "sources":
            kwargs[name] = frozenset(value)
        elif name == "notes":
            kwargs[name] = tuple(value)
        elif name == "budget_per_unit":
            kwargs[name] = Money(value)
        else:
            kwargs[name] = value
    return Criteria(**kwargs)


def _to_json(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "criteria": _criteria_to_json(conversation.criteria),
        "turns_seen": conversation.turns_seen,
        "turns": [
            {
                "index": turn.index,
                "criteria": _criteria_to_json(turn.criteria),
                "carried": sorted(turn.carried),
                "outcome": turn.outcome,
            }
            for turn in conversation.turns
        ],
    }


def _from_json(record: dict[str, Any]) -> Conversation | None:
    try:
        conversation_id = validate_id(record["id"])
    except (KeyError, ConversationInvalid):
        return None
    criteria = _criteria_from_json(record.get("criteria") or {})
    turns = []
    for raw in record.get("turns") or []:
        turns.append(
            Turn(
                index=raw.get("index", len(turns) + 1),
                criteria=_criteria_from_json(raw.get("criteria") or {}),
                carried=frozenset(raw.get("carried") or ()),
                outcome=raw.get("outcome"),
            )
        )
    return Conversation(
        id=conversation_id,
        criteria=criteria,
        turns=turns,
        turns_seen=int(record.get("turns_seen") or 0),
    )


def _copy(conversation: Conversation) -> Conversation:
    """A defensive copy, so a caller cannot mutate stored state."""
    return Conversation(
        id=conversation.id,
        criteria=conversation.criteria,
        turns=list(conversation.turns),
        turns_seen=conversation.turns_seen,
    )


# ---------------------------------------------------------------------------
# Recording a turn
# ---------------------------------------------------------------------------

def record_turn(
    conversation: Conversation,
    result: MergeResult,
    *,
    outcome: str | None = None,
) -> Conversation:
    """Return a new conversation with this turn appended.

    Appending a turn never mutates the argument: the store hands out copies, and
    a caller that got a copy must not be able to change history by holding on to
    it.
    """
    turn = Turn(
        index=conversation.turn_index,
        criteria=result.criteria,
        carried=result.carried,
        outcome=outcome,
    )
    return Conversation(
        id=conversation.id,
        criteria=result.criteria,
        turns=list(conversation.turns) + [turn],
        turns_seen=turn.index,
    )


def iter_stored_text(store: ConversationStore) -> Iterator[str]:
    """Every string the store holds. Used by the test that proves no text is kept.

    Not a public API — it exists so the "no request text is stored" guarantee is
    checkable by inspection rather than by reading the schema and hoping.
    """
    for conversation_id in store.ids():
        conversation = store.get(conversation_id)
        if conversation is None:
            continue
        yield from _strings_in(_to_json(conversation))


def _strings_in(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings_in(item)
