"""The conversation evaluation: refinements, and the single-turn replay.

The merge rule is proven by unit tests. What a case file adds is the question a
unit test cannot ask: *would a salesperson recognise this as what the customer
meant?* A test can assert that "make it 50" merged to quantity 50; only a
recorded sequence can assert that the second turn quoted 50 reams of the paper
the first turn found, at the 50+ tier, with the delivery rule applied.

Two things are checked, and they fail differently:

* **Refinements are understood** — the conversation case file, one sequence per
  entry, asserting the merged requirements and what the reply disclosed.
* **Single-turn behaviour is untouched** — every case in ``eval/cases.json`` is
  replayed as the first turn of its own conversation and must produce the same
  reply, character for character. Without this, a regression in the single-turn
  path could hide behind a passing conversation suite.

Run with ``./run.sh eval --cases eval/conversation-cases.json``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from . import catalog
from .assistant import answer
from .conversation import Conversation, merge_turn, record_turn
from .evaluate import AXES, FAIL, NA, PASS, load_cases, run_case
from .interpret import interpret_rules, validate

#: Where the conversation cases live. Beside ``cases.json``, and deliberately a
#: separate file: the original set answers "is the assistant right?", this one
#: answers "does it still hear a refinement?", and merging them would let one
#: question's answer stand in for the other's.
DEFAULT_CONVERSATION_CASES_PATH = (
    Path(__file__).resolve().parents[2] / "eval" / "conversation-cases.json"
)

#: The axes a conversation turn is scored on. Retrieval, pricing and reply carry
#: over from the single-turn harness; ``match`` does not apply, because a
#: conversation case is about which requirements survived, not about the wording
#: of a justification. ``memory`` is the axis only this harness can assess.
CONVERSATION_AXES = ("memory", "retrieval", "pricing", "reply")


@dataclass
class TurnExpectation:
    """What one turn of a recorded conversation must produce."""

    request: str
    #: Expected outcome, when the case states one.
    expect_outcome: str | None = None
    #: Requirements the merged criteria must state. A subset check: a case names
    #: what it is about, not every field, so adding a field elsewhere does not
    #: silently rewrite an unrelated case.
    expect_criteria: dict[str, Any] = field(default_factory=dict)
    #: Requirements that must be *absent* from the merged criteria. This is how a
    #: case says "the flyer constraints did not survive" without listing every
    #: field the catalog happens to have today.
    expect_absent: tuple[str, ...] = ()
    #: Field names that must be reported as carried from an earlier turn.
    expect_carried: tuple[str, ...] = ()
    #: Field names that must *not* be reported as carried. A restated field is
    #: current, not remembered, and saying otherwise is a small lie the customer
    #: cannot check.
    expect_not_carried: tuple[str, ...] = ()
    #: Phrases the reply text must contain — the disclosure a salesperson reads.
    expect_reply_contains: tuple[str, ...] = ()
    #: Phrases the reply text must not contain.
    expect_reply_excludes: tuple[str, ...] = ()


@dataclass
class ConversationCase:
    """One recorded conversation and what each turn should produce."""

    number: int
    name: str
    proves: str
    turns: tuple[TurnExpectation, ...]
    note: str = ""


@dataclass
class TurnResult:
    """What one turn produced, and how each axis judged it."""

    index: int
    request: str
    outcome: str = ""
    criteria: dict[str, Any] = field(default_factory=dict)
    carried: tuple[str, ...] = ()
    reply_text: str = ""
    total: str | None = None
    axes: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if FAIL in self.axes.values():
            return "fail"
        return "pass"


@dataclass
class ConversationResult:
    case: ConversationCase
    turns: list[TurnResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(turn.verdict == "fail" for turn in self.turns):
            return "fail"
        return "pass"


def load_conversation_cases(path: Path | None = None) -> list[ConversationCase]:
    """Read the recorded conversation set from disk."""
    path = Path(path) if path is not None else DEFAULT_CONVERSATION_CASES_PATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[ConversationCase] = []
    for entry in raw["conversations"]:
        turns = tuple(
            TurnExpectation(
                request=turn["request"],
                expect_outcome=turn.get("expect", {}).get("outcome"),
                expect_criteria=dict(turn.get("expect", {}).get("criteria", {})),
                expect_absent=tuple(turn.get("expect", {}).get("absent", ())),
                expect_carried=tuple(turn.get("expect", {}).get("carried", ())),
                expect_not_carried=tuple(
                    turn.get("expect", {}).get("not_carried", ())
                ),
                expect_reply_contains=tuple(
                    turn.get("expect", {}).get("reply_contains", ())
                ),
                expect_reply_excludes=tuple(
                    turn.get("expect", {}).get("reply_excludes", ())
                ),
            )
            for turn in entry["turns"]
        )
        cases.append(ConversationCase(
            number=entry["number"],
            name=entry["name"],
            proves=entry["proves"],
            turns=turns,
            note=entry.get("note", ""),
        ))
    return cases


# ---------------------------------------------------------------------------
# Running one conversation
# ---------------------------------------------------------------------------

def _score_memory(expectation: TurnExpectation, turn: TurnResult) -> tuple[str, list[str]]:
    """Did the merge carry the right things, and say so?

    This is the axis that only exists here. It fails when a requirement the
    customer stated earlier is missing from what was priced, when a requirement
    they just restated is presented as remembered, or when the reply does not
    say what it remembered.
    """
    notes: list[str] = []
    verdict = PASS

    for key, expected in expectation.expect_criteria.items():
        actual = turn.criteria.get(key)
        if actual != expected:
            notes.append(f"criteria[{key!r}] is {actual!r}, expected {expected!r}")
            verdict = FAIL

    for key in expectation.expect_absent:
        if turn.criteria.get(key) is not None:
            notes.append(
                f"criteria[{key!r}] is {turn.criteria[key]!r} but should not be "
                f"present at all"
            )
            verdict = FAIL

    for key in expectation.expect_carried:
        if key not in turn.carried:
            notes.append(f"{key!r} should be reported as carried, but is not")
            verdict = FAIL

    for key in expectation.expect_not_carried:
        if key in turn.carried:
            notes.append(
                f"{key!r} is reported as carried, but the turn stated it itself"
            )
            verdict = FAIL

    return verdict, notes


def _score_text(expectation: TurnExpectation, turn: TurnResult) -> tuple[str, list[str]]:
    """Did the reply a salesperson reads say what the case expects?

    Separate from the structural axes because the disclosure requirement is about
    words: a reply that carried a quantity and only said so in a JSON field has
    not told the customer.
    """
    notes: list[str] = []
    verdict = PASS
    for phrase in expectation.expect_reply_contains:
        if phrase not in turn.reply_text:
            notes.append(f"reply should contain {phrase!r}")
            verdict = FAIL
    for phrase in expectation.expect_reply_excludes:
        if phrase in turn.reply_text:
            notes.append(f"reply should not contain {phrase!r}")
            verdict = FAIL
    return verdict, notes


def run_conversation(
    case: ConversationCase,
    *,
    products: Sequence[dict[str, Any]],
    facts,
    standalone_totals: dict[str, str] | None = None,
) -> ConversationResult:
    """Run one recorded conversation, scoring each turn.

    ``standalone_totals`` maps a request to the total the single-turn path
    produces for it. When a turn starts a fresh subject, the conversation must
    quote the same total as the standalone request — that is the assertion that
    memory did not quietly change the answer.
    """
    result = ConversationResult(case=case)
    conversation = Conversation(id=f"case-{case.number}")

    for index, expectation in enumerate(case.turns, start=1):
        turn = TurnResult(index=index, request=expectation.request)
        result.turns.append(turn)

        parsed = interpret_rules(expectation.request)
        previous = conversation.criteria if conversation.criteria.has_any_constraint() else None
        merge = merge_turn(previous, parsed)
        criteria = merge.criteria
        turn.carried = tuple(sorted(merge.carried))

        try:
            criteria = validate(criteria)
        except Exception as exc:  # noqa: BLE001 - an invalid merge is a result
            # A merge can produce something the catalog cannot price — a bare
            # "make it 500000" is a quantity out of range. That is a *result*,
            # not a harness error, so it is scored rather than aborted: the case
            # expects ``error``, nothing was priced, and the customer is told.
            # Scoring it here is what lets the case assert the important half —
            # that the assistant did not quietly fall back to quoting the
            # previous turn's quantity, which is an answer nobody asked for.
            turn.outcome = "error"
            turn.criteria = criteria.describe()
            turn.notes.append(f"merged criteria failed validation: {exc}")
            expected_error = expectation.expect_outcome == "error"
            turn.axes = {
                # The merge itself did what the case describes, and nothing was
                # priced, so those two axes have nothing to fault.
                "memory": PASS,
                "retrieval": PASS if expected_error else FAIL,
                "pricing": PASS,
                "reply": NA,
            }
            if not expected_error:
                turn.notes.append(
                    f"the merge produced an unusable request, but the case "
                    f"expected {expectation.expect_outcome!r}"
                )
            continue

        turn.criteria = criteria.describe()

        try:
            reply = answer(criteria, products, facts)
        except Exception as exc:  # noqa: BLE001
            turn.outcome = "error"
            turn.notes.append(f"answer failed: {exc}")
            turn.axes = {axis: FAIL for axis in CONVERSATION_AXES}
            continue

        turn.outcome = reply.outcome
        turn.reply_text = reply.text
        if reply.quote is not None:
            turn.total = reply.quote.total.format()

        # The conversation's state after this turn, so the next turn sees it.
        conversation = record_turn(conversation, merge, outcome=reply.outcome)

        memory_verdict, memory_notes = _score_memory(expectation, turn)
        text_verdict, text_notes = _score_text(expectation, turn)
        turn.notes.extend(memory_notes)
        turn.notes.extend(text_notes)

        outcome_verdict = PASS
        if expectation.expect_outcome is not None and turn.outcome != expectation.expect_outcome:
            turn.notes.append(
                f"outcome is {turn.outcome!r}, expected {expectation.expect_outcome!r}"
            )
            outcome_verdict = FAIL

        pricing_verdict = PASS
        if standalone_totals and not turn.carried and expectation.request in standalone_totals:
            expected_total = standalone_totals[expectation.request]
            if turn.total != expected_total:
                turn.notes.append(
                    f"a fresh turn quoted {turn.total}, but the same request on its "
                    f"own quotes {expected_total}"
                )
                pricing_verdict = FAIL
        if turn.total is None and turn.outcome == "quoted":
            turn.notes.append("a quoted outcome carried no total")
            pricing_verdict = FAIL

        turn.axes = {
            "memory": FAIL if FAIL in (memory_verdict, text_verdict) else PASS,
            "retrieval": outcome_verdict,
            "pricing": pricing_verdict,
            "reply": text_verdict if expectation.expect_reply_contains
                     or expectation.expect_reply_excludes else NA,
        }

    return result


# ---------------------------------------------------------------------------
# The single-turn replay
# ---------------------------------------------------------------------------

def replay_single_turn(
    *,
    products: Sequence[dict[str, Any]],
    facts,
    cases_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Every recorded single-turn case, as the first turn of its own conversation.

    A first turn in a conversation must be indistinguishable from the standalone
    request: same outcome, same SKUs, same total, same reply text. If that ever
    stops holding, memory has changed single-turn behaviour and the original
    evaluation is no longer measuring what it claims to.
    """
    rows: list[dict[str, Any]] = []
    for case in load_cases(cases_path):
        standalone = run_case(case, products=products, facts=facts)

        parsed = interpret_rules(case.request)
        merge = merge_turn(None, parsed)
        criteria = merge.criteria
        row: dict[str, Any] = {
            "number": case.number,
            "request": case.request,
            "standalone": standalone.verdict,
            "carried": sorted(merge.carried),
            "match": None,
            "notes": [],
        }

        if not standalone.ran:
            row["match"] = None
            row["notes"].append("not run standalone, so nothing to compare")
            rows.append(row)
            continue

        if standalone.outcome == "multi_line":
            # A basket case is priced by the multi-line path, not by the
            # assistant, so there is no single-item reply to compare against.
            # Reported as not comparable rather than as a match: a pass it did
            # not earn is worse than a stated gap.
            row["match"] = None
            row["notes"].append(
                "priced by the multi-line path, not the assistant; nothing to replay"
            )
            rows.append(row)
            continue

        if merge.carried:
            row["notes"].append(
                f"a first turn carried {sorted(merge.carried)}; it has nothing to "
                f"carry from"
            )
            rows.append(row)
            continue

        try:
            reply = answer(validate(criteria), products, facts)
        except Exception as exc:  # noqa: BLE001
            row["notes"].append(f"conversation path failed: {exc}")
            rows.append(row)
            continue

        same = (
            reply.outcome == standalone.outcome
            and reply.text == standalone.reply_text
        )
        row["match"] = same
        if not same:
            row["notes"].append(
                f"conversation path produced {reply.outcome!r}, the standalone path "
                f"produced {standalone.outcome!r}"
            )
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def run_conversation_eval(
    *,
    as_json: bool = False,
    cases_path: Path | None = None,
    db_path: Path | None = None,
    out: Any = None,
) -> int:
    """Run the conversation set and the single-turn replay. Returns a process code."""
    out = out if out is not None else sys.stdout
    snapshot_path = Path(db_path) if db_path is not None else catalog.DEFAULT_DB_PATH
    if not catalog.snapshot_exists(snapshot_path):
        print(
            f"No catalog snapshot at {snapshot_path}.\n"
            f"Build one with: ./run.sh ingest --base-url "
            f"http://localhost:8000/paperlane/",
            file=out,
        )
        return 1

    products = catalog.load_products(snapshot_path)
    facts = catalog.load_price_facts(snapshot_path)

    # Totals the single-turn path produces, so a fresh turn can be held to them.
    standalone_totals: dict[str, str] = {}
    for case in load_cases():
        if case.expect_lines:
            from .evaluate import recompute_totals

            figures = recompute_totals(list(case.expect_lines))
            standalone_totals[case.request] = figures["total"]

    results = [
        run_conversation(case, products=products, facts=facts,
                         standalone_totals=standalone_totals)
        for case in load_conversation_cases(cases_path)
    ]
    replay = replay_single_turn(products=products, facts=facts)

    payload = {
        "catalog": "v1",
        "kind": "conversations",
        "snapshot": {
            "path": str(snapshot_path),
            "products": len(products),
            "price_tiers": sum(len(f.tiers) for f in facts.values()),
        },
        "conversations": [
            {
                "number": result.case.number,
                "name": result.case.name,
                "proves": result.case.proves,
                "verdict": result.verdict,
                "turns": [
                    {
                        "index": turn.index,
                        "request": turn.request,
                        "outcome": turn.outcome,
                        "criteria": turn.criteria,
                        "carried": list(turn.carried),
                        "total": turn.total,
                        "axes": turn.axes,
                        "notes": turn.notes,
                    }
                    for turn in result.turns
                ],
            }
            for result in results
        ],
        "replay": replay,
        "summary": _summary(results, replay),
    }

    if as_json:
        json.dump(payload, out, indent=2, default=str)
        print(file=out)
    else:
        _render(payload, out=out)

    return 0 if payload["summary"]["failed"] == 0 else 1


