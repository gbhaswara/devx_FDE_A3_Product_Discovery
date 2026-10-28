"""One structured record per handled request, appended as JSONL.

The record exists so that the five metrics in ``metrics.py`` can be *derived*
rather than *maintained*. Nothing increments a counter while a request is being
handled; a request writes one line, and the numbers are recomputed from those
lines on read. That choice has a cost (an O(n) scan per read, microseconds at
this scale) and buys the property that matters: the record is the single source
of truth, so a metric cannot drift away from the events it claims to summarise.

**What is deliberately absent.** The record does not carry the request text. It
carries ``request_chars`` (a length) and ``request_digest`` (a short hash)
instead, because the ``observability`` spec forbids retaining arbitrary
conversation text — and this conflicts with `docs/pre/ANALYZE_01.md` §9a, which specifies
logging ``raw_message``. The spec is the higher authority, so the analysis is
recorded as a defect rather than quietly followed. Text capture is an explicit
opt-in, bounded by a maximum length.

The digest is a **grouping aid, not anonymisation**: a short hash of a short
string is brute-forceable, and calling it anything else would be a lie that
someone eventually relies on.

**What is deliberately present.** ``stated_total`` is parsed from the rendered
reply text at record time, and ``lines`` holds the SKUs and quantities quoted.
Together they let the disagreement metric re-derive the total through
``evaluate.recompute_totals`` — a different code path from the one that produced
the reply — and compare. Storing the engine's own figure and comparing it to
itself would measure nothing.

**Concurrency.** The append happens under one module-level ``threading.Lock``.
One lock around a single line append is not a throughput concern at this scale,
and it is far simpler than a queue. The lock protects the write, never the
request path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

#: The closed vocabulary of outcomes a record may carry. ``failed`` is not one of
#: the assistant's four outcomes — it is what a record says when the request
#: never produced a reply at all. Keeping it in the same vocabulary is what makes
#: failures countable instead of invisible.
OUTCOMES = ("quoted", "clarified", "no_match", "refused", "failed")

#: Interpretation paths, matching ``interpret.Interpretation.path``.
INTERPRETATIONS = ("model", "rules", "mixed", "structured")

#: Per-stage timings. ``total_ms`` is the wall clock for the whole request and is
#: asserted to be at least the sum of the stages, never less.
TIMING_STAGES = ("interpret_ms", "search_ms", "price_ms")

#: How much request text an operator may opt into storing. Bounded on purpose:
#: "capture the text for debugging" must not become "retain every conversation".
DEFAULT_TEXT_MAX = 200

#: How many records the p95 window covers by default.
DEFAULT_WINDOW = 1000

#: Default location. Git-ignored: it is operational data, not catalog data, and
#: committing it would look like a second source of truth about the catalog.
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "requests.jsonl"

#: Where the evaluation harness writes its records.
#:
#: Deliberately **not** the live log. The harness and live traffic are different
#: populations: the eval set is a fixed, curated sample chosen to exercise edge
#: cases, so mixing it into the live log would drag the fallback and zero-result
#: rates toward whatever the case list happens to emphasise. A rate computed over
#: a mixture answers neither question. Keeping them apart also means an operator
#: can re-run the harness as often as they like without disturbing their
#: production numbers.
EVAL_PATH = Path(__file__).resolve().parents[2] / "data" / "eval-records.jsonl"


class RecordInvalid(ValueError):
    """A record was constructed with a value outside its declared vocabulary."""


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def digest_of(text: str) -> str:
    """A short, stable hash of the request text.

    Sixteen hex characters. Long enough to group repeated identical requests
    without collision at any plausible volume, short enough to read in a log.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


#: The ``Total`` line ``assistant._render_breakdown`` emits:
#:
#:     Total         4,664.00
#:
#: Anchored at both ends and requiring the grouped-thousands shape, so a stray
#: "total" in prose cannot be mistaken for the figure. Parsed from the rendered
#: text rather than read off the quote object — that is the whole point, because
#: a rendering bug is exactly what this metric is meant to catch.
_STATED_TOTAL = re.compile(
    r"^[ \t]*Total[ \t]+(\d{1,3}(?:,\d{3})*\.\d{2})[ \t]*$",
    re.MULTILINE,
)


