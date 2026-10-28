# Ingestion

How the catalog gets from PaperLane's website into a queryable snapshot, and
what each of the four markup shapes actually looks like.

Code: `src/paperlane/crawl.py`, `extract.py`, `normalize.py`, `ingest.py`,
`catalog.py`. Tests: `tests/test_crawl.py`, `tests/test_extract.py`,
`tests/test_catalog.py`.

---

## The site must be served over HTTP

Volume pricing is loaded by JavaScript (`assets/tiers.js`) from
`api/pricing/<SKU>.json`. Opening the files from disk does not execute that
script, so a filesystem crawl silently loses **all 105 tier rows** and every
price above the list price is wrong.

So the crawler refuses a non-HTTP base URL outright:

```python
parsed = urlparse(base_url)
if parsed.scheme not in ("http", "https"):
    raise CrawlError(...)
```

Serve from the **parent** of `paperlane/`, because the pages reference
`../assets/` and `../api/`:

```bash
cd devx_FDE_A3_Product_Discovery
python3 -m http.server 8000
# site is now at http://localhost:8000/paperlane/
```

Serving from *inside* `paperlane/` breaks the documented URL — verified 404.

---

## Rate limit

The footer permits "max 2 requests per second" and `robots.txt` sets
`Crawl-delay: 1`. The crawler defaults to **1 req/s** and refuses anything
above 2:

```python
if rate_per_second > 2.0:
    raise ValueError("the site permits at most 2 requests/second")
```

A full ingest is **103 requests** and takes about 1m43s at 1 req/s.

The crawl is sequential. Concurrency buys nothing when the permitted rate is
1–2 req/s and only risks exceeding it.

---

## Discovery: 36 pages → 72 leaf SKUs

The walk is:

```
index.html
  → 4 category pages (+ 3 pager pages)     7 requests
    → 36 product pages                     36 requests
      → 59 volume-pricing documents        59 requests
                                           ─────────────
                                           103 requests
```

Discovery follows links rather than hard-coding URLs, so a renamed page or a new
category still works.

**The 36 pages are not 36 SKUs.** Six flyer pages are variant tables: each row
is its own purchasable SKU with its own price and its own tier document.

| Page kind | Pages | Leaf SKUs |
|---|---|---|
| single-SKU product pages | 30 | 30 |
| flyer variant tables | 6 | 42 |
| **total** | **36** | **72** |

A crawler that treats a flyer page as one product loses 36 of the 72 SKUs.

---

## The four markup shapes

Verified counts: `table` 10, `dl` 10, `prose` 10, `variant-table` 6.

Shape detection is by **markup structure**, not by URL, so a new page in an
existing shape is handled without a code change:

| Shape | Detected by | Pages |
|---|---|---|
| `variant-table` | the text `Options and prices` | 6 |
| `table` | `<table class='specs'>` | 10 |
| `dl` | `<dl class='specs'>` | 10 |
| `prose` | `weighs N` with no spec block | 10 |

### Shape 1 — `table` (10 pages)

```html
<table class='specs'>
  <tr><th>Item code</th><td>PL-CP-A4-80-ECO</td></tr>
  <tr><th>Brand</th><td>PaperLane Essentials</td></tr>
  <tr><th>Size</th><td>A4 (210 × 297 mm)</td></tr>
  <tr><th>Weight</th><td>80 gsm</td></tr>
  <tr><th>Colour</th><td>White</td></tr>
  <tr><th>Finish</th><td>Uncoated</td></tr>
  <tr><th>Sheets per pack</th><td>500</td></tr>
</table>
```

Size is **concatenated** into one string. `Colour` here is the paper shade.

### Shape 2 — `dl` (10 pages)

```html
<dl class='specs'>
  <dt>SKU</dt><dd>PL-CP-A5-80</dd>
  <dt>Manufacturer</dt><dd>PaperLane Essentials</dd>
  <dt>Paper size</dt><dd>A5</dd>
  <dt>Dimensions</dt><dd>148 × 210 mm</dd>
  <dt>Basis weight</dt><dd>80 gsm</dd>
  <dt>Shade</dt><dd>White</dd>
  <dt>Surface</dt><dd>Uncoated</dd>
  <dt>Pack contents</dt><dd>500 sheets</dd>
</dl>
```

