"""The single-turn path is unchanged, proved against a recorded digest.

Task 4.10 asks for a test that the original evaluation cases produce
byte-identical replies after conversation memory was added. That claim is the
one that lets the original 28-case evaluation keep measuring what it claims to,
so it is worth more than a hand-check: it is a digest of every reply, recorded
from the code *before* the feature existed (commit `d4a67db`, the commit before
the conversation work) and asserted on every run.

How the digest was taken, so it can be retaken honestly:

    git worktree add /tmp/base d4a67db
    PYTHONPATH=/tmp/base/devx_FDE_A3_Product_Discovery/src python /tmp/replay_check.py

where the script validates the rule interpretation of each case and stores
``{"outcome", "text"}`` per case number. The same script run against this tree
produced the digest below with **0 differences across 28 cases**.

If this test ever fails, the question is not "update the digest". It is "which
single-turn reply changed, and why" — a changed reply here means memory altered
behaviour for a request that named no conversation.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from paperlane import catalog
from paperlane.assistant import answer
from paperlane.evaluate import load_cases
from paperlane.interpret import interpret_rules, validate

#: SHA-256 of the JSON of every case's {outcome, text}, sorted and compact.
#: Recorded from the tree at `d4a67db`, before conversation memory existed.
#:
#: **Retaken 2026-10-27** for the PR7 fix (BUG.md A21), which is not a memory
#: change: case 18 (*"budget 1500 including VAT"*) now compares against the
#: VAT-inclusive unit price, so its reply states 111.96 where it stated 104.64.
#: Case 18 is the only one of the 28 whose reply changed, and it changed because
#: the basis is now applied rather than labelled. Every other case is unchanged,
#: which is the property this digest exists to protect.
PRE_CHANGE_DIGEST = (
    "bc42a65324ddac01110b48e4ffe7afdf53704f31ecaa1d6f086e2e32fdd256b7"
)


@pytest.fixture(scope="module")
def replies():
    if not catalog.snapshot_exists():
        pytest.skip("no committed catalog snapshot")
    products = catalog.load_products()
    facts = catalog.load_price_facts()

    collected: dict[str, dict[str, str]] = {}
    for case in load_cases():
        try:
            criteria = validate(interpret_rules(case.request))
        except Exception as exc:  # noqa: BLE001
            collected[str(case.number)] = {"error": str(exc)}
            continue
        reply = answer(criteria, products, facts)
        collected[str(case.number)] = {"outcome": reply.outcome, "text": reply.text}
    return collected


class TestSingleTurnUnchanged:
    def test_every_case_still_produces_the_same_reply(self, replies):
        blob = json.dumps(replies, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode()).hexdigest()
        assert digest == PRE_CHANGE_DIGEST, (
            "a single-turn reply changed. Find which one before touching the "
            "digest: memory must not alter a request that named no conversation."
        )

    def test_the_reply_set_is_the_recorded_size(self, replies):
        """A digest over an empty set would match nothing and prove nothing."""
        assert len(replies) == 28

    def test_no_reply_carries_a_conversation_disclosure(self, replies):
        """The strongest statement of the same fact, in words rather than a hash."""
        for number, reply in replies.items():
            assert "Remembered" not in reply.get("text", ""), (
                f"case {number} mentions remembering with no conversation id"
            )
