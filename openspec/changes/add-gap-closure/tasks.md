# Tasks

## 1. The snapshot path

- [ ] 1.1 Extend `catalog.resolve_db_path` to fall back to `PAPERLANE_DB` and then the committed path, and route the five re-spelled fallbacks in `catalog.py` (`open_readonly`, `snapshot_exists`, `health`, `swap_into_place`, and the staging path) through it, and verify a test asserts every reader resolves the same path when only the environment variable is set
- [ ] 1.2 Add `--db` to the `ingest`, `serve`, `eval`, `ask` and `metrics` subcommands and pass it through to the functions that already accept `db_path`, and verify a test asserts the flag reaches the snapshot the operation reads or writes
- [ ] 1.3 Verify an unseen-site re-ingest cannot clobber the committed catalog: ingest into a named snapshot, assert the committed file's bytes are unchanged, and assert the named snapshot is the one served
- [ ] 1.4 Delete the unused `EXPECTED_CATEGORIES` constant and verify no reference to it remains and the suite still passes

## 2. The interpretation axis

- [ ] 2.1 Add `expect_criteria` and `expect_absent_criteria` to `Case` and carry them through `effective_expectation` and `_resolved_case` so per-catalog overrides resolve like every other expectation, and verify a test asserts a v2 override changes the expected criteria for a v2 run
- [ ] 2.2 Add `interpretation` as the first member of `AXES` and implement `_score_interpretation` comparing the derived criteria against the expected subset and the expected-absent set, and verify tests assert a missing expected field fails, an invented absent field fails, and a case with no expectation is `n/a`
- [ ] 2.3 Record `expect.criteria` on the cases where a misreading is the interesting failure — the ambiguous size, the unit conversions, the budget that must not become a weight, the colour that means shade not print mode, and the cases that must ask rather than guess — and verify each recorded value is the meaning of the request rather than a copy of the engine's output
- [ ] 2.4 Extend `self_check()` with a corruption whose derived criteria are altered and assert the interpretation axis moves while retrieval, pricing and reply do not, and verify `./run.sh eval --self-check` exits 0
- [ ] 2.5 Add a fourth corruption to `eval/negative-control.json` on the interpretation axis, update the test asserting the corrupted set, and verify `./run.sh eval --cases eval/negative-control.json` still exits 1 and the new case is attributed to interpretation
- [ ] 2.6 Widen the text report for the new column and verify the rendered header, the per-axis summary line and the JSON `by_axis` block all carry five axes

## 3. The held-out set

- [ ] 3.1 Author `eval/held-out-cases.json` as requests written without consulting the rules path — unfamiliar phrasings of supported behaviours, plus one deliberately adversarial request — each with expected outcome, expected SKUs where relevant, and expected criteria, and verify it loads and runs through `./run.sh eval --cases eval/held-out-cases.json`
- [ ] 3.2 Verify at least one held-out case fails and that the failure is retained in the results with its expected and actual interpretation, because a held-out set that passes completely is evidence about the author rather than about the system
- [ ] 3.3 Record the held-out result in `docs/` and in the README evidence table, stating that the set was not used to develop the rules and reporting its score alongside the regression set's
- [ ] 3.4 Verify the held-out set is not loaded by a default `./run.sh eval` run, so the two sets stay separate and the regression run's counts do not change

## 4. The freshness signal

- [ ] 4.1 Add `STALE_AFTER_HOURS` with a documented default and a `PAPERLANE_STALE_AFTER_HOURS` override, and implement age and staleness on the snapshot state in `catalog.health`, attaching UTC to the zone-less stored timestamp, and verify a test asserts the age of a known timestamp and that the stored zone-less string is read as UTC rather than local
- [ ] 4.2 Carry the age and the stale flag through `catalog.snapshot_meta` so every response that reports its snapshot reports its age, and verify a test asserts a response's snapshot block carries both
- [ ] 4.3 Report the snapshot's age and staleness in `./run.sh metrics` beside the review backlog — the other snapshot-derived measure — without adding a sixth derived measure, and verify the rendered output and the JSON payload both carry it
- [ ] 4.4 Verify staleness never blocks: with the threshold set below the catalog's age, assert health, quote and ask all still succeed and only report the flag
