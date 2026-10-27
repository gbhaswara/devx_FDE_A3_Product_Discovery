# Design

## Context

Constraints that shape the approach, each verified in the tree rather than assumed:

- **`AXES = ("retrieval", "match", "pricing", "reply")`** (`evaluate.py:69`). It is
  imported by `conversation_eval.py` (for `FAIL`/`NA`/`PASS` and `run_case`) and
  iterated by `_summary`, `_render_text`, and `tests/test_evaluate.py`. Adding a
  member is safe for all of them because none hard-codes a length; the one place
  that asserts a shape is `set(result.axes) == set(AXES)`, which follows the
  constant.
- **`CONVERSATION_AXES = ("memory", "retrieval", "pricing", "reply")`** is a
  *separate* tuple in `conversation_eval.py`. The conversation set already scores
  memory; interpretation will not be added there in this change.
- **`Case`** carries `expect_outcome`, `expect_skus`, `expect_questions`,
  `expect_lines`, `expect_relaxed`, and per-catalog overrides through
  `effective_expectation` / `_resolved_case`. A new expectation field must travel
  through that same resolution path or the v2 cases will score against v1's
  criteria.
- **`self_check()`** corrupts one real case's answer per check and asserts the
  intended axis notices *and the others do not*. It is the only thing that proves
  the axes discriminate, and both negative controls and `tests/test_evaluate.py`
  depend on it.
- **`eval/negative-control.json`** is a copy of `cases.json` with three
  corruptions (cases 4, 6, 14) whose tests assert the exact corrupted set:
  `corrupted = {4, 6, 14}`. Adding a fourth means updating that set, which is the
  point — the fixture is the falsifiability evidence, not a sample.
- **`health()` already reads `ingest_runs.finished_at`** and returns it as
  `last_ingest.finished_at`, a DuckDB `TIMESTAMP` stringified as
  `2026-10-27 00:25:24.500248` — naive, no zone. The crawl stamps it with
  `datetime.now(timezone.utc)`, so the value *is* UTC and is read back without a
  zone. Age arithmetic must therefore attach UTC rather than assume local.
- **`resolve_db_path(db_path)`** (`catalog.py:146`) is documented as "one place
  for the fallback" — but it is not the only place: `open_readonly`,
  `snapshot_exists`, `health`, `swap_into_place` and `run_ingest` each re-spell
  `Path(db_path) if db_path is not None else DEFAULT_DB_PATH`. An environment
  variable belongs in `resolve_db_path` **and** in those five, or `PAPERLANE_DB`
  would be honoured by some readers and not others — a snapshot mix-up that
  presents as "the price is wrong".
- **`EXPECTED_CATEGORIES = 4`** (`ingest.py:38`) has no reader. Category URLs are
  discovered from the home page, so the constant cannot be honoured on a site with
  a different number of categories anyway.

## Goals / Non-Goals

**Goals**

- Make a wrong reading a reportable failure, separately from a wrong answer.
- Report catalog age on the surfaces that already exist, and never gate on it.
- Provide a set the rules were not written against, and keep it separate.
- Let an unseen site be ingested and served from a named snapshot with no edit.
- Make the gap analysis answerable in one document.

**Non-Goals**

- **A hard completeness/clarity gate that blocks publish.** The demo round
  re-ingests a live, unseen site; a gate that refuses to publish when a heuristic
  is unhappy would fail the demonstration. Incompleteness is surfaced and counted.
- **Reconciling PR1–PR8 with a real supplier's terms, tax policy or quote expiry.**
  The brief calls them the agreed specification; overriding them is not an
  improvement to this submission.
- **Auth, RBAC, rate limiting, idempotency, API versioning.** Already a stated
  README limitation for a local demo; adding a half-implemented version of any of
  them would be worse than the honest limitation.
- **Semantic or model-based interpretation scoring.** The expected criteria are
  compared as data.

## Decisions

