# FIXED.md — the remaining fixes

Working list of what is **not** fixed, opened after the `BUG.md` audit on
2026-10-27. **Nothing is open.** Every item in `BUG.md` is fixed, mitigated by
design, or an accepted risk.

This file is the to-do list, not the record. The record stays in `BUG.md` (one
entry per defect, with its guard), and the history stays in `CHANGELOG.md`. Both
live at the repository root, three levels above this file. An
item leaves this file only when its stated verification has been run and passed —
not when the code is written.

**Status: 0 open · 0 in progress · 2 closed since the audit (F-1, F-2 — both 2026-10-27).** The later brief-audit and refresh fixes (A20–A32) were not tracked here: they arrived after this list was opened and are recorded directly in `BUG.md` Parts 2c and 2d, each with the failing run and the verification that closed it.

---

## What closed

| Item | Defect | Change | Verification |
|---|---|---|---|
| **F-1** | A16 — `unit_word` held the volume-pricing note on four SKUs | `extract._unit_word` reads the slash tail before the `.muted` fallback; snapshot re-ingested over HTTP at 1 req/s | Failing test first (`assert 'No volume pr...or this item.' == 'ream'`); `TestPackSize` 11/11; 4 rows differ, all `unit_word`, plus provenance; 72 products / 105 tiers / 2 out of stock / 0 review items; offline suite 1192 passed, 7 skipped; eval 24/24; `--catalog v2` 21/21; `verify-refresh --keep` 12/12 |
| **F-2** | The eval CLI ignored a second catalog: `./run.sh eval` had no `--catalog` flag, so a mutated-site run could silently score the committed catalog | `--catalog {v1,v2}`, default `v1`; a mismatched combination is refused with exit 2 | Refused a conversation set with `--catalog v2`; refused `--catalog v2` without `--db`; `eval --catalog v2` 21/21; default 24/24 |

Both closed as shipped-code correctness fixes. Neither adds a feature, changes a
pricing rule, or touches the assistant's behaviour.

**What is not claimed.** F-1 is a display-only field, not one of the fields the
brief names (size, weight, colour, finish, sides, colour mode, pack size, prices,
stock), so it is a correctness fix for a published record rather than a must-have
gap. F-2 served submission item 3 — reproducible evidence — and added no product
behaviour.

**Found while closing F-1.** A19, the stored-timestamp defect: every `TIMESTAMP`
column held local wall time while every reader assumed UTC, so catalog age was
understated by the host offset and went negative right after an ingest. The
re-ingest exposed it through two pre-existing freshness tests. It was fixed in
the same session, separately, with three tests seen to fail by 25200 s first. It
was never on this list because it was not known until the snapshot was rebuilt;
its record is in `BUG.md` A19 and `CHANGELOG.md`.

---

## Constraints that applied

- The catalog site is served over HTTP. Never `file://`, never a direct file read.
- Crawl at **1 req/s**. The brief permits up to 2; `robots.txt` states
  `Crawl-delay: 1`, and the lower rate is the one the rest of the project uses.
- No API key is committed; credentials stay in environment variables. Neither fix
  reads one.
- Pricing stays deterministic and untouched. No price, total or tier moved:
  `price_tiers` is identical apart from `crawled_at`.
- The data is used only for this assignment.
- The demo path stays runnable: a fresh site re-ingests without code changes, and
  neither fix adds a required step to the README's quickstart.
- Failures stay in the results. Neither fix turned a documented failure into a
  pass by changing the expectation.

---

## Order

F-2 went first because it was small, touched no data, and made the existing
evidence reproducible before the snapshot changed. F-1 followed because it
rewrites `data/catalog.duckdb` and wanted a quiet tree and its own commit. Had
only one been possible, F-1 was always the one to do — a wrong value in the data
outranks a missing convenience flag.

F-1 has its own commit, pushed separately from F-2. A19 does too.

---

## Not on this list

- F-2 — closed on 2026-10-27; its change and rationale are in `CHANGELOG.md`
  under `[Unreleased]`.
- The 15 data traps and the accepted risks in `BUG.md` Parts 1 and 3 — mitigated
  or closed by design, not pending work.
- A1–A32 — fixed, each with a guard that was seen to fail first. A1–A19 were on
  this list or found while closing it; A20–A32 were closed by the later brief
  audit and the refresh probe and are recorded only in `BUG.md`.
- Anything in the held-out set's two retained failures — those are documented
  limitations of rule interpretation, kept failing on purpose. The third, 30 lb,
  turned out to be a defect with a known fix and was closed as `BUG.md` A34.
