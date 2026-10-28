# ARCHITECTURE.md — PaperLane Product Discovery

Architecture overview for the A3 submission. Requirements live in the eleven main specs under `openspec/specs/`; the reasoning behind each technical choice is in the `design.md` of the change that introduced it, under `openspec/changes/archive/`.

## What the system does

A sales assistant over PaperLane's paper catalog. A customer sends a chat message such as *"We need letter-size flyers, one side, colour, under 250 a pack, 20 packs."* The system reads the live catalog, finds matching products, explains why each matches, and returns a complete price breakdown — with every figure computed in deterministic code.

## Component view

```
                    PaperLane site (localhost:8000)
                    36 product pages | 59 pricing docs | 7 category pages
                                    |
                                    |  HTTP only, 1 req/s (site permits 2)
                                    v
                    +-----------------------------------+
                    |  CRAWLER                          |
                    |  discovery: pages + variant rows  |
                    |  provenance on every fetch        |
                    +-----------------------------------+
                                    |
                                    v
                    +-----------------------------------+
                    |  EXTRACTION LADDER                |
                    |  1 variant table                  |
                    |  2 <table class='specs'>          |
                    |  3 <dl class='specs'>             |
                    |  4 prose regexes                  |
                    |  5 structured model extraction    |
                    |  floor: NEEDS_REVIEW row          |
                    +-----------------------------------+
                                    |
                                    v
                    +-----------------------------------+
                    |  NORMALISER                       |
                    |  size -> code + dimensions        |
                    |  weight: 4 forms -> grammage      |
                    |  shade vs print colour mode       |
                    |  pack sheets, not unit word       |
                    |  money -> integer satang          |
                    +-----------------------------------+
                                    |
                                    v
                    +-----------------------------------+
                    |  CATALOG STORE (DuckDB)           |
                    |  build new file -> atomic swap    |
                    |  provenance on every row          |
                    +-----------------------------------+
                          |                       |
        +-----------------+                       +------------------+
        v                                                          v
+---------------------+                              +----------------------+
|  PRICING ENGINE     |                              |  SEARCH              |
|  pure, deterministic|                              |  hard filters        |
|  no I/O, no model   |                              |  + absent-attr rules |
|  tiers -> sale ->   |                              |  + alias layer       |
|  subtotal -> deliv  |                              |  + deterministic rank|
|  -> VAT (half-up)   |                              |  + match_reasons     |
+---------------------+                              +----------------------+
                                                              ^
                                        +---------------------+
                                        |  EMBEDDINGS (optional)
                                        |  local HTTP, no key
                                        |  similarity = a TIEBREAK
                                        |  cannot change membership
                                        +----------------------+
        |                                                          |
        +----------------------+-----------------------------------+
                               v
                    +-----------------------------------+
                    |  ASSISTANT                        |
                    |  model: intent -> criteria only   |
                    |  conversation: merge across turns |
                    |  (after interpret, over typed     |
                    |   criteria; re-validated; the     |
                    |   model never sees the transcript)|
                    |  rules: fallback interpretation   |
                    |  code: products + prices + reasons|
                    |  assertions: no invented product  |
                    |              stated == computed   |
                    +-----------------------------------+
                               |
                               v
                    +-----------------------------------+
                    |  HTTP API (FastAPI)               |
                    |  POST /api/ask  /api/quote        |
                    |  POST /api/quote/lines            |
                    |  GET  /api/products /api/health   |
                    |  GET  /api/diff /api/metrics      |
                    |  DELETE /api/conversations/{id}   |
                    |  POST /ask  + one server page     |
                    +-----------------------------------+
                               |
                               v
                    +-----------------------------------+
                    |  RECORDS (one line per request)   |
                    |  path, outcome, fallback reason   |
                    |  stage timings, snapshot identity |
                    |  no text, no credentials          |
                    +-----------------------------------+
                               |
                               v
                    +-----------------------------------+
                    |  METRICS (derived on every read)  |
                    |  fallback / zero-result / backlog |
                    |  p95 latency / disagreement       |
                    |  no counters during handling      |
                    +-----------------------------------+
```

## The load-bearing design decisions

Six properties carry most of the score. Each is structural — enforced by the shape of the code, not by a convention.

### 1. Prices cannot come from the model

The model's only output is structured search criteria. Product selection, pricing and justification happen in deterministic code. A post-generation assertion rejects any reply referencing a SKU absent from the current snapshot.