def parse_stated_total(reply_text: str) -> str | None:
    """The total the reply actually printed, or ``None`` if it printed none.

    Returns the formatted string exactly as rendered, so the comparison against
    a recomputed total is a string compare on identical formatting. A reply with
    two ``Total`` lines is ambiguous and returns ``None`` rather than guessing
    which one the customer was meant to read.
    """
    if not reply_text:
        return None
    found = _STATED_TOTAL.findall(reply_text)
    if len(found) != 1:
        return None
    return found[0]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class RequestRecord:
    """One handled request, as it is written to the log.

    Frozen because a record that can be edited after the fact is not a record.
    """

    endpoint: str
    outcome: str
    interpretation: str = "structured"
    model_configured: bool = False
    #: Why the rule path served the request, when it did. Required by the spec
    #: when a model was configured and rules ran anyway — that is the silent
    #: degradation the fallback metric exists to surface.
    fallback_reason: str | None = None
    candidates_considered: int = 0
    items_returned: int = 0
    #: The engine's figure, and the figure the reply actually printed. Both are
    #: kept: the second is parsed from rendered text, so the two disagreeing is
    #: itself a rendering finding.
    quoted_total: str | None = None
    stated_total: str | None = None
    #: ``[{"sku": ..., "quantity": ...}]`` for the lines actually quoted, so the
    #: total can be re-derived independently when the metric is read.
    lines: tuple[dict[str, Any], ...] = ()
    timings: dict[str, float] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    request_chars: int = 0
    request_digest: str = ""
    #: Populated only when an operator has opted into text capture.
    request_text: str | None = None
    #: Set when the request produced no reply at all.
    error: str | None = None
    #: Groups the records one evaluation run wrote. Absent for live traffic,
    #: which has no run to belong to. Without it a log holding several runs
    #: would have its metrics computed over their union, so re-running the
    #: harness would silently change what the next read reports.
    run_id: str | None = None
    #: Position in a conversation, 1-based. ``None`` for a single-turn request,
    #: so single-turn and multi-turn traffic stay separable in the metrics
    #: rather than blended into one population with two behaviours.
    turn_index: int | None = None
    #: Field names carried from earlier turns. Empty for a single-turn request,
    #: and empty for a multi-turn turn that carried nothing — the two are
    #: distinguished by ``turn_index``.
    carried_fields: tuple[str, ...] = ()
    timestamp: str = ""

    def __post_init__(self) -> None:
        # Redaction happens here, in the record itself, rather than at each call
        # site. A field that could carry a credential is scrubbed whether the
        # caller remembered to scrub it or not, so there is one place to audit and
        # no way for a new caller to opt out by forgetting.
        if self.fallback_reason:
            object.__setattr__(
                self, "fallback_reason", redact_secrets(self.fallback_reason)
            )
        if self.error:
            object.__setattr__(self, "error", redact_secrets(self.error))
        if self.request_text:
            object.__setattr__(
                self, "request_text", redact_secrets(self.request_text)
            )
        if self.outcome not in OUTCOMES:
            raise RecordInvalid(
                f"outcome {self.outcome!r} is not one of {list(OUTCOMES)}"
            )
        if self.interpretation not in INTERPRETATIONS:
            raise RecordInvalid(
                f"interpretation {self.interpretation!r} is not one of "
                f"{list(INTERPRETATIONS)}"
            )
        if not self.endpoint:
            raise RecordInvalid("a record must name the endpoint that produced it")
        if self.request_chars < 0:
            raise RecordInvalid("request_chars cannot be negative")
        if self.turn_index is not None and self.turn_index < 1:
            raise RecordInvalid("turn_index is 1-based, so it cannot be below 1")
        for stage in TIMING_STAGES:
            value = self.timings.get(stage)
            if value is not None and value < 0:
                raise RecordInvalid(f"{stage} cannot be negative")
        if not self.timestamp:
            object.__setattr__(self, "timestamp", _now())
        # A model-configured request served by rules must say why. The spec asks
        # for it, and an unexplained fallback is the exact failure this record
        # exists to make visible — so it is rejected at construction rather than
        # discovered missing during an incident.
        if (
            self.outcome != "failed"
            and self.model_configured
            and self.interpretation == "rules"
            and not self.fallback_reason
        ):
            raise RecordInvalid(
                "a model-configured request served by the rule path must record "
                "why it fell back"
            )

    @property
    def total_ms(self) -> float:
        return float(self.timings.get("total_ms", 0.0))

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": self.timestamp,
            "endpoint": self.endpoint,
            "outcome": self.outcome,
            "interpretation": self.interpretation,
            "model_configured": self.model_configured,
            "candidates_considered": self.candidates_considered,
            "items_returned": self.items_returned,
            "timings": {k: round(v, 3) for k, v in self.timings.items()},
            "snapshot": self.snapshot,
            "request_chars": self.request_chars,
            "request_digest": self.request_digest,
        }
        # Absent rather than null when there is nothing to say, so a reader can
        # tell "no total was quoted" from "a total was quoted and lost".
        if self.fallback_reason:
            payload["fallback_reason"] = self.fallback_reason
        if self.quoted_total is not None:
            payload["quoted_total"] = self.quoted_total
        if self.stated_total is not None:
            payload["stated_total"] = self.stated_total
        if self.lines:
            payload["lines"] = list(self.lines)
        if self.error:
            payload["error"] = self.error
        if self.request_text is not None:
            payload["request_text"] = self.request_text
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.turn_index is not None:
            payload["turn_index"] = self.turn_index
        # Present whenever this was a multi-turn request, even when nothing was
        # carried: an empty list says "turn 3 carried nothing", which is a
        # different fact from "this was turn 1".
        if self.turn_index is not None:
            payload["carried_fields"] = list(self.carried_fields)
        return payload