def _summary(results: Sequence[ConversationResult], replay) -> dict[str, Any]:
    turns = [turn for result in results for turn in result.turns]
    failed_cases = [r.case.number for r in results if r.verdict == "fail"]
    compared = [row for row in replay if row["match"] is not None]
    mismatched = [row["number"] for row in compared if not row["match"]]
    return {
        "conversations": len(results),
        "turns": len(turns),
        "passed": sum(1 for r in results if r.verdict == "pass"),
        "failed": len(failed_cases),
        "failed_numbers": failed_cases,
        "by_axis": {
            axis: {
                PASS: sum(1 for t in turns if t.axes.get(axis) == PASS),
                FAIL: sum(1 for t in turns if t.axes.get(axis) == FAIL),
                NA: sum(1 for t in turns if t.axes.get(axis) == NA),
            }
            for axis in CONVERSATION_AXES
        },
        "replay_cases": len(replay),
        "replay_compared": len(compared),
        "replay_matched": sum(1 for row in compared if row["match"]),
        "replay_mismatched": mismatched,
    }


def _fold_axis(verdicts: Sequence[str]) -> str:
    """One axis verdict for a whole conversation, from its per-turn verdicts.

    ``n/a`` must not collapse into ``fail``. A case that states no reply
    expectations was never assessed on the reply axis, and printing ``fail`` for
    it would report a defect that does not exist — the same conflation the
    single-turn harness avoids by keeping ``n/a`` distinct.
    """
    if FAIL in verdicts:
        return FAIL
    if all(verdict == NA for verdict in verdicts):
        return NA
    return PASS