This matters because the guarantee is *structural* rather than *behavioural*. The model is not instructed to avoid inventing products; it has no channel through which to introduce one.

The same holds once a conversation exists. The merge runs **after** interpretation, over typed `Criteria`, and only the current turn's text ever reaches an interpreter — so every constraint in a merged request is traceable to a turn that stated it, and the model still has no channel into the numbers. See `docs/conversation-memory.md`.

### 2. One pricing path, shared by every caller

`POST /api/quote` (structured criteria) and `POST /api/ask` (free text) both call the same pure pricing function. The evaluation harness calls it too.

Consequence: a pricing bug cannot appear in one entry point and not another, and most of the evaluation set runs with no model and no network.

### 3. A page cannot silently disappear

The extraction ladder ends in a review row, never an exception and never a skip. A refresh that loses products reports the loss.

Consequence: the demo round's updated site can introduce a fifth markup shape without the catalog quietly shrinking.

### 4. Absent is not negative

Printing attributes (`sides`, colour mode) do not apply to plain paper. They are stored as not-applicable, and a constraint on them does not exclude those products.

Consequence: the naive `WHERE sides = 'single'` — which returns *zero* paper products — cannot be written.

### 5. Similarity reorders; it cannot change what qualifies

The optional embedding layer scores only candidates that already passed the filter. There is no code path that consults a similarity score before `_evaluate()`, so "semantic ranking cannot introduce or exclude a product" is a property of the structure rather than of careful coding.

Consequence: the ranking key gains a `similarity` term **conditionally** — omitted entirely when no provider is configured, never inserted as a constant, so the unconfigured path is the previous tuple exactly. The term sorts *after* price, measured: before price it regressed 6 of 28 recorded cases and displaced the cheapest-first rule.

### 6. Metrics are derived from records, never counted

No counter is incremented while a request is handled. Each handled request appends one structured line; every measure is computed by scanning those lines on read.

Consequence: a metric cannot drift from the events it claims to summarise. A counter and its log can disagree, and when they do you no longer know which one is true. The cost is an O(n) scan per read — microseconds at this scale.

Two supporting choices make the measures honest rather than merely present: every rate returns `null` on an empty basis instead of `0.0` (a 0% failure rate over zero requests and a perfect run must not print the same), and the disagreement metric reports how many replies it *checked* as well as how many disagreed.

## Data model

```
products
  sku                      primary key, leaf SKU (variant rows are their own SKU)
  name, brand, category
  size_code                A3 | A4 | A5 | LTR | LGL
  width_mm, height_mm      integers
  weight_gsm               normalised grammage
  weight_raw               original string, e.g. "20 lb bond (75 gsm)"
  weight_form              gsm | g_per_m2 | lb_only | lb_with_gsm
  colour_name              paper shade: White, Cream, Pastel pink, ...
  colour_mode              print: cmyk | mono | not-applicable
  sides                    single | double | not-applicable
  finish                   Gloss | Matte | Smooth | Uncoated | ...
  pack_sheets              integer — the authoritative quantity basis
  unit_word                "ream" | "pack" — display text only, never filtered on
  list_price_satang        integer
  sale_price_satang        integer or null
  stock_status             in_stock | out_of_stock | discontinued
  back_in_stock_date       nullable
  source_url, source_shape, crawled_at, snapshot_id

price_tiers
  sku, min_qty, unit_price_satang, source_url, snapshot_id
  primary key (sku, min_qty)          -- tiers are per leaf SKU, not per product page

product_aliases
  sku, alias, alias_type, confidence  -- "letter", "8.5x11", "4/4", "cmyk", "duplex"

snapshots
  snapshot_id, started_at, finished_at, base_url, page_count, sku_count

page_reviews
  url, snapshot_id, reason, raw_excerpt, created_at, resolved_at
```

`pack_sheets` is separate from price because "under 250 a pack" is unanswerable without it. `weight_raw` is kept alongside `weight_gsm` because the source states weight four different ways, and a conversion must be defensible in the interview.

There is deliberately **no `stock_on_hand` column**. The source publishes a three-valued status and a restock date, never a count, so no requested quantity is compared with stock — an unavailable SKU is refused at any quantity, and an available one is priced at any quantity. See `devx_FDE_A3_Product_Discovery/docs/ingestion.md`.

