# FIXED.md — the remaining fixes

Working list of what is **not** fixed, opened after the `BUG.md` audit on
2026-10-27. One item is open; nothing else in `BUG.md` is.

This file is the to-do list, not the record. The record stays in `BUG.md` (one
entry per defect, with its guard), and the history stays in `CHANGELOG.md`. An
item leaves this file only when its stated verification has been run and passed —
not when the code is written.

**Status: 1 open · 0 in progress · 1 closed since the audit (F-2, 2026-10-27).**

---

## How the remaining item maps to the brief

The A3 brief is the customer's agreed specification. This item does not add a
feature, change a pricing rule, or touch the assistant's behaviour. It is small
enough to sit inside the brief's six-hour scope, and it may not violate a
constraint to close.

| Item | Brief requirement it serves | Scoring area | Constraint it must respect |
|---|---|---|---|
| **F-1** (A16) | Must-have 1 — normalised product records; A3 “Data” — complete, correctly typed records | Data · technical correctness · honesty | HTTP only · ≤2 req/s · deterministic code · provenance kept |

**What is not claimed.** F-1 is a display-only field. It is not one of the fields
the brief names — size, weight, colour, finish, sides, colour mode, pack size,
prices, stock — so it is a correctness fix for a published record, not a
must-have gap. F-2 — the eval CLI's missing `--catalog` — is closed; it served
must-have 7 and submission item 3, added no product behaviour, and its change,
verification and rationale are in `CHANGELOG.md` under `[Unreleased]`.

**Constraints that apply to this fix.**

- The catalog site is served over HTTP. Never `file://`, never a direct file read.
- Crawl at **1 req/s**. The brief permits up to 2; `robots.txt` states
  `Crawl-delay: 1`, and the lower rate is the one the rest of the project uses.
- No API key is committed; credentials stay in environment variables. Nothing in
  this fix reads one.
- Pricing stays deterministic and untouched. No price, total or tier may move
  because of this fix.
- The data is used only for this assignment.
- The demo path stays runnable: after F-1 a fresh site re-ingests without code
  changes. The fix adds no required step to the README's five-command quickstart.
- Failures stay in the results. The fix may not turn a documented failure into a
  pass by changing the expectation.

---

## F-1 — A16: `unit_word` still holds the volume-pricing note on four SKUs

**Type:** shipped-code defect · **Severity:** low · **Status:** OPEN

**Brief alignment.** Must-have 1 asks for a database of *normalised* product
records, and the brief's “what we look for” asks for *complete, correctly typed
records*. This field is correctly typed — it is a string — but its value is a
sentence about pricing, not a unit, so it is not normalised. It is not a missing
field: size, weight, colour, finish, sides, colour mode, pack size, prices and
stock are all present and correct. This is the one wrong value in a published
record, which is why it is worth fixing rather than only documenting.

`/api/products` returns `"No volume pricing for this item."` as the `unit_word`
for four products. Replies and the catalog column are unaffected because both use
`pack_sheets` via `assistant.unit_phrase`; the raw field is what is wrong.

```
PL-CL-LTR-24-BRT   pack_sheets 500
PL-CS-A4-160-AST   pack_sheets 100
PL-CS-A4-250-BLK   pack_sheets 100
PL-PH-A4-230-MT    pack_sheets  50
```

**Cause.** `extract._unit_word` returns `box.css_first(".muted")` first and only
reads the text after `/` when there is no `.muted` at all. On these four pages the
only `.muted` in the price box is the volume note, so the `/ pack` tail is never
reached. This is unchanged since A16 was registered.

**Reproduce.**

```bash
cd devx_FDE_A3_Product_Discovery
PYTHONPATH=src .venv/bin/python - <<'EOF'
from pathlib import Path
from paperlane.catalog import load_products
for r in load_products(Path("data/catalog.duckdb")):
    if "volume" in (r.get("unit_word") or "").lower():
        print(r["sku"], "|", r["unit_word"])
EOF
```

**Fix.** In `_unit_word`, prefer the slash tail when the `.muted` node is the
volume note (or simply prefer the slash tail whenever it exists, with the
`.muted` text as the fallback). Add a test built on this exact price-box shape —
no unit element, one `.muted` volume note, `/ pack` in the big price's parent.
Then re-ingest the committed snapshot, because `unit_word` is stored, not derived
at read time.

**Files:** `src/paperlane/extract.py`, `tests/test_extract.py`,
`data/catalog.duckdb` (re-ingest), `BUG.md` A16.

**Closes when:**

- the four SKUs carry a real unit (`/ pack`, `/ ream`, …) and no row carries the
  volume note;
- a test on the four-SKU shape fails against the current branch order and passes
  after the change (the fix is seen to fail first);
- the re-ingested snapshot still has 72 products, 105 tiers, 2 out of stock, and
  0 review items — i.e. only `unit_word` and the `crawled_at` provenance
  timestamps moved. A timestamp change is expected and required by must-have 1;
  any other field moving is a defect;
- `unshare -rn .venv/bin/python -m pytest` passes;
- `BUG.md` A16 moves to **FIXED** with the falsification note, the item is
  removed from this file, and the change gets its own `CHANGELOG.md` entry.

**Note.** The catalog site must be served over HTTP at 1 req/s for the re-ingest
(the brief permits 2; `robots.txt` says 1). Do not crawl `file://`, and do not
hand-edit the DuckDB file — the only way the brief's “re-ingest without code
changes” story stays true is if the snapshot is produced by the crawler.

---

## Order

F-2 went first because it was small, touched no data, and made the existing
evidence reproducible before the snapshot changed. **F-1 is the one still open**,
and it rewrites `data/catalog.duckdb`, so it wants a quiet tree and its own
commit. Had only one been possible, F-1 was always the one to do — a wrong value
in the data outranks a missing convenience flag.

F-1 gets its own commit and its own verification run. F-2 already has both.

---

## Not on this list

- F-2 — closed on 2026-10-27; its change, verification and rationale are in
  `CHANGELOG.md` under `[Unreleased]`.
- The 15 data traps and the accepted risks in `BUG.md` Parts 1 and 3 — mitigated
  or closed by design, not pending work.
- A1–A15, A17 and A18 — fixed, each with a guard that was seen to fail.
- Anything in the held-out set's three retained failures — those are documented
  limitations of rule interpretation, not defects with a known fix.