Three label differences from `table`, all silent if unmapped:

* `Manufacturer`, not `Brand`
* size **split** across `Paper size` + `Dimensions`
* `Shade` and `Surface`, not `Colour` and `Finish`

### Shape 3 — `variant-table` (6 pages, 42 SKUs)

```html
<h2>Options and prices</h2>
<table>
  <tr><th>Item code</th><th>Paper weight</th><th>Printing</th><th>Colour</th>
      <th>Price per pack of 100</th><th>Volume pricing</th><th>Availability</th></tr>
  <tr><td>PL-PR-LTR-GL-170-40</td><td>170 gsm</td><td>Single-sided</td>
      <td>Full colour (CMYK)</td>
      <td><del>฿299.00</del> ฿259.00<span class='sale'>Sale</span></td>
      <td><span data-sku='...' data-sale='1'>Not available on sale items</span></td>
      <td><span class="stock-in">In stock</span></td></tr>
</table>
```

* **`Colour` here is the print colour mode**, not the paper shade. The same word
  means two different things in two shapes; they are stored in two different
  fields (`colour_mode` vs `colour_name`).
* Size is stated **once in the `<h1>`** for all rows, including the two
  spellings `8.5 × 11 in` and `8½ × 11 in`.
* Pack size comes from the **column header** ("Price per pack of 100").
* Availability is **per row**: `PL-PR-A4-GL-170-44` is out of stock while its
  neighbours are in stock. The row's own availability cell decides **both**
  fields — status and restock date — because a whole-page scan for "out of
  stock" finds the one unavailable row and would otherwise attach its date to
  every sibling, giving an in-stock record a restock date it cannot have
  (`BUG.md` A23). The page-level scan survives only for a table with no
  availability column, where nothing else states availability.
* Availability is **read from a closed set of wordings**, never assumed:
  `In stock`, `Out of stock … expected back <date>`, `Discontinued`. Wording the
  parser does not recognise makes the row `unknown` and produces a review row
  carrying the raw cell text, because an `in_stock` default turns a copy edit on
  the site into a catalog of items that cannot be bought (`BUG.md` A31). The
  same rule applies to a page-level badge.
* Columns are located **by header name**, never by fixed index.

### Shape 4 — `prose` (10 pages)

No spec table at all. Every fact is a sentence:

> Lotus Bright Premium A4 80gsm **from Lotus Bright** is supplied as a **ream of
> 500 sheets**. Each sheet is **A4 (210 × 297 mm)** and **weighs 80 gsm**. The
> **white** sheets have a **uncoated** surface and run well in laser and inkjet
> printers.

> Nusa Paper US Letter 90 from Nusa Paper is supplied as a ream of 500 sheets.
> Each sheet is US Letter (8.5 × 11 in) and weighs **90 g/m²**. …

The second is the only page using `g/m²` (U+00B2). Both are matched.

A crawler that only reads spec tables drops **10 of 36 pages** — and one of them,
`PL-CP-A4-80` at 129.00, is the brief's own example product.

---

## Field mapping across shapes

Every shape maps onto the same canonical fields. The raw label and raw value are
retained on every product so a mapping mistake is visible.

| Canonical field | `table` | `dl` | `variant-table` | `prose` |
|---|---|---|---|---|
| `sku` | Item code | SKU | Item code (per row) | `Item code:` line |
| `brand` | Brand | **Manufacturer** | — | "from X is supplied" |
| `size_code` | Size (concatenated) | Paper size + **Dimensions** | `<h1>` | "Each sheet is …" |
| `weight_gsm` | Weight | Basis weight | Paper weight | "weighs N gsm" |
| `colour_name` (shade) | **Colour** | Shade | — | "The X sheets" |
| `colour_mode` (print) | — | — | **Colour** | — |
| `finish` | Finish | Surface | `<h1>` (Gloss/Matte) | "X surface" |
| `pack_sheets` | Sheets per pack | Pack contents | header "pack of 100" | "ream of 500 sheets" |
| `list_price` | price box | price box | Price column | price box |
| `sale_price` | `<del>` in box | `<del>` in box | `<del>` in column | `<del>` in box |