**Conversation state is deliberately not in this store.** It is not catalog data, it is per-customer and short-lived, and putting it in the snapshot would make it survive a refresh it has no business surviving. `conversation.py` holds it separately: an in-memory store for the service, and a JSONL store for the CLI, both bounded (`MAX_CONVERSATIONS = 100` LRU, `MAX_TURNS = 20`). Neither holds request text — only `Criteria`. See `docs/conversation-memory.md`.

## Pricing pipeline

```
unit_price(sku, qty):
    if sale_price:  return sale_price                  # PR3: sale beats list and tiers
    best = list_price                                  # MUST initialise here, not None
    for tier in tiers sorted by min_qty:
        if qty >= tier.min_qty: best = tier.unit_price  # PR2: highest met tier
    return best

quote(lines):
    subtotal = sum(unit_price(sku, qty) * qty)          # PR4
    delivery = 0 if subtotal >= 3_000_00 else 150_00    # PR4: per ORDER, not per line
    vat      = round_half_up((subtotal + delivery) * 7 / 100)   # PR5
    total    = subtotal + delivery + vat
```

Three lines in that pseudocode are where the errors live, so each has a named test:

| Line | Failure if wrong | Detection |
|---|---|---|
| `best = list_price` | Items with a 5+ or 10+ tier return nothing at qty 1–4 | unit test at qty below the lowest tier |
| `delivery` on the summed subtotal | A mixed order pays delivery twice | multi-item case where neither line crosses the threshold alone |
| VAT on `subtotal + delivery` | Total understated | small-order case; VAT-on-subtotal-only differs by a fixed amount |

## API surface

| Endpoint | Purpose | Calls the model |
|---|---|---|
| `POST /api/ask` | Free text in, reply + criteria + candidates out | yes (with rule fallback) |
| `POST /api/quote` | Structured criteria in, candidates + prices out | **no** |
| `POST /api/quote/lines` | A multi-line basket, priced once per order | **no** |
| `GET /api/products` | Inspect the normalised catalog | no |
| `GET /api/health` | Snapshot id, product count, store readable, model reachable | no |
| `GET /api/diff` | Current snapshot vs previous | no |
| `GET /api/metrics` | The five operational measures, derived from request records | no |
| `DELETE /api/conversations/{id}` | Discard a conversation. Idempotent | no |
| `GET /` | The single server-rendered page | no |
| `POST /ask` | The htmx fragment the page swaps in | yes (with rule fallback) |

The four that interpret or quote — `POST /api/ask`, `POST /api/quote`,
`POST /api/quote/lines` and the page's `POST /ask` — write a request record, as
does a request the framework rejects before it reaches a handler; the rest do not.
Recording the inspection endpoints would dilute the fallback and zero-result
rates with traffic that structurally cannot exhibit either — see
`docs/observability.md`.

Every response declares exactly one outcome:

| Outcome | Meaning | Required fields |
|---|---|---|
| `quoted` | Candidates satisfy all hard constraints | `reply`, `candidates[]`, `figures` |
| `clarified` | A needed detail is missing and would change the answer | `reply`, `questions[]` |
| `no_match` | Constraints are complete but nothing satisfies them | `reply` |
| `refused` | The suitable item is out of stock or discontinued | `reply`, `refused[]` |

The four-outcome enum is what makes the must-haves testable. "Clarifying questions when ambiguous" and "a clear no exact match" are assertions on `outcome`, not judgements about prose. The record schema adds a fifth value, `failed`, for a request that produced no reply at all — it is not an assistant outcome, but failures have to be countable in the same vocabulary or they become invisible.

## Refresh and snapshot lifecycle

```
ingest  ->  build catalog.<snapshot_id>.duckdb    (fresh file, never mutated)
        ->  validate rows
        ->  refuse the swap on 0 SKUs or < half the serving count (exit 3)
        ->  os.replace() over catalog.duckdb      (atomic swap; readers unaffected)
diff    ->  attach old + new read-only, full outer join, group changes
serve   ->  open catalog.duckdb read-only, one connection per request
```

A single-writer store would normally be a limitation. Rebuild-and-swap removes it rather than working around it, and gives a failed ingest nowhere to damage a working catalog. A committed snapshot means the service starts without crawling.

The collapse gate is a count check, not a completeness judgement: a genuine catalog cut passes `--accept-shrink`, a first ingest is never refused, and exactly half the previous count is allowed.

## Deployment

One process, one command, same origin. No build step, no separate frontend, no cross-origin configuration — the submission requires running in five commands or fewer.