**D1 — Interpretation is a fifth axis, first in the tuple, not a retagging of
retrieval.** The gap analysis's example is decisive: A4 misread as A3 produces a
*valid* quote with a *plausible* price. Retrieval would return the A3 set and pass
if the expectation were written loosely; pricing would pass; reply would pass. The
only reason retrieval fails today is that the expected SKU set happens to be
categorical about size — which makes a size error look like a search error and
gives no signal about *which* it was. A separate axis names the cause.
*Rejected:* folding a criteria check into `_score_retrieval`, because then a
misread and a mis-ranked case are indistinguishable in the summary, which is the
one thing the four-axis design exists to prevent.

**D2 — Expected criteria are a declared subset plus a declared absent set, never
the engine's full output.** Each case records the fields that carry its meaning
(`{"size": "LTR", "quantity": 20, "budget_per_unit": "250.00"}`) and the fields
that must *not* be present (`["weight_gsm"]` — "under 250 a pack" must not become
"80 gsm or lighter", which is a documented defect the system already guards
against). An absent set is what catches an *invented* requirement, which is the
mirror of a missed one and is invisible to a subset check.
*Rejected:* recording the full `criteria.describe()` output per case. That is
transcription of the engine's answer into its own expectation — the exact
anti-pattern `recompute_totals` is written to avoid for money, applied to
semantics.

**D3 — The held-out set is a separate file, not extra cases in `cases.json`.**
The harness selects a case file with `--cases`. A second file scored by the same
code gives the honest statement "these 28 were used to build it, these 12 were
not", and a run of the held-out file needs no new reporting path.
*Rejected:* adding cases 29+ to `cases.json`. Once they are in the regression set
they get fixed against like the others, and the held-out property dies quietly in
one commit.

**D4 — Freshness is reported, with a threshold, and never blocks.** `health()`
gains `age_seconds`, `age_human` and `stale`; `stale` is
`age_seconds > STALE_AFTER_HOURS * 3600`, with the threshold a named constant
defaulting to 24h and overridable by `PAPERLANE_STALE_AFTER_HOURS`. The reply
disclosure is deliberately *not* touched: a customer asking for paper does not
need the crawl time in the reply, and putting it there would be noise in the one
surface the brief scores for usability.
*Rejected:* a hard staleness gate (fails the demo round), and a freshness metric
inside the five (the brief asks for "logging and metrics you would watch"; a
sixth measure derived from the snapshot belongs beside `review_backlog`, which is
already the snapshot-derived one — it renders in `metrics` without changing the
count of five).

**D5 — `PAPERLANE_DB` is the environment fallback, and `--db` the flag.** One
resolution function, `resolve_db_path`, extended to read the variable, and every
re-spelled fallback in `catalog.py` routed through it so a single definition
governs. Precedence: explicit argument, then `PAPERLANE_DB`, then the committed
`data/catalog.duckdb`.
*Rejected:* a `--snapshot` directory convention, or copying the catalog aside. Both
add a concept for what an argument already expresses.

**D6 — The dead `EXPECTED_CATEGORIES` is deleted.** It is an assertion about the
site's shape that no code makes and that an unseen site would falsify. Deleting it
removes a misleading constant; wiring it up would create the gate D4 rejects.

## Risks / Trade-offs

- **Risk:** an interpretation axis that only ever reports `pass` is decoration.
  **Mitigation:** the self-check corrupts a case's derived criteria and asserts
  the axis moves while retrieval, pricing and reply do not; the negative control
  gains a fourth corruption on a real case; and the held-out set is expected to
  contain at least one case the rules misread, which is a finding rather than a
  failure to hide.
- **Trade-off:** adding a member to `AXES` changes the width of the text report
  and the key set of every `by_axis` block. Accepted: `results.md` and `TEST.md`
  are regenerated, and a reader seeing five columns understands the design better
  than four.
- **Trade-off:** `interpretation` reports `n/a` for cases with no recorded
  criteria. That is honest — those cases were not written to test interpretation —
  and the summary distinguishes `n/a` from `pass`, as it already does elsewhere.