`colour_name` and `colour_mode` are separate columns. Neither is inferred from
the other.

---

## Normalisation

### Weight — four published forms

| Form | Example | Pages | How |
|---|---|---|---|
| grammage | `80 gsm` | 16 | direct |
| grams per m² | `90 g/m²` (U+00B2) | 1 | direct |
| pounds + grammage | `20 lb bond (75 gsm)` | 2 | cross-checked against the table |
| pounds alone | `20 lb bond` | 2 | converted from the table |

The brief's table is the agreed specification:

```
20 lb = 75 gsm    24 lb = 90 gsm    28 lb = 105 gsm    32 lb = 120 gsm
```

Two source pages state **both** forms, so the table is cross-checked against the
site: `20 lb bond (75 gsm)` and `24 lb (90 gsm)` both agree. A disagreement
raises rather than being silently resolved.

An unlisted pound value (`26 lb`) **raises** — it is not extrapolated. Guessing
would put a number in a quote that no source supports. `28 lb` and `32 lb` are
implemented from the table but no v1 product uses them.

### Size — three spellings, one code

| Spelling | Occurrences | Note |
|---|---|---|
| `A4`, `A5`, `A3`, `US Letter`, `US Legal` | many | codes / names |
| `8.5 × 11 in` | 9 | multiplication sign is **U+00D7**, not ASCII `x` |
| `8½ × 11 in` | 2 | **U+00BD** VULGAR FRACTION ONE HALF |

Both inch spellings appear on the **same two flyer pages** — the `<h1>` says
`8.5 × 11 in` while the body prose says `8½ × 11 in`. A filter written as
`"8.5" in text` passes or fails depending on which occurrence it reads.

All spellings normalise to a code (`LTR`), and matching uses the code. An
unmappable size is **reported**, never stored as an unset value that would
become an unmatchable NULL.

### Pack size vs unit word

`pack_sheets` is the fact; `unit_word` is display text only.

`pl-cl-a4-80-pyl.html` proves why: its price box says `195.00 THB / ream` while
its own spec table says `Pack contents: 500 sheets`. The words are unreliable;
the sheet count is not. Nothing filters or compares on `unit_word`.

Where the words are read from is a branch order, not a lookup. When the price line
carries the unit — `Price: <span class='big'>289.00 THB</span> / ream` — the slash
tail wins; otherwise the unit comes from the price box's `.muted` element, which is
how `Ream of 500 sheets` is published. The tail is checked first for one reason:
on four pages the only `.muted` in the box is the note `No volume pricing for this
item.`, so reading `.muted` first stored the note as the unit (defect A16). The
fix is the order, not a check for that sentence, so the weathered copy cannot
bring it back — see `BUG.md` A16.

---

## Sale, stock, restock, discontinued

| State | Where it appears | v1 count |
|---|---|---|
| on sale | `<del>` beside the sale price | 1 (`PL-PR-LTR-GL-170-40`, 299→259) |
| out of stock | `stock-out` span + "expected back …" | 2 (`PL-PR-A4-GL-170-44`, `PL-CL-A4-100-IVY`) |
| discontinued | the word "discontinued" | 0 |
| no volume pricing | `No volume pricing for this item.` | 13 |

A sale item's tier document **does not exist**. The page carries
`data-sku='…' data-sale='1'` and the text "Not available on sale items". So
`has_volume_pricing` is derived per SKU, and a fetch is only attempted for SKUs
that actually advertise tiers.

### The sale-price trap

```html
<td><del>฿299.00</del> ฿259.00<span class='sale'>Sale</span></td>
```

