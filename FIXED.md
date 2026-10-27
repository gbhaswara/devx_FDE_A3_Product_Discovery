# FIXED.md — the remaining fixes

Working list of what is **not** fixed, opened after the `BUG.md` audit on
2026-10-27. Two items are open; nothing else in `BUG.md` is.

This file is the to-do list, not the record. The record stays in `BUG.md` (one
entry per defect, with its guard), and the history stays in `CHANGELOG.md`. An
item leaves this file only when its stated verification has been run and passed —
not when the code is written.

**Status: 2 open · 0 in progress · 0 closed since the audit.**

---

## F-1 — A16: `unit_word` still holds the volume-pricing note on four SKUs

**Type:** shipped-code defect · **Severity:** low · **Status:** OPEN

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
  0 review items — i.e. only `unit_word` moved;
- `unshare -rn .venv/bin/python -m pytest` passes;
- `BUG.md` A16 moves to **FIXED** with the falsification note, and the change gets
  its own `CHANGELOG.md` entry.

**Note.** The catalog site must be served over HTTP at 1 req/s for the re-ingest.
Do not crawl `file://`, and do not hand-edit the DuckDB file.

---

## F-2 — the eval CLI cannot name the catalog, so 21/21 on v2 is not reproducible from `./run.sh`

**Type:** reproducibility gap (CLI + docs), not a shipped-behaviour defect ·
**Severity:** medium for the submission, because the claim is scored ·
**Status:** OPEN

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

F-2 first: it is small, it touches no data, and it makes the existing evidence
reproducible before the snapshot changes. F-1 second: it is the only actual
defect, and it rewrites `data/catalog.duckdb`, so it wants a quiet tree and its
own commit.

Each item gets its own commit and its own verification run. Do not batch them.

---

## Not on this list

- The 15 data traps and the accepted risks in `BUG.md` Parts 1 and 3 — mitigated
  or closed by design, not pending work.
- A1–A15, A17 and A18 — fixed, each with a guard that was seen to fail.
- Anything in the held-out set's three retained failures — those are documented
  limitations of rule interpretation, not defects with a known fix.
