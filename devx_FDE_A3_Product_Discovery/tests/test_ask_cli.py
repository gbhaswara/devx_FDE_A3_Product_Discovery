"""The ``ask`` command: one question, answered, recorded, and exit-coded.

The command is a thin wrapper, so these tests are about the wrapper's contract
rather than about assistant behaviour — that is covered elsewhere. What they pin
is the part a wrapper can get wrong on its own: which process code each of the
four outcomes returns, that a handled request leaves exactly one record, and that
the JSON it prints is the same shape the HTTP API returns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperlane import records
from paperlane.ask_cli import run_ask

# Requests that exercise each outcome, against the committed snapshot.
QUOTED = "A4 80gsm copy paper, 20 reams"
CLARIFIED = "I need some paper"
REFUSED = "Heritage Ivory A4 100gsm, 5 reams"
NO_MATCH = "A4 300gsm card, 5 packs"


@pytest.fixture
def ask(tmp_path, monkeypatch, capsys):
    """Run ``run_ask`` with model use off and return (code, stdout, records)."""

    def _run(request: str, **kwargs) -> tuple[int, str]:
        # use_model=False keeps the suite deterministic and offline: no
        # PAPERLANE_LLM_* is configured here anyway, but stating it means a
        # developer with a model configured sees the same result.
        kwargs.setdefault("use_model", False)
        # A per-test conversation file, so a test never reads or writes the real
        # data/conversations.jsonl — that would make one test's turns visible to
        # the next and make the assertions depend on ordering.
        kwargs.setdefault("conversation_path", tmp_path / "conversations.jsonl")
        code = run_ask(request, **kwargs)
        return code, capsys.readouterr().out

    return _run


def _records() -> list[dict]:
    """Records written so far, from whichever path is configured.

    The conftest autouse fixture redirects ``PAPERLANE_RECORD_PATH`` to a
    per-test temporary file, so reading the module default would read an empty
    file and every assertion here would pass for the wrong reason.
    """
    path = records.record_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestProcessCodes:
    """A reply is an answer, not a failure.

    The distinction matters for scripting: ``./run.sh ask ... && next-step`` must
    not skip the next step because the catalog had nothing matching. Only a
    request that could not be handled at all is a non-zero exit.
    """

    @pytest.mark.parametrize(
        "request_text,expected",
        [(QUOTED, "quoted"), (CLARIFIED, "clarified"),
         (REFUSED, "refused"), (NO_MATCH, "no_match")],
    )
    def test_every_reply_outcome_exits_zero(self, ask, request_text, expected):
        code, out = ask(request_text)
        assert code == 0, f"{expected} is an answer, so it must exit 0"
        assert out.strip(), "an exit-0 answer must print something"

    def test_an_empty_request_exits_two(self, ask):
        code, out = ask("   ")
        assert code == 2
        assert "empty" in out

    def test_a_missing_snapshot_exits_two_and_names_the_path(self, ask, tmp_path):
        absent = tmp_path / "absent.duckdb"
        code, out = ask(QUOTED, db_path=absent)
        assert code == 2
        # The message must name the path that was actually checked. Naming the
        # default while checking another one sends the reader to the wrong file.
        assert str(absent) in out
        assert str(Path.cwd() / "data" / "catalog.duckdb") not in out


class TestOutput:
    def test_json_output_matches_the_api_shape(self, ask):
        code, out = ask(QUOTED, as_json=True)
        assert code == 0
        body = json.loads(out)
        # These are the keys `AssistantReply.as_dict()` emits, which is what
        # POST /api/ask returns. A CLI with its own shape would drift.
        assert body["outcome"] == "quoted"
        assert body["reply"]
        assert body["criteria"]["size"] == "A4"
        assert body["candidates"]
        assert body["breakdown"]["total"]

    def test_plain_output_is_the_reply_text(self, ask):
        code, plain = ask(QUOTED)
        code_json, as_json = ask(QUOTED, as_json=True)
        assert plain.strip() == json.loads(as_json)["reply"].strip()

    def test_verbose_explains_the_interpretation(self, ask):
        code, out = ask(QUOTED, verbose=True)
        assert code == 0
        assert "--- interpretation ---" in out
        assert "path: rules" in out
        assert "considered: 72 products" in out

    def test_verbose_is_absent_by_default(self, ask):
        code, out = ask(QUOTED)
        assert "--- interpretation ---" not in out

    def test_quantity_override_reaches_pricing(self, ask):
        code, out = ask(QUOTED, quantity=40, as_json=True)
        assert code == 0
        body = json.loads(out)
        assert body["criteria"]["quantity"] == 40
        assert all(line["quantity"] == 40 for line in body["candidates"])


class TestRecords:
    """One handled request, one record — the observability spec's first rule.

    A CLI that answered questions without recording them would make
    ``./run.sh metrics`` understate live traffic for exactly the callers most
    likely to be debugging.
    """

    def test_a_quoted_request_writes_one_record(self, ask):
        before = len(_records())
        ask(QUOTED)
        after = _records()
        assert len(after) == before + 1
        entry = after[-1]
        assert entry["endpoint"] == "cli/ask"
        assert entry["outcome"] == "quoted"

    def test_each_outcome_writes_exactly_one_record(self, ask):
        before = len(_records())
        for request_text in (QUOTED, CLARIFIED, REFUSED, NO_MATCH):
            ask(request_text)
        after = _records()
        assert len(after) == before + 4, "one record per handled request, not zero and not two"

    def test_a_failed_request_is_recorded_too(self, ask):
        before = len(_records())
        ask("A4 80gsm copy paper", quantity=0)
        after = _records()
        assert len(after) == before + 1
        assert after[-1]["outcome"] == "failed"
        assert after[-1]["error"]

    def test_the_record_carries_no_raw_request_text(self, ask):
        ask(QUOTED)
        entry = _records()[-1]
        # Capture is opt-in. Without it the record carries a length and a
        # digest, never the customer's sentence.
        assert "request_text" not in entry
        assert entry["request_chars"] == len(QUOTED)
        assert entry["request_digest"]

    def test_the_record_names_the_snapshot_it_used(self, ask):
        ask(QUOTED)
        snapshot = _records()[-1]["snapshot"]
        assert snapshot["products"] == 72
        assert snapshot["path"].endswith("catalog.duckdb")

    def test_stage_timings_do_not_exceed_the_total(self, ask):
        ask(QUOTED)
        timings = _records()[-1]["timings"]
        stages = sum(
            timings[stage] for stage in ("interpret_ms", "search_ms", "price_ms")
        )
        # A breakdown that exceeds its own total means the instrumentation is
        # measuring different requests.
        assert stages <= timings["total_ms"] + 1e-6


class TestCommandLine:
    """The dispatcher wiring, exercised as a subprocess would run it."""

    def test_the_subcommand_is_registered(self):
        from paperlane.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["ask", "hello"])
        assert args.command == "ask"
        assert args.request == "hello"
        assert args.quantity is None
        assert args.json is False
        assert args.verbose is False
        assert args.no_model is False

    def test_flags_parse(self):
        from paperlane.cli import build_parser

        args = build_parser().parse_args(
            ["ask", "hello", "--quantity", "5", "--json", "--verbose", "--no-model"]
        )
        assert (args.quantity, args.json, args.verbose, args.no_model) == (
            5, True, True, True,
        )

    def test_no_model_flag_forces_the_rule_path(self, monkeypatch):
        """``--no-model`` must mean no client, not "try the model then fall back"."""
        from paperlane import model

        def _explode(*args, **kwargs):
            raise AssertionError("a model client was constructed despite --no-model")

        monkeypatch.setattr(model, "ModelClient", _explode)
        from paperlane.cli import main

        assert main(["ask", QUOTED, "--no-model"]) == 0

    def test_conversation_flags_parse(self):
        from paperlane.cli import build_parser

        args = build_parser().parse_args(
            ["ask", "hello", "--conversation", "abc", "--forget"]
        )
        assert args.conversation == "abc"
        assert args.forget is True

    def test_the_request_is_optional_so_forget_can_stand_alone(self):
        from paperlane.cli import build_parser

        args = build_parser().parse_args(["ask", "--forget", "--conversation", "abc"])
        assert args.request == ""


class TestConversation:
    """``--conversation`` across invocations, which is the point of the file store.

    Each ``run_ask`` call here is a separate call, standing in for a separate
    process: nothing is shared between them except the file.
    """

    def test_a_second_invocation_refines_the_first(self, ask):
        ask(QUOTED, conversation_id="c1")
        code, out = ask("make it 50", conversation_id="c1", as_json=True)
        assert code == 0
        body = json.loads(out)
        assert body["criteria"]["quantity"] == 50
        assert body["criteria"]["size"] == "A4"
        assert body["conversation"]["turn"] == 2

    def test_the_reply_discloses_what_it_remembered(self, ask):
        ask(QUOTED, conversation_id="c1")
        code, out = ask("make it 50", conversation_id="c1")
        assert "Remembered from your earlier message" in out
        assert "size A4" in out

    def test_a_new_size_starts_fresh(self, ask):
        ask(QUOTED, conversation_id="c1")
        code, out = ask("A5 copy paper", conversation_id="c1", as_json=True)
        body = json.loads(out)
        assert body["criteria"]["size"] == "A5"
        assert body["conversation"]["turn"] == 2
        assert body["conversation"]["carried"] == []

    def test_forget_makes_the_next_invocation_fresh(self, ask):
        ask(QUOTED, conversation_id="c1")
        code, out = ask("", conversation_id="c1", forget=True)
        assert code == 0
        assert "forgot conversation c1" in out

        code, out = ask("make it 50", conversation_id="c1", as_json=True)
        body = json.loads(out)
        assert body["conversation"]["turn"] == 1
        assert body["criteria"] == {}

    def test_forgetting_an_unknown_conversation_is_not_a_failure(self, ask):
        code, out = ask("", conversation_id="never", forget=True)
        assert code == 0
        assert "no conversation never to forget" in out

    def test_forget_without_an_id_is_a_usage_error(self, ask):
        code, out = ask("", forget=True)
        assert code == 2
        assert "--forget needs --conversation" in out

    def test_the_store_holds_no_request_text(self, ask, tmp_path):
        ask(QUOTED, conversation_id="c1")
        ask("make it 50", conversation_id="c1")
        written = (tmp_path / "conversations.jsonl").read_text()
        assert "copy paper" not in written
        assert "make it" not in written
        # It holds the requirements, which is what it is for.
        assert "PL-CP" not in written
        assert '"size_code": "A4"' in written

    def test_a_conversation_writes_one_record_per_turn(self, ask):
        before = len(_records())
        ask(QUOTED, conversation_id="c1")
        ask("make it 50", conversation_id="c1")
        written = _records()
        assert len(written) == before + 2
        assert written[-1]["turn_index"] == 2
        assert "size_code" in written[-1]["carried_fields"]

    def test_without_the_flag_nothing_is_stored(self, ask, tmp_path):
        ask(QUOTED)
        assert not (tmp_path / "conversations.jsonl").exists()
        assert "turn_index" not in _records()[-1]