The struck-through list price comes **first** in the cell. A parser taking the
first currency amount on the row quotes **299.00** — the higher, wrong price.
The extractor reads `<del>` explicitly and keeps both amounts.

### No quantity on hand — state only

The site publishes a state, never a count. There is no "45 left", no inventory
number on the page, the variant table, the category card or
`api/pricing/<sku>.json`; `stock_status` is therefore the whole of the stock
model, plus the restock date when the page supplies one.

That absence is load-bearing: **a requested quantity is never compared with
stock.** An out-of-stock SKU is refused at quantity 1 and at quantity 500 alike,
and an in-stock SKU is quoted at any quantity because there is no number to
compare against. If only 45 packs remain and a customer asks for 50, the quote is
for 50; the count is a fulfilment question the source cannot answer. Inventing
one would break the brief's no-enrichment rule and put a fabricated figure into
the pricing path.

Measured on 2026-10-28 across the seven category listing pages and all 36 product
pages: every stock claim is one of the wordings above, no claim carries a number,
and no page or card states a stock count. If a later site revision publishes a count,
that is a new field and a new decision — not a silent reinterpretation of
`stock_status`.

---

## Cross-checks that produce review rows

Both run at the end of an ingest. Neither corrects anything; both flag.

### Availability disagreement

Category cards and product pages are separate renderings of the same claim.
`category/coloured-paper/index.html` says of `PL-CL-A4-100-IVY`:

```html
<div class='muted'>pack of 250 sheets &middot; out of stock</div>
```

and the product page says `Out of stock — expected back 20 November 2026`. These
agree. When they do **not**, both values are kept and a review row records the
disagreement — neither source overwrites the other.

The card is a **secondary** source, and only recognised wording counts.
`ingest._card_stock_claim` reads `out of stock` and `discontinued`; a card that
phrases a claim another way is treated as making no claim, so the product page
stands and no disagreement is raised. Measured on 2026-10-28: 35 cards across the
seven listing pages, 34 carry only the unit line, one adds `out of stock`, and
none claims `in stock` — so the gap is not live on this site. It is carried as
accepted risk **A33** in `BUG.md` Part 3.

### Tier-document count

> The number of documents retrieved must equal the number of SKUs that advertise
> volume pricing.

On the reference site: **59 = 59**, with 105 tier rows across them. A SKU that
advertises pricing but whose document fails to fetch produces a review row, not
a silent zero.

---

## The review floor

The ladder never raises for a page-level problem. Every failure becomes a
`ReviewRow` with the URL, a reason, and a raw excerpt, and ingestion continues.

Reasons that produce a review row:

| Reason | Trigger |
|---|---|
| `unrecognised markup shape` | no known shape detected |
| `no SKU found on page` | SKU missing |
| `no price found on page` | price box unreadable |
| `size: …` | unmappable size |
| `weight: …` | unparseable or unlisted weight |
| `availability not recognised` | wording outside the known set; row is `unknown` |
| `availability_disagreement` | card contradicts page |
| `tier_document` | advertised but missing or empty |

The reference site produces **0 review rows** — every page and every SKU parses.
That is the baseline; the mutated site (Tier 2) is what exercises the floor.

`_finish()` applies the minimum-completeness rule: a product without a SKU or
without a price is a review row, not a half-populated catalog entry.

---

## The snapshot

Written to `data/catalog.duckdb` and committed, so the service runs with no
crawl.

### Choosing the file

Where the snapshot lives is resolved in one place, `catalog.resolve_db_path`, in
the order **explicit argument → `PAPERLANE_DB` → the committed path**. `ingest`,
`serve`, `eval`, `ask` and `metrics` each take `--db <path>`, and all five route
through that function, so a reader and a writer can never disagree about which
file they mean.

This exists for the re-ingest the demo round asks for. A live crawl of an unseen
site must not overwrite `data/catalog.duckdb`, because that file is what the
recorded expectations are written against — so the crawl goes to a named snapshot
and the service is pointed at it:

```bash
./run.sh ingest --base-url http://localhost:8000/paperlane/ --db data/unseen.duckdb
PAPERLANE_DB=data/unseen.duckdb ./run.sh serve
```

The committed catalog is untouched by that, which is asserted by comparing its
**bytes** rather than its size or mtime — a rewrite that preserved the length
would pass either of those. Without `--db` and without `PAPERLANE_DB` every
command resolves to `data/catalog.duckdb` exactly as before, so nothing in the
five-command demo path changed.

### Build, then swap

An ingest builds a complete new file (`.tmp.duckdb`) and only then replaces the
serving file with `os.replace`, which is atomic on one filesystem. A crawl that
dies half way through cannot damage the catalog currently answering questions —
the previous snapshot keeps serving, untouched.

```python
staged = catalog.build_snapshot(...)   # may fail; nothing served is touched
_swap_refusal(len(new_skus), len(serving_skus), accept_shrink)  # gate
catalog.swap_into_place(staged)        # atomic
```

The gate is a count, checked before the swap: a run that extracted **zero**
SKUs, or **under half** of what the serving snapshot holds, keeps the serving
catalog and exits **3**, with the staged file left on disk for inspection. A
collapse to zero is a failed parse, not a smaller catalog, and swapping it in
takes the service down until someone notices (`BUG.md` A32). A first ingest has
nothing to protect and is never refused; a genuine catalog cut passes
`--accept-shrink`. Exit codes: **0** swapped, **2** crawl failed, **3** swap
refused.

### Read-only per request

DuckDB allows many concurrent readers **or** one writer, never both, and a
connection shared across threads raises `Resource In Use Error`. So the serving
path opens a fresh read-only connection per request. Verified: 20 concurrent
readers in 0.02 s, no errors.

### Schema

| Table | Holds |
|---|---|
| `products` | one row per leaf SKU (72) |
| `price_tiers` | one row per tier (105, across 59 SKUs) |
| `review_items` | unresolved parse and cross-check failures |
| `ingest_runs` | one row per ingest, with counts and status |
| `meta` | schema version, build time, base URL |

Money columns are `BIGINT` satang: `list_price_satang`, `sale_price_satang`,
`unit_price_satang`. **There is no float column anywhere**, and the loader
raises `TypeError` if a float is passed — the check runs before the swap, so a
malformed row can never reach the serving catalog.

Every product row and every tier row carries `source_url` and `crawled_at`.

### The WAL

DuckDB writes `catalog.duckdb.wal` beside the database. Left behind, it makes
the committed snapshot incomplete, so the build checkpoints and then removes it.
`.gitignore` covers `*.duckdb.wal` as a second line of defence.

---

## Fixture-to-field mapping

`tests/fixtures/` holds one real page per shape. The mapping the tests assert:

| Fixture | Shape | Key assertions |
|---|---|---|
| `pl-cp-a4-80-eco.html` | `table` | SKU, Brand, `A4`/210×297, 80 gsm, White, Uncoated, 500, 125.00 |
| `pl-cp-a5-80.html` | `dl` | Manufacturer→brand, split size→`A5`, Shade→White, `72.00 THB` |
| `pl-cp-a4-80.html` | `prose` | brand from sentence, size from sentence, 80 gsm, 500, 129.00 |
| `pl-cp-ltr-90-nusa.html` | `prose` | `90 g/m²` (U+00B2) → 90 gsm, `LTR` |
| `flyers-ltr-gloss.html` | `variant-table` | 6 SKUs, Colour→`colour_mode`, per-row sides, sale 299→259 |
| `pl-cl-a4-100-ivy.html` | `prose` | out of stock + restock date 20 November 2026 |

Every assertion in `tests/test_extract.py` corresponds to a row above, so the
documented mapping and the tests cannot drift apart silently.

---

## Verified results

```
categories: 4
product pages: 36
leaf SKUs: 72
SKUs advertising volume pricing: 59
requests: 103
tier documents: 59
review items: 0
```

All 105 tier rows were re-checked against the raw `api/pricing/*.json`
documents: **0 mismatches**.