# ---------------------------------------------------------------------------
# Building a record from a reply
# ---------------------------------------------------------------------------


def items_returned(reply) -> int:
    """How many products the reply actually put in front of the customer."""
    if reply.outcome == "quoted":
        return len(reply.candidates)
    if reply.outcome == "no_match":
        return len(reply.alternatives)
    if reply.outcome == "refused":
        return len(reply.refused)
    return 0


def lines_of(reply) -> tuple[dict[str, Any], ...]:
    """The quoted lines, as ``{"sku", "quantity"}`` pairs."""
    if reply.quote is None:
        return ()
    return tuple(
        {"sku": line.sku, "quantity": line.quantity} for line in reply.quote.lines
    )


def text_for_log(text: str, *, max_chars: int | None = None) -> str | None:
    """The request text, truncated, when an operator has opted in.

    Returns ``None`` when there is no text. The bound comes from
    :func:`text_max` unless one is passed explicitly, so the configured limit is
    the one that applies — a default argument would silently pin every caller to
    the constant and make the setting do nothing.
    """
    if not text:
        return None
    limit = text_max() if max_chars is None else max_chars
    return text[:limit]


def build_record(
    *,
    endpoint: str,
    reply=None,
    request_text: str = "",
    timings: dict[str, float] | None = None,
    snapshot: dict[str, Any] | None = None,
    model_configured: bool = False,
    fallback_reason: str | None = None,
    interpretation: str | None = None,
    error: str | None = None,
    turn_index: int | None = None,
    carried_fields: Sequence[str] = (),
) -> RequestRecord:
    """Assemble a record from whatever the handler managed to produce.

    Written to tolerate a missing reply, because a failed request still needs a
    record: "one record per handled request" includes the ones that failed, and a
    failure that leaves no trace is the hardest kind to count.
    """
    capture = capture_enabled()
    body = text_for_log(request_text) if capture else None

    if reply is None:
        return RequestRecord(
            endpoint=endpoint,
            outcome="failed",
            interpretation=interpretation or "structured",
            model_configured=model_configured,
            fallback_reason=fallback_reason,
            timings=dict(timings or {}),
            snapshot=dict(snapshot or {}),
            request_chars=len(request_text or ""),
            request_digest=digest_of(request_text or ""),
            request_text=body,
            error=error,
            turn_index=turn_index,
            carried_fields=tuple(carried_fields),
        )

    quoted_total = reply.quote.total.format() if reply.quote is not None else None
    return RequestRecord(
        endpoint=endpoint,
        outcome=reply.outcome,
        interpretation=interpretation or reply.interpretation,
        model_configured=model_configured,
        fallback_reason=fallback_reason,
        candidates_considered=int(getattr(reply, "considered", 0) or 0),
        items_returned=items_returned(reply),
        quoted_total=quoted_total,
        stated_total=parse_stated_total(reply.text),
        lines=lines_of(reply),
        timings=dict(timings or {}),
        snapshot=dict(snapshot or {}),
        request_chars=len(request_text or ""),
        request_digest=digest_of(request_text or ""),
        request_text=body,
        error=error,
        turn_index=turn_index,
        carried_fields=tuple(carried_fields),
    )


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def capture_enabled() -> bool:
    return _truthy(os.environ.get("PAPERLANE_RECORD_TEXT"))


