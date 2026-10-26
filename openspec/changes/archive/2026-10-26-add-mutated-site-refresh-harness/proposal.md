# Proposal

## Why

The refresh path is the only major capability in this submission that is **asserted but never demonstrated end to end**. `diff_snapshots()` is unit-tested against synthetic snapshots, and re-ingesting the *unchanged* site correctly reports `no_change: true` — but no refresh has ever been run against a site that actually changed. That leaves three things unproven at once:

- The diff cannot be shown to *detect* anything. A report that returns six empty lists is equally consistent with a correct implementation and with one that reads nothing.
- Four evaluation cases are recorded `not_applicable` with reasons that all reduce to "the v1 catalog has no such data": a discontinued product, a page carrying an injected instruction, and 28 lb / 32 lb weights. Those behaviours are implemented and unit-tested, but no live sample exists to run them against.
- The review floor — the mechanism that makes a silently shrinking catalog detectable — has never fired on a real page, because all 36 pages parse cleanly.

The v1 site is a fixture that happens to contain no adversity. The honest way to prove the refresh path is to construct the adversity deliberately and check the report names every injected change.

## What Changes

- A **mutated site generator** that copies the committed catalog site and injects a known, declared set of changes into it: added items, a withdrawn item, a price change, a tier change, an availability change, a page in an unknown markup shape, both missing pound→grammage weights, an exact budget boundary, an exact delivery threshold, and an embedded instruction.
- The generator writes a **manifest** of exactly what it injected, so verification compares the diff report against a declaration rather than against someone's memory of what they edited.
- An **expectation file** that states, per injected change, which diff list it must appear in and why. Verification is a comparison of the report against this file, not a reading of the report.
- The evaluation set's four `not_applicable` cases gain a **second catalog** in which they are runnable, rather than staying permanently unexercised.
- A `run.sh` entry point for the whole demonstration, so it is reproducible by a reviewer in one command rather than a documented sequence of manual steps.

**Not** changing: the diff algorithm, the extraction ladder, or the ingest path. This change builds a fixture and a verification around code that already exists. If the demonstration finds a defect, fixing it is part of this change — but the intent is to *test* the existing implementation, not to redesign it.

## Capabilities

### New Capabilities

- `refresh-verification`: the system can be shown to detect catalog change, by generating a declared mutation of a known site and asserting that every injected change is reported and attributed to the right change kind. Covers the fixture's construction, its manifest, and the correspondence between the two.

### Modified Capabilities

- `catalog-refresh`: the existing requirement *"The result of a refresh is reported as a diff"* gains scenarios for change kinds that the v1 catalog cannot produce — tier change and availability change have no live sample today. The requirement that a page which cannot be parsed becomes visible gains a scenario exercised against a real unparseable page rather than a synthetic row.
- `evaluation-harness`: the requirement covering not-applicable cases is extended so that a case may be marked not-applicable *for a named catalog* rather than permanently, and becomes runnable when a catalog exists in which it applies.

## Impact

- **New code:** a mutated-site generator, a manifest format, and a verification module. The generator is test tooling, not runtime — it is not imported by the serving path.
- **New data:** a generated site tree (not committed as HTML; generated on demand into a temp or git-ignored directory, since 36 copied pages plus mutations is derivable output, not source) and a committed expectations file.
- **Affected existing code:** `evaluate.py` gains per-catalog applicability; `catalog.py` diff is exercised but not changed unless a defect is found.
- **`run.sh`:** one new command.
- **Tests:** the diff's six change kinds get an end-to-end test that does not rely on hand-built snapshots; the four previously-unexercised behaviours get live coverage.
- **Dependencies:** none new. The generator uses the standard library and the existing crawler's target layout.
- **Risk:** the generated site must be faithful enough that a successful diff proves something about the real site. If the generator produces markup the extractor cannot read *by accident*, the demonstration proves only that the extractor fails. The manifest and the review floor are what keep those two outcomes distinguishable — see `design.md`.