def _render(payload: dict[str, Any], *, out: Any = None) -> None:
    out = out if out is not None else sys.stdout
    snap = payload["snapshot"]
    print(f"Conversations against {payload['catalog']} ({snap['path']})", file=out)
    print(f"  {snap['products']} products, {snap['price_tiers']} price tiers",
          file=out)
    print(file=out)

    header = f"{'#':>3}  {'verdict':8} {'mem':5} {'retr':5} {'price':5} {'reply':5}  conversation"
    print(header, file=out)
    print("-" * len(header), file=out)
    for conversation in payload["conversations"]:
        axes = {
            axis: _fold_axis([t["axes"].get(axis) for t in conversation["turns"]])
            for axis in CONVERSATION_AXES
        }
        print(
            f"{conversation['number']:>3}  {conversation['verdict']:8} "
            f"{axes['memory']:5} {axes['retrieval']:5} "
            f"{axes['pricing']:5} {axes['reply']:5}  {conversation['name'][:44]}",
            file=out,
        )
    print(file=out)

    for conversation in payload["conversations"]:
        print(f"#{conversation['number']} {conversation['name']}", file=out)
        for turn in conversation["turns"]:
            total = f" total={turn['total']}" if turn["total"] else ""
            carried = (
                f"  carried: {', '.join(turn['carried'])}" if turn["carried"] else ""
            )
            print(
                f"   turn {turn['index']}: {turn['request'][:44]!r} -> "
                f"{turn['outcome']}{total}{carried}",
                file=out,
            )
            for note in turn["notes"]:
                print(f"      {note}", file=out)
        print(file=out)

    s = payload["summary"]
    print(
        f"conversations: {s['conversations']}  turns: {s['turns']}  "
        f"passed: {s['passed']}  failed: {s['failed']}",
        file=out,
    )
    for axis in CONVERSATION_AXES:
        counts = s["by_axis"][axis]
        print(f"  {axis:9} pass {counts[PASS]:>2}  fail {counts[FAIL]:>2}  "
              f"n/a {counts[NA]:>2}", file=out)
    print(
        f"single-turn replay: {s['replay_matched']}/{s['replay_compared']} comparable "
        f"cases produce the same reply as before "
        f"({s['replay_cases'] - s['replay_compared']} not comparable)",
        file=out,
    )
    if s["replay_mismatched"]:
        print(f"  MISMATCHED: {s['replay_mismatched']}", file=out)