```
uv sync
./run.sh ingest --base-url http://localhost:8000/paperlane/
./run.sh serve
```

## Verified site facts

Measured against `paperlane/` during analysis; see `devx_FDE_A3_Product_Discovery/docs/pre/ANALYZE_01.md` §12 for the full log.

| Fact | Value |
|---|---|
| Product pages | 36 |
| Leaf SKUs | 72 (30 single-SKU pages + 42 flyer variant rows) |
| Volume-pricing documents | 59, all belonging to SKUs that advertise them; zero orphans |
| Category pages | 7 (4 category index pages + 3 `page-2.html` continuation pages) |
| Markup shapes | 4: variant table (6), `<table>` (10), `<dl>` (10), prose-only (10) |
| Weight input forms | 4: grammage, grams-per-square-metre, pounds-with-grammage, pounds-alone |
| Out of stock | 2 — `PL-PR-A4-GL-170-44`, `PL-CL-A4-100-IVY` |
| On sale | 1 — `PL-PR-LTR-GL-170-40`, 299.00 → 259.00, volume pricing suppressed |
| Discontinued | 0 in v1 (PR8 names it, so expect it in the updated site) |
| `robots.txt` | `Allow: /`, `Crawl-delay: 1` |
| Full crawl | 105 requests ≈ 105 seconds at 1 req/s (36 product + 59 pricing + 7 category + 3 root) |

### How the four shapes name the same field

The ladder does not just handle different *structure* — the four shapes use different *labels*, and one of them splits a field in two. This is the mapping the normaliser has to implement, verified against every page.

| Concept | `table` (10) | `dl` (10) | `variant-table` (6) | prose (10) |
|---|---|---|---|---|
| SKU | `Item code` | `SKU` | `Item code` (column) | `Item code: ...` in text |
| Brand | `Brand` | `Manufacturer` | — | in prose |
| Size | `Size` = `A4 (210 × 297 mm)` | **`Paper size` = `A5` + `Dimensions` = `148 × 210 mm`** | fixed per page | in prose |
| Weight | `Weight` | `Basis weight` | `Paper weight` (per row) | `weighs N gsm.` |
| Shade | `Colour` | `Shade` | — | in prose |
| Print colour | — | — | `Colour` = `Full colour (CMYK)` | — |
| Finish | `Finish` | `Surface` | — | in prose |
| Pack size | `Sheets per pack` | `Pack contents` | fixed: "pack of 100" | in prose |

Two consequences worth naming, because both are silent:

- **`Colour` means a different thing in `table` and `variant-table`.** In `table` it is the paper shade (`White`); in `variant-table` it is the print mode (`Full colour (CMYK)`). Same label, two fields (T9).
- **`dl` splits size into code and dimensions**, while `table` concatenates them into one string. A normaliser that assumes one field per concept will lose the dimensions on every `dl` page — or, worse, store `A5` as a display string and never derive a `size_code`.

## Known architectural limitations

- **Conversation memory is conservative and per process.** A follow-up continues only when it names no new subject (a category or a size), so *"the cheaper one"* with no subject is a fresh request. The API's store is in memory, so a restart forgets every conversation and two workers do not share one; there is no expiry, only bounds. Deliberate: a wrong carry is a confident wrong answer, worse than a lost one. The model never sees the transcript — the merge is over typed criteria, after interpretation. Reasoning and the full list of limits in `docs/conversation-memory.md`; the three defects found after it shipped are A12–A14 in `BUG.md` Part 2b.
- **Semantic search is a tiebreak only.** A purely descriptive request with no structured terms can miss — embeddings never enter the filter. The tiebreak decides ties among equally-priced items; measured against the recorded set it reorders 3 of 28 cases with zero improvements and zero regressions, so it is not a quality claim.
- **Rule interpretation is narrower than the model.** Paraphrases the model handles may fall back to a clarification. The fallback rate is measured so the degradation is visible.
- **No authentication, no rate limiting beyond the crawler.** This is a local demonstration service.
- **Request records grow without bound.** No rotation; the remedy is manual (`rm` the file or move it aside). p95 is over a count window of the last 1000 records, not a time window, so a burst can flush history. The `request_digest` is a grouping aid and **not** anonymisation — a 16-character hash of a short string is brute-forceable. Reasoning in `docs/observability.md`.
- **One site, one layout family.** The extraction ladder covers this site's four shapes plus a structured fallback; onboarding a different supplier would need a parser profile per site.