def text_max() -> int:
    try:
        return max(1, int(os.environ.get("PAPERLANE_RECORD_TEXT_MAX", DEFAULT_TEXT_MAX)))
    except ValueError:
        return DEFAULT_TEXT_MAX


class RecordWriter:
    """Appends records as JSONL. A failed write never fails the request.

    ``failures`` is the one counter in this module, and it counts the writer's own
    failures rather than anything about requests. That distinction matters: a
    metric derived from records must not also be a counter, but a recorder that
    silently drops records needs to be visible somewhere, and the record it would
    have written is not available to say so.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.failures = 0
        self.last_error: str | None = None
        self._created_dirs = False

    def write(self, record: RequestRecord) -> bool:
        """Append one line. Returns whether it landed."""
        line = json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True)
        try:
            with _LOCK:
                if not self._created_dirs:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self._created_dirs = True
                # One write call per line, under the lock: two writers cannot
                # interleave halves of a record into one malformed line.
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception as exc:  # noqa: BLE001 - losing a record beats failing
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"paperlane: could not write request record: {self.last_error}",
                file=sys.stderr,
            )
            return False
        return True

    def read(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Every parseable record, oldest first.

        A malformed line is skipped rather than raising: one truncated line from
        a crashed process must not make the whole log unreadable, and metrics
        that refuse to load are metrics nobody watches.
        """
        records = _read_path(self.path)
        if limit is not None and limit >= 0:
            records = records[-limit:] if limit else []
        return records


def _read_path(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict):
                out.append(payload)
    return out


#: One writer per configured path, so the failure counter survives across
#: requests without leaking across paths.
_WRITERS: dict[str, "RecordWriter"] = {}


def record_path() -> Path:
    """Where records go. ``PAPERLANE_RECORD_PATH=off`` disables recording.

    Returns the sentinel path unchanged when disabled; use :func:`writer_from_env`
    to get ``None`` instead.
    """
    raw = os.environ.get("PAPERLANE_RECORD_PATH")
    if raw is None:
        return DEFAULT_PATH
    return Path(raw)


def recording_enabled() -> bool:
    raw = os.environ.get("PAPERLANE_RECORD_PATH")
    if raw is None:
        return True
    return raw.strip().lower() not in ("", "off", "0", "false", "none")


def writer_from_env() -> "RecordWriter | None":
    """The writer for the currently configured path, or ``None`` if disabled.

    Cached **per path** rather than once per process. Two reasons, and they pull
    in the same direction:

    * the failure counter is only meaningful if it survives across requests, so a
      fresh writer per request would reset it and a writer that dropped every
      record would report ``failures == 0``;
    * the test suite points ``PAPERLANE_RECORD_PATH`` at a per-test temporary
      file, so a single global writer would send every later test's records to
      whichever path happened to be set first — the metrics tests would then be
      measuring a mixture of their own fixtures and someone else's leftovers.
    """
    if not recording_enabled():
        return None
    key = str(record_path())
    writer = _WRITERS.get(key)
    if writer is None:
        writer = RecordWriter(key)
        _WRITERS[key] = writer
    return writer


def reset_writers() -> None:
    """Drop the cached writers. For tests that change the path mid-run."""
    _WRITERS.clear()


def iter_records(writer: "RecordWriter | None" = None) -> Iterator[dict[str, Any]]:
    """Records from ``writer``, or from the configured path when not supplied."""
    if writer is not None:
        yield from writer.read()
        return
    yield from _read_path(record_path())


def eval_path() -> Path:
    """Where the harness writes, honouring ``PAPERLANE_EVAL_RECORD_PATH``."""
    raw = os.environ.get("PAPERLANE_EVAL_RECORD_PATH")
    return Path(raw) if raw else EVAL_PATH


