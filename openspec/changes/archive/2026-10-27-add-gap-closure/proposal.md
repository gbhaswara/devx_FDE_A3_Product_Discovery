# Proposal

## Why

A gap analysis was written against the finished system, reviewing it as a
**production** sales assistant rather than as the scoped local demonstration the
brief actually asks for. Read that way most of what it finds is real, and most of
it is out of scope: tax reconciliation, authentication, RBAC, rate limiting and
quote expiry are all gaps *of a hypothetical deployment*, and the brief states
that PR1–PR8 are "the customer's agreed specification" — reconciling them against
a real supplier's terms would contradict the brief rather than improve the
submission.

Three of the findings are different: they are within scope, they are about the
brief's own scored areas, and they can be closed with measurement rather than
features.

1. **Interpretation is not scored.** The harness has four axes — retrieval, match,
   pricing, reply — and none of them asks *"did we read the request correctly?"*
   The gap analysis names this precisely: a validated criterion can still be
   semantically wrong, so an A4 request misread as A3 passes validation and
   returns a perfectly valid quote for the wrong request. The brief's own scored
   area is **"Agent design: the model decides intent, code decides facts and
   prices"** — and intent correctness is currently the one thing unmeasured.

2. **Freshness is not surfaced.** `health()` reports counts and `built_at`;
   `metrics` reports five measures. None of them reports the catalog's *age*. A
   twelve-day-old catalog and one crawled a minute ago render identically, so the
   exact condition the gap analysis calls critical — stale data behind a correct
   engine — is invisible to every surface the system has.

3. **The recorded set is not held out.** All 28 cases were written while the rules
   path was being built, and were used to fix it. They are a good regression set
   and a poor estimate of behaviour on unseen wording. The brief says the demo
   round runs the system on *"inputs you have not seen"*.

There is also one operational gap that the gap analysis reaches from a different
direction and that matters specifically on demo day: **re-ingest is parameterized
by address but not by snapshot path**. `--base-url` and `--rate` exist, but the
snapshot is always `data/catalog.duckdb`, so a live re-ingest of an unseen site
overwrites the committed catalog and `serve` cannot be pointed at a named one.
The brief requires the solution to keep running against a new site "without
changing code first"; overwriting the only snapshot with an unreviewed build is
how that goes wrong in front of an audience.

## What Changes

- **A fifth evaluation axis, `interpretation`.** Each case records what the
  request *means* — the criteria that must be understood, and the ones that must
  not be invented — and the axis scores the criteria the engine actually derived
  against that. It is scored before retrieval, because retrieving the right set
  for the wrong request is the failure mode the four existing axes cannot see.
- **A held-out case set**, `eval/held-out-cases.json`, authored as requests that
  were *not* used to write the rules, scored by the same harness and reporting its
  own summary. It is deliberately not merged into `cases.json`: a set you tune
  against stops being held out, and the separation is the whole value.
- **A freshness signal**: catalog age and a `stale` flag derived from the recorded
  ingest time, surfaced in `GET /api/health`, in the snapshot metadata carried by
  every API response, and in `./run.sh metrics`. It is **reported, never gating**.
- **A snapshot path argument.** `--db` on `ingest`, `serve`, `eval`, `ask` and
  `metrics`, with `PAPERLANE_DB` as the single fallback in `resolve_db_path`, so an
  unseen site can be ingested into a named snapshot and served from it without
  touching the committed catalog.
- **A gaps response document**, `GAPS_RESPONSE.md`, mapping every finding in
  `GAPS_ANALYSIS.md` to *closed* / *out of scope by the brief* / *not fixable
  in kind*, with the reason for each.
- **Deletion:** `EXPECTED_CATEGORIES = 4` in `ingest.py` is dead — defined and
  never read — and it encodes an assumption that an unseen site has four
  categories. It is removed rather than wired up.

**BREAKING:** none. The four existing axes keep their names and their meanings;
`interpretation` is added first in the tuple, and cases that record no expected
criteria report `n/a` there rather than failing. With no `--db` and no
`PAPERLANE_DB`, every path is byte-identical to today's.

## Capabilities

### Modified Capabilities

- `evaluation-harness`: the requirement *"Cases are scored on separate axes"*
  gains the interpretation axis as a first-class, independently reported axis, and
  the requirement *"Failing cases are retained and reported"* gains the
  consequence that a wrong reading is now visible as its own failure rather than
  being absorbed by retrieval.
- `evaluation-harness` (new): a held-out set requirement — a separate recorded
  set that was not used to develop the interpretation rules, scored by the same
  harness, with its own results.
- `catalog-refresh`: the requirement *"Re-ingest requires no code changes"* gains
  the snapshot-location scenario, so pointing a re-ingest at a named snapshot is a
  documented capability rather than an internal detail.
- `observability`: a new requirement that the catalog's age is reported, with a
  stated staleness threshold, on the surfaces an operator already reads.

## Impact

- **New code:** `_score_interpretation` in `evaluate.py`; an `age`/`stale`
  derivation in `catalog.py`; `eval/held-out-cases.json`; `GAPS_RESPONSE.md`.
- **Modified code:** `evaluate.py` (`AXES`, `Case.expect_criteria`,
  `effective_expectation`, `run_case`, `_render_text`, `_summary`, `self_check`);
  `catalog.py` (`health`, `snapshot_meta`, `STALE_AFTER_HOURS`); `metrics.py`
  (render and payload); `cli.py` (`--db` on five subcommands); `ingest.py`
  (delete the dead constant).
- **Data:** case files gain an `expect.criteria` block. `negative-control.json`
  gains a fourth corruption, on the interpretation axis, so the new axis is
  falsifiable by the same fixture that falsifies the other three.
- **Dependencies:** none added.
- **Tests:** `tests/test_evaluate.py` gains interpretation-axis tests and the
  negative-control expectations move from three corrupted cases to four. The
  existing assertions that every axis is reported, that absent-data cases are
  `n/a` on every axis, and that the four original axes still discriminate are
  unchanged in intent and must still pass.
- **Risk:** an axis whose expected values are transcribed from the engine's own
  output measures nothing. The mitigation is that cases record a *subset* of the
  criteria — the fields that discriminate meaning — plus an explicit list of
  fields that must be absent, and the self-check corrupts a case's criteria to
  prove the axis moves while the others do not.
