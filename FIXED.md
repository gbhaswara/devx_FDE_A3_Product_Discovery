# FIXED.md — the remaining fixes

Working list of what is **not** fixed, opened after the `BUG.md` audit on
2026-10-27. Two items are open; nothing else in `BUG.md` is.

This file is the to-do list, not the record. The record stays in `BUG.md` (one
entry per defect, with its guard), and the history stays in `CHANGELOG.md`. An
item leaves this file only when its stated verification has been run and passed —
not when the code is written.

**Status: 2 open · 0 in progress · 0 closed since the audit.**

---

## How these two items map to the brief

The A3 brief is the customer's agreed specification. Neither item adds a feature,
changes a pricing rule, or touches the assistant's behaviour. Both are small
enough to sit inside the brief's six-hour scope, and neither may violate a
constraint to close.

| Item | Brief requirement it serves | Scoring area | Constraint it must respect |
|---|---|---|---|
| **F-1** (A16) | Must-have 1 — normalised product records; A3 “Data” — complete, correctly typed records | Data · technical correctness · honesty | HTTP only · ≤2 req/s · deterministic code · provenance kept |
| **F-2** (`--catalog`) | Must-have 7 — test set and results; submission item 3 — evaluation results including failures | AI and data evaluation · communication · honesty | Default command unchanged · no new dependency · no pricing or model change |

**What is not claimed.** F-1 is a display-only field. It is not one of the fields
the brief names — size, weight, colour, finish, sides, colour mode, pack size,
prices, stock — so it is a correctness fix for a published record, not a
must-have gap. F-2 is not a customer-facing requirement at all; it makes an
existing evaluation claim reproducible with the documented command. If time were
short, F-1 would still be the one to fix, because it is a wrong value in the
data; F-2 is evidence quality.

**Constraints that apply to both fixes.**

- The catalog site is served over HTTP. Never `file://`, never a direct file read.
- Crawl at **1 req/s**. The brief permits up to 2; `robots.txt` states
  `Crawl-delay: 1`, and the lower rate is the one the rest of the project uses.
- No API key is committed; credentials stay in environment variables. Nothing in
  either fix reads one.
- Pricing stays deterministic and untouched. No price, total or tier may move
  because of either fix.
- The data is used only for this assignment.
- The demo path stays runnable: after F-1 a fresh site re-ingests without code
  changes, and after F-2 the evaluation can name the catalog it scored. Neither
  fix adds a required step to the README's five-command quickstart.
- Failures stay in the results. Neither fix may turn a documented failure into a
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

## F-2 — the eval CLI cannot name the catalog, so 21/21 on v2 is not reproducible from `./run.sh`

**Type:** reproducibility gap (CLI + docs), not a shipped-behaviour defect ·
**Severity:** medium for the submission, because the claim is scored ·
**Status:** OPEN

**Brief alignment.** Must-have 7 asks for a test set *and your results*, and
submission item 3 asks for the evaluation results *including cases where the
system fails*. The brief also says it cares about *evidence that the system works,
and honesty about where it does not*. A result that is true but cannot be
reproduced with the documented command is weak evidence, and the 21/21 figure sits
in the README where a reviewer will try it. The fix adds no product behaviour: it
makes the evaluation name the catalog it already knows it scored.

Must-have 8 — the refresh path — is already met by `./run.sh verify-refresh`; this
fix does not implement refresh. It makes the two-catalog evaluation legible, which
is part of the demo-round story rather than a new capability. If scope were
tighter, the zero-code alternative would be to document the Python invocation
beside the claim; the flag is preferred because the run should be able to say
which catalog it scored without a reader writing Python.

`run_eval` takes `catalog_name`, and `BUG.md`/`README.md` claim **21/21 on v2**.
The CLI never passes the argument, so it always defaults to `v1`:

```bash
./run.sh verify-refresh --keep
./run.sh eval --db .refresh-verification/mutated.duckdb
# Evaluation against v1 (...mutated.duckdb)
# cases: 28  ran: 24  not run: 4  passed: 17  failed: 7
```

The number is right; the documented path to it is wrong. The 21/21 result was
produced through the Python API:

```python
run_eval(db_path=Path(".refresh-verification/mutated.duckdb"), catalog_name="v2")
# cases: 28  ran: 21  not run: 7  passed: 21  failed: 0
```

**Fix.** Add `--catalog {v1,v2}` to the `eval` subcommand (default `v1`, so the
existing command is byte-identical), pass `catalog_name` through `run_eval`, and
name the exact command wherever 21/21 appears (`README.md`, `TEST.md`,
`eval/results.md`). A run should still print which catalog it scored — it already
does.

**Files:** `src/paperlane/cli.py`, `tests/test_evaluate.py` (or the CLI test
module), `README.md`, `TEST.md`, `eval/results.md`.

**Closes when:**

- `./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb` exits 0
  with **21/21**;
- the default `./run.sh eval` still exits 0 with **24/24**, unchanged;
- a test pins the flag reaching `run_eval` (a mocked `run_eval` is enough; the
  numbers are already pinned elsewhere);
- the v2 command is written down next to the 21/21 claim;
- no credential, no new dependency, and no change to the case files.

---

## Order

The order is practical, not a priority ranking: **F-2 first** because it is small,
touches no data, and makes the existing evidence reproducible before the snapshot
changes; **F-1 second** because it rewrites `data/catalog.duckdb` and wants a
quiet tree. If only one could be done, it would be **F-1** — a wrong value in the
data outranks a missing convenience flag.

Each item gets its own commit and its own verification run. Do not batch them.

---

## Not on this list

- The 15 data traps and the accepted risks in `BUG.md` Parts 1 and 3 — mitigated
  or closed by design, not pending work.
- A1–A15, A17 and A18 — fixed, each with a guard that was seen to fail.
- Anything in the held-out set's three retained failures — those are documented
  limitations of rule interpretation, not defects with a known fix.