def eval_records(run_id: str | None = None) -> list[dict[str, Any]]:
    """Records written by the evaluation harness, oldest first.

    A separate reader because they are a separate population — see
    :data:`EVAL_PATH`. ``PAPERLANE_EVAL_RECORD_PATH`` overrides the location so a
    test can point at a temporary file.

    With no ``run_id``, only the **most recent run's** records are returned. The
    file accumulates across runs — including the negative-control run, whose
    whole purpose is to fail — so reading the whole file would mean the reported
    numbers silently described several runs at once. Passing a ``run_id`` reads
    that run specifically.
    """
    everything = _read_path(eval_path())
    if run_id is not None:        return [r for r in everything if r.get("run_id") == run_id]
    latest = latest_eval_run(everything)
    if latest is None:
        return []
    return [r for r in everything if r.get("run_id") == latest]


def latest_eval_run(records: list[dict[str, Any]]) -> str | None:
    """The ``run_id`` of the last run in ``records``, or ``None``.

    The last one, not the largest by string order: the ids are timestamps, but
    relying on lexicographic order would break the moment the format changed.
    """
    for record in reversed(records):
        if record.get("run_id"):
            return record["run_id"]
    return None


def eval_writer() -> "RecordWriter | None":
    """The writer the harness uses. ``None`` when recording is disabled."""
    if not recording_enabled():
        return None
    key = str(eval_path())
    writer = _WRITERS.get(key)
    if writer is None:
        writer = RecordWriter(key)
        _WRITERS[key] = writer
    return writer


def all_records(writer: "RecordWriter | None" = None) -> list[dict[str, Any]]:
    return list(iter_records(writer))


def emit(
    writer: "RecordWriter | None", record: RequestRecord
) -> RequestRecord:
    """Write ``record`` if there is a writer. Never raises."""
    if writer is not None:
        writer.write(record)
    return record


def window_size() -> int:
    try:
        return max(1, int(os.environ.get("PAPERLANE_RECORD_WINDOW", DEFAULT_WINDOW)))
    except ValueError:
        return DEFAULT_WINDOW


def summarise(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Counts by outcome and interpretation, for the metrics endpoint's basis."""
    by_outcome: dict[str, int] = {}
    by_interpretation: dict[str, int] = {}
    for record in records:
        outcome = str(record.get("outcome", "?"))
        path = str(record.get("interpretation", "?"))
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        by_interpretation[path] = by_interpretation.get(path, 0) + 1
    return {"by_outcome": by_outcome, "by_interpretation": by_interpretation}


def contains_credential_shape(text: str, patterns: Iterable[Any]) -> str | None:
    """The first credential-shaped substring in ``text``, or ``None``.

    Kept here so the hygiene test and any future runtime check share one
    definition of "credential-shaped" rather than drifting apart.
    """
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

#: The shapes a credential takes in free text. Duplicated from the hygiene test's
#: list on purpose rather than imported from it: production code must not depend
#: on the test suite. The test asserts the two lists agree, so the duplication is
#: checked rather than hoped for.
CREDENTIAL_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{20,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[=:]\s*"
        r"[\"']([A-Za-z0-9_\-\.]{24,})[\"']"
    ),
)

REDACTED = "[redacted]"

#: Environment variables whose *values* are credentials. A configured key is
#: redacted literally, not just by shape: a short or unusually-formatted key would
#: slip past a pattern, and it is the value we actually know.
_SECRET_ENV = (
    "PAPERLANE_LLM_API_KEY",
    "PAPERLANE_EMBED_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def redact_secrets(text: str | None) -> str | None:
    """Remove anything credential-shaped from text bound for a record.

    This exists because the realistic leak is not a field someone added for a
    key — it is an **error message**. A provider client that fails often
    interpolates the request it was building, and the request carries the
    ``Authorization`` header. That message becomes ``fallback_reason``, which
    lands in the record, and the credential is in the log.

    Two passes, because they catch different things: the configured values are
    replaced literally (they are known, so they are certain to be caught), then
    the patterns catch a key that arrived by some other route.
    """
    if not text:
        return text
    for name in _SECRET_ENV:
        value = os.environ.get(name)
        if value and len(value) >= 8:
            text = text.replace(value, REDACTED)
    for pattern in CREDENTIAL_SHAPES:
        text = pattern.sub(REDACTED, text)
    return text
