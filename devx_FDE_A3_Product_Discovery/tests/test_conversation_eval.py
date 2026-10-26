"""The conversation harness: it must be able to fail.

An evaluation that only ever reports pass is a decoration. These tests pin the
two properties that make the conversation results mean something: the harness
runs the committed case file and agrees with it, and it *rejects* a case file
whose expectations are wrong. The second is the one that matters — it is the
reason the first can be believed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperlane import catalog
from paperlane.conversation_eval import (
    DEFAULT_CONVERSATION_CASES_PATH,
    load_conversation_cases,
    replay_single_turn,
    run_conversation,
    run_conversation_eval,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "eval" / "conversation-cases.json"
NEGATIVE = ROOT / "eval" / "conversation-negative-control.json"


@pytest.fixture(scope="module")
def snapshot():
    """The committed catalog, loaded once: these tests only read it."""
    if not catalog.snapshot_exists():
        pytest.skip("no committed catalog snapshot")
    return catalog.load_products(), catalog.load_price_facts()


# ---------------------------------------------------------------------------
# The recorded set
# ---------------------------------------------------------------------------

class TestRecordedCases:
    def test_the_case_file_parses(self):
        cases = load_conversation_cases()
        assert len(cases) >= 6, "the brief asks for at least six sequences"
        assert all(case.turns for case in cases)

    def test_every_case_says_what_it_proves(self):
        for case in load_conversation_cases():
            assert case.proves, f"case {case.number} does not say what it proves"
            assert case.name

    def test_every_case_passes(self, snapshot):
        products, facts = snapshot
        for case in load_conversation_cases():
            result = run_conversation(case, products=products, facts=facts)
            assert result.verdict == "pass", (
                f"case {case.number} ({case.name}) failed: "
                f"{[t.notes for t in result.turns if t.notes]}"
            )

    def test_a_new_subject_case_exists(self):
        """Task 7.2. Named rather than inferred, so removing it is visible."""
        names = " ".join(case.name for case in load_conversation_cases())
        assert "new subject" in names

    def test_a_correction_case_exists(self):
        names = " ".join(case.name for case in load_conversation_cases())
        assert "correction" in names

    def test_an_unusable_refinement_case_exists(self):
        """Task 7.5: an invalid merge asks rather than quotes."""
        cases = load_conversation_cases()
        expected_error = [
            case for case in cases
            if any(turn.expect_outcome == "error" for turn in case.turns)
        ]
        assert expected_error, "no case asserts that an unusable merge asks"


# ---------------------------------------------------------------------------
# The harness can fail
# ---------------------------------------------------------------------------

class TestTheHarnessRejectsWrongExpectations:
    """The negative control, run as a test rather than only by hand.

    Each case in the negative file is wrong in exactly one way. If the harness
    stops detecting one of them, the corresponding recorded case has quietly
    stopped proving anything.
    """

    def test_the_negative_control_exits_non_zero(self, snapshot):
        products, facts = snapshot
        results = [
            run_conversation(case, products=products, facts=facts)
            for case in load_conversation_cases(NEGATIVE)
        ]
        assert results, "the negative control must not be empty"
        assert all(result.verdict == "fail" for result in results), (
            "every negative case must be rejected; these were not: "
            f"{[r.case.number for r in results if r.verdict != 'fail']}"
        )

    def test_a_missing_disclosure_is_caught(self, snapshot):
        products, facts = snapshot
        case = _negative("the disclosure is missing")
        result = run_conversation(case, products=products, facts=facts)
        assert any("reply should contain" in note
                   for turn in result.turns for note in turn.notes)

    def test_a_wrong_carried_field_is_caught(self, snapshot):
        products, facts = snapshot
        case = _negative("a new subject wrongly inherits")
        result = run_conversation(case, products=products, facts=facts)
        assert any("should be reported as carried" in note
                   for turn in result.turns for note in turn.notes)

    def test_a_restated_field_reported_as_carried_is_caught(self, snapshot):
        products, facts = snapshot
        case = _negative("a restated field is called remembered")
        result = run_conversation(case, products=products, facts=facts)
        assert any("the turn stated it itself" in note
                   for turn in result.turns for note in turn.notes)


def _negative(name_fragment: str):
    for case in load_conversation_cases(NEGATIVE):
        if name_fragment in case.name:
            return case
    raise AssertionError(f"no negative case named {name_fragment!r}")


# ---------------------------------------------------------------------------
# The single-turn replay
# ---------------------------------------------------------------------------

class TestSingleTurnReplay:
    def test_the_committed_cases_are_all_replayed(self, snapshot):
        products, facts = snapshot
        rows = replay_single_turn(products=products, facts=facts)
        from paperlane.evaluate import load_cases

        assert len(rows) == len(load_cases())

    def test_no_comparable_case_changed_its_reply(self, snapshot):
        """Memory must not have touched the single-turn path.

        This is task 7.6: the original set is the regression guard for the new
        feature. A case that is not comparable (a basket, priced elsewhere) is
        excluded rather than counted as a pass.
        """
        products, facts = snapshot
        rows = replay_single_turn(products=products, facts=facts)
        mismatched = [row["number"] for row in rows if row["match"] is False]
        assert not mismatched, f"cases whose reply changed: {mismatched}"

    def test_a_first_turn_never_carries_anything(self, snapshot):
        products, facts = snapshot
        for row in replay_single_turn(products=products, facts=facts):
            assert row["carried"] == [], (
                f"case {row['number']} carried {row['carried']} on turn one"
            )

    def test_not_comparable_is_not_counted_as_a_match(self, snapshot):
        """A basket case has no assistant reply to compare, and says so."""
        products, facts = snapshot
        rows = replay_single_turn(products=products, facts=facts)
        not_comparable = [row for row in rows if row["match"] is None]
        for row in not_comparable:
            assert row["notes"], "an excluded case must state its reason"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

class TestTheCommand:
    def test_it_exits_zero_on_the_recorded_set(self, capsys):
        assert run_conversation_eval() == 0
        out = capsys.readouterr().out
        assert "failed: 0" in out

    def test_it_exits_non_zero_on_the_negative_control(self, capsys):
        assert run_conversation_eval(cases_path=NEGATIVE) == 1

    def test_the_json_payload_states_the_catalog(self, capsys):
        run_conversation_eval(as_json=True)
        payload = json.loads(capsys.readouterr().out)
        assert payload["catalog"] == "v1"
        assert payload["kind"] == "conversations"
        assert payload["snapshot"]["products"] > 0
        assert payload["summary"]["replay_compared"] > 0

    def test_a_missing_snapshot_is_a_failure_not_a_crash(self, tmp_path, capsys):
        code = run_conversation_eval(db_path=tmp_path / "absent.duckdb")
        assert code == 1
        assert "No catalog snapshot" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The render
# ---------------------------------------------------------------------------

class TestTheRender:
    def test_na_is_not_rendered_as_a_failure(self, capsys):
        """A case stating no reply expectations was never assessed on reply.

        The per-conversation table once folded ``n/a`` into ``fail`` and printed
        a defect that did not exist. The counts below the table were right, which
        is exactly how that kind of bug survives: one half of the output
        contradicted the other.
        """
        run_conversation_eval()
        out = capsys.readouterr().out
        for line in out.splitlines():
            if line.strip().startswith("8 ") and "unusable refinement" in line:
                assert "fail" not in line
                assert "n/a" in line
                return
        raise AssertionError("case 8 not found in the rendered table")
