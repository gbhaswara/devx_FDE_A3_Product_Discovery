# Refresh

How the catalog snapshot is rebuilt, and what makes a rebuild safe to run against
a live service.

Code: `src/paperlane/catalog.py`, `ingest.py`, `crawl.py`. Tests:
`tests/test_catalog.py`, `test_ingest.py`, `test_crawl.py`.

---

## The five commands

From the project root, with the site being served at `http://localhost:8000/`:

```bash
uv sync
(python3 -m http.server 8000 &)              # serve the site itself, on 8000
./run.sh ingest --base-url http://localhost:8000/paperlane/
./run.sh diff
./run.sh serve                               # the assistant, on 8001
```

The two ports are separate on purpose: **8000 serves the catalog site**, which the
crawler reads; **8001 serves the assistant**, which reads the snapshot. Binding
the assistant to 8000 collides with the site and fails with
`address already in use`. `./run.sh serve --port N` overrides it.

`./run.sh ingest` takes about **1m45s** — 103 requests at 1 req/s, deliberately
rate-limited. It is not slow by accident: the site is a static copy of a real
supplier's catalog and the crawler treats it as one.

> **Serving directory matters.** The static server must be started from the
> **parent** of `paperlane/`, not from inside it. Started from inside, the
> documented URL `http://localhost:8000/paperlane/` returns 404.

---

## What a refresh does

```
crawl ──→ extract ──→ build to catalog.tmp.duckdb ──→ gate ──→ swap ──→ diff
                              │                        │         │
                              │                        │         └─ old file kept as
                              │                        │            catalog.previous.duckdb
                              │                        └─ 0 SKUs or < half → exit 3, staging kept
                              └─ any failure here leaves the serving file untouched
```

### Build, then swap

`build_snapshot()` writes a complete catalog to a **staging file**
(`catalog.tmp.duckdb`) and only then does `swap_into_place()` replace the serving
one with `os.replace`, which is atomic on the same filesystem.

A reader therefore sees either the whole old catalog or the whole new one, never a
half-written one. If the build fails partway — a bad price, an unreachable page —
the staging file is deleted and the serving catalog is byte-for-byte unchanged.
Both are asserted by `TestFailedIngestIsHarmless`.

**A structurally valid collapse is refused too.** Validation catches a bad row;
it does not catch a good row set that is almost empty because the markup changed
under the parser. `ingest._swap_refusal` therefore refuses the swap when the new
snapshot has **zero SKUs**, or fewer than **half** the rows the serving snapshot
has, and exits **3** with the staging file kept for inspection. A first ingest has
nothing to protect, so it is never refused; exactly half is allowed. A genuine
catalog cut passes `--accept-shrink`. This is a collapse guard, not a
completeness heuristic — see `GAPS_RESPONSE.md` §3 for why a general threshold
would fail the demo round.

### The baseline is kept

`swap_into_place()` moves the outgoing snapshot to `catalog.previous.duckdb`
before installing the new one. That is what makes `./run.sh diff` meaningful:
without it, the staging file is consumed by the swap and a diff would always
answer "nothing to compare against" — useless exactly when someone wants to know
what changed.

The baseline is gitignored. `catalog.duckdb` is committed.

---

## The diff report

`./run.sh diff` compares the previous snapshot against the current one and
classifies every change:

| Key | Meaning |
|---|---|
| `added` | SKUs in the new snapshot that were not in the old |
| `withdrawn` | SKUs that disappeared |
| `price_changed` | with `list_before` / `list_after` / `sale_before` / `sale_after` in satang |
| `availability_changed` | with `before` / `after` stock status |
| `tier_changed` | with the full before and after tier lists |
| `parse_failed` | unresolved review items from the new snapshot |
| `no_change` | `true` when every list is empty |
| `comparable` | `false` when there is no baseline, with a `reason` |

**`no_change: true` is a positive statement**, not an absence of findings. An
unchanged re-ingest reports it explicitly; `comparable: false` with a `reason`
means there was nothing to compare against. Conflating the two would make a
successful no-op look identical to a diff that never ran.

Verified against the real site: re-ingesting the unchanged catalog reports
`no_change: true` with all six lists empty.

---

## Review items persist

`review_items` holds everything the extractor could not resolve — an unrecognised
markup shape, an ambiguous price box, a category card disagreeing with its product
page, an advertised tier document that failed to load.

An unresolved item is **carried forward** to the next snapshot unless that run
reports it again. So a flagged problem stays flagged until someone marks it
resolved:

```sql
UPDATE review_items SET resolved = TRUE WHERE url = '…';
```

Without this the review backlog would be silently discarded by every rebuild —
which looks like a clean run and is not. `health()` reports both counts:

```json
{ "open_review_items": 2, "carried_review_items": 1 }
```

`carried_review_items` counts those inherited from an earlier run rather than
found by this one, so a growing number means nobody is working the backlog.

The committed snapshot currently has **0 open review items**: all 36 pages, 72
leaf SKUs and 59 tier documents parsed cleanly.

---

## Concurrency

Reads use a **read-only connection per request** (`open_readonly()`), not a shared
connection. DuckDB raises `Resource In Use Error` when one connection is shared
across threads; per-request read-only connections handled 20 concurrent reads in
0.02s with no errors, asserted by `TestConcurrentReads`.

Because a refresh writes to a *different* file and swaps atomically, reads are
never blocked by an ingest.

---

## Verified

| Check | Result |
|---|---|
| Requests per ingest | 103, at 1 req/s |
| Product pages | 36 |
| Leaf SKUs | 72 |
| Tier documents | 59 |
| Tier rows | 105 |
| Review items | 0 |
| Unchanged re-ingest | `no_change: true`, all lists empty |
| Failed build | serving catalog byte-identical afterwards |
| Concurrent reads | 20 simultaneous, 0 errors |

---

## When the site changes

1. `./run.sh ingest --base-url …`
2. `./run.sh diff`
3. Read `withdrawn` first — a SKU vanishing is the change most likely to be a
   crawler fault rather than a real catalog change.
4. Check `parse_failed` — a new markup shape shows up here before it shows up as
   wrong prices.
5. If `price_changed` includes unexpected items, re-run the evaluation set
   (`./run.sh eval`) before serving: the expected totals are computed from
   catalog data, so a genuine price change will surface as failures there.

A withdrawn SKU that is *not* genuinely discontinued usually means the page moved.
It will appear in `withdrawn` **and** as a review item, not silently disappear.
