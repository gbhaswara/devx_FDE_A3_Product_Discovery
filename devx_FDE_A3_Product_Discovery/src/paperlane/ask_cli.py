"""The ``ask`` command: one question from a shell, answered in full.

This exists because the JSON API and the page both require a server, and a demo
that begins with ``curl`` is a worse demo than one that begins with the customer's
own sentence. It is a thin wrapper over the same modules the API uses — it does
not reimplement interpretation, validation, pricing, or reply rendering, so there
is no second code path that can disagree with the service.

It does write a request record, because the observability spec says every handled
request produces exactly one, and a CLI question is a handled request. Leaving it
out would make ``./run.sh metrics`` understate live traffic for exactly the
callers most likely to be debugging.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

from . import catalog, conversation, embeddings, records
from .assistant import answer
from .interpret import CriteriaInvalid, fallback_reason, interpret, validate
from .model import ModelClient, ModelConfig

#: Where `--conversation` keeps its state between invocations. Git-ignored, for
#: the same reason request records are: runtime data, not catalog data.
DEFAULT_CONVERSATION_PATH = (
    catalog.DEFAULT_DB_PATH.parent / "conversations.jsonl"
)


def _conversation_store(path=None) -> conversation.JsonlConversationStore:
    """The store `--conversation` uses.

    A file, because a CLI invocation is a new process and an in-memory store
    would make the flag appear to work while remembering nothing. The path is
    injectable so a test does not write to the real file.
    """
    return conversation.JsonlConversationStore(
        path if path is not None else DEFAULT_CONVERSATION_PATH
    )


def _record(
    *,
    started: float,
    interpret_ms: float,
    request_text: str,
    reply=None,
    interpretation=None,
    client: ModelClient | None = None,
    db_path=None,
    error: str | None = None,
    turn_index: int | None = None,
    carried_fields=(),
):
    """Write one record for a handled CLI request. Never raises.

    Mirrors the API's recorder. It is not imported from there because importing
    the HTTP layer to log a CLI request would pull FastAPI into a code path that
    does not serve HTTP.
    """
    timings = dict(getattr(reply, "timings", None) or {})
    for stage in records.TIMING_STAGES:
        timings.setdefault(stage, 0.0)
    timings["interpret_ms"] = round(interpret_ms, 3)
    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 3)

    try:
        entry = records.build_record(
            endpoint="cli/ask",
            reply=reply,
            request_text=request_text,
            timings=timings,
            snapshot=catalog.snapshot_meta(db_path),
            model_configured=client is not None,
            # The same rule the API applies, so "degraded" means one thing
            # across both entry points.
            fallback_reason=fallback_reason(interpretation, client),
            interpretation=interpretation.path if interpretation else None,
            error=error,
            turn_index=turn_index,
            carried_fields=carried_fields,
        )
    except records.RecordInvalid as exc:
        # A record the schema refuses is a bug here, but it must not turn a good
        # answer into a failure. Note it and carry on.
        print(f"paperlane: could not build request record: {exc}")
        return None
    return records.emit(records.writer_from_env(), entry)


def run_ask(
    request: str,
    *,
    quantity: int | None = None,
    use_model: bool = True,
    as_json: bool = False,
    verbose: bool = False,
    db_path=None,
    conversation_id: str | None = None,
    forget: bool = False,
    conversation_path=None,
) -> int:
    """Answer one free-text request. Returns a process code.

    Process codes mirror the API's notion of a handled request:

    ``0``   a reply was produced — any of the four outcomes, including
            ``no_match`` and ``refused``. Those are answers, not failures, so
            they must not exit non-zero; a script that treats "nothing matches"
            as an error will misreport a working assistant.
    ``2``   the request could not be handled at all: no snapshot, an empty
            request, or criteria that failed validation. Nothing was priced.
    """
    started = time.perf_counter()

    # --- forget --------------------------------------------------------
    # A separate mode, because "forget this conversation" is not a question and
    # pricing one would be nonsense. The file store is used even here so a
    # forget reaches the state a previous invocation wrote.
    if forget:
        if not conversation_id:
            print("ask: --forget needs --conversation <id>")
            return 2
        store = _conversation_store(conversation_path)
        try:
            removed = store.forget(conversation_id)
        except conversation.ConversationInvalid as exc:
            print(f"ask: {exc}")
            return 2
        print(
            f"ask: forgot conversation {conversation_id}"
            if removed else
            f"ask: no conversation {conversation_id} to forget"
        )
        return 0

    text = (request or "").strip()
    if not text:
        print("ask: the request is empty")
        return 2

    if not catalog.snapshot_exists(db_path):
        checked = catalog.resolve_db_path(db_path)
        print(
            f"ask: no catalog snapshot at {checked}\n"
            "Build one with: "
            "./run.sh ingest --base-url http://localhost:8000/paperlane/"
        )
        return 2

    client: ModelClient | None = None
    if use_model:
        config = ModelConfig.from_env()
        if config.configured:
            client = ModelClient(config)

    # --- interpret -----------------------------------------------------
    # `interpret` handles the no-client case itself (it returns the rule-based
    # criteria with path="rules"), so there is no separate branch here. One call
    # path means the CLI cannot interpret differently from the service.
    interpret_started = time.perf_counter()
    interpretation = interpret(text, client)
    interpret_ms = (time.perf_counter() - interpret_started) * 1000

    criteria = interpretation.criteria
    if quantity is not None:
        criteria = replace(criteria, quantity=quantity)

    # --- conversation --------------------------------------------------
    # The file store, because every CLI invocation is a new process: an
    # in-memory store here would make --conversation look like it works while
    # remembering nothing. The merge is the service's own pure function, so the
    # CLI cannot interpret a refinement differently from the API.
    store = None
    existing = None
    merge = None
    turn_index: int | None = None
    carried_fields: list[str] = []
    if conversation_id is not None:
        store = _conversation_store(conversation_path)
        try:
            existing = store.get(conversation_id) or conversation.Conversation(
                id=conversation_id
            )
        except conversation.ConversationInvalid as exc:
            print(f"ask: {exc}")
            return 2
        previous = conversation.continuation_basis(existing)
        merge = conversation.merge_turn(previous, criteria)
        criteria = merge.criteria
        carried_fields = sorted(merge.carried)
        turn_index = existing.turn_index

    try:
        criteria = validate(criteria)
    except CriteriaInvalid as exc:
        _record(
            started=started, interpret_ms=interpret_ms, request_text=text,
            interpretation=interpretation, client=client, db_path=db_path,
            error=f"criteria invalid: {exc.reason}",
            turn_index=turn_index, carried_fields=carried_fields,
        )
        print(f"ask: could not use that request — {exc.reason}")
        if as_json:
            print(json.dumps({"outcome": "error", "reason": exc.reason}, indent=2))
        else:
            print(
                "\nNothing was priced. Rephrase with a product kind, a size, or a "
                "quantity, for example:\n"
                '  ./run.sh ask "A4 80gsm copy paper, 20 reams"'
            )
        return 2

    # --- price ---------------------------------------------------------
    rows = catalog.load_products(db_path)
    facts = catalog.load_price_facts(db_path)

    try:
        reply = answer(
            criteria,
            rows,
            facts,
            interpretation=interpretation.path,
            scorer=embeddings.scorer_for(text, rows, db_path=db_path),
        )
    except catalog.SnapshotMissing as exc:
        _record(
            started=started, interpret_ms=interpret_ms, request_text=text,
            interpretation=interpretation, client=client, db_path=db_path,
            error=f"no snapshot: {exc}",
            turn_index=turn_index, carried_fields=carried_fields,
        )
        print(f"ask: no catalog snapshot — {exc}")
        return 2

    # A clarified turn is still a turn: the clarification is often the only
    # constraint the customer has given, and the next turn needs it.
    if store is not None and conversation_id is not None:
        assert existing is not None and merge is not None
        store.put(conversation.record_turn(existing, merge, outcome=reply.outcome))

    _record(
        started=started, interpret_ms=interpret_ms, request_text=text,
        reply=reply, interpretation=interpretation, client=client,
        db_path=db_path,
        turn_index=turn_index, carried_fields=carried_fields,
    )

    # --- report --------------------------------------------------------
    if as_json:
        # `AssistantReply.as_dict()` is the same serialiser the HTTP API returns,
        # so the CLI cannot drift from the service: one shape, one definition.
        # Hand-rolling a second shape here is how a CLI and an API start
        # disagreeing about what a quote looks like.
        body = reply.as_dict()
        if conversation_id is not None:
            body["conversation"] = {
                "id": conversation_id,
                "turn": turn_index,
                "carried": carried_fields,
                "carried_described": criteria.describe_carried(),
            }
        print(json.dumps(body, indent=2, default=str))
        return 0

    print(reply.text)
    if conversation_id is not None:
        # Stated outside the reply text, because it is about the command rather
        # than about the catalog: without it a user cannot tell which id the next
        # invocation must repeat.
        print(f"\n(conversation {conversation_id}, turn {turn_index})")

    if verbose:
        print("\n--- interpretation ---")
        print(f"path: {interpretation.path}")
        if interpretation.detail:
            print(f"detail: {interpretation.detail}")
        print(f"criteria: {json.dumps(criteria.describe(), default=str, sort_keys=True)}")
        print(f"considered: {len(rows)} products")

    return 0
