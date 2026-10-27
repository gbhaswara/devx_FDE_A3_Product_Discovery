# API

Six endpoints. Every example below is a real response captured from the running
service against the committed snapshot, and **every one is executed by a test** in
`tests/test_api.py::TestDocumentedExamples`. A documented example that has never
been run is a guess; these are the same requests the tests issue.

Base URL in development: `http://127.0.0.1:8001`.

Port 8001, not 8000, and the distinction is not cosmetic: **8000 serves the
catalog site** the crawler reads, **8001 serves the assistant**. Binding the
assistant to 8000 collides with the site. `./run.sh serve` defaults to 8001 for
that reason; see `docs/refresh.md` for running both at once.

```
GET  /                    the single page
POST /ask                 the same page's fragment endpoint (HTML)
POST /api/ask             free text in  → reply + interpretation + candidates + figures
POST /api/quote           structured in → candidates + figures (no model)
POST /api/quote/lines     several SKUs   → one order, one delivery charge
GET  /api/products        the normalised catalog, filterable
GET  /api/health          snapshot name, counts, model state
GET  /api/diff            staged snapshot vs serving snapshot
```

---

## The response envelope

Every `/api/*` response is a JSON object. Successful ones share these keys:

| Key | Present when | Meaning |
|---|---|---|
| `outcome` | always on quote/ask | one of the four outcomes below |
| `reply` | `/api/ask` | the rendered text, ready to show a person |
| `criteria` | quote/ask | the interpreted requirements — the audit trail |
| `candidates` | quote/ask | what was considered, with per-product justification |
| `figures` | `quoted` only | the full breakdown |
| `questions` | `clarified` only | what the assistant needs to know |
| `alternatives` | `no_match` with a relaxation | close items, labelled as non-matches |
| `refused` | `refused` only | the items that cannot be supplied |
| `relaxed` | `no_match` with a relaxation | which requirement was dropped |
| `errors` | when a self-check fails | guard violations, see G1–G3 in `assistant.md` |
| `warnings` | when a guard is suspicious | non-fatal guard notes |
| `meta` | `/api/ask`, `/api/quote` | interpretation path, elapsed ms, snapshot identity |

`meta.snapshot` always names the file and counts the answer was computed against,
so a surprising number can be traced to a stale snapshot rather than argued about.

---

## The four outcomes

A caller branches on `outcome`; it never has to parse prose.

| `outcome` | Means | Required fields |
|---|---|---|
| `quoted` | items satisfy every requirement and are available | `reply`, `candidates`, `figures` |
| `clarified` | a detail is needed and its answer would change the result | `reply`, `questions` |
| `no_match` | nothing satisfies every requirement | `reply` |
| `refused` | items match but none can be ordered today | `reply`, `refused` |

The requirement set is declared in code as `OUTCOME_REQUIRED_FIELDS` and enforced
by `check_outcome_contract()`. It also rejects an outcome that carries a price it
did not earn — a `no_match` with `figures` is a defect, not a nuance.

---

## `POST /api/ask`

Free text in. The model, if configured, interprets; otherwise the rules do. Both
paths answer.

**Request**

```json
{ "request": "A4 copy paper, 80 gsm, 20 reams", "use_model": false }
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `request` | string | required | 1–2000 chars, must not be blank |
| `quantity` | integer | null | 1–100000, overrides a quantity found in the text |
| `use_model` | boolean | `true` | `false` guarantees no network call |

**`quoted` response** (abridged to one candidate; the real one lists three)

```json
{
  "outcome": "quoted",
  "candidates": [
    {
      "sku": "PL-CP-A4-80-NUSA",
      "name": "Nusa Paper Copy A4 80gsm",
      "size": "A4",
      "weight_gsm": 80,
      "pack_sheets": 500,
      "unit_price": "117.00",
      "quantity": 20,
      "line_total": "2,340.00",
      "discount": "10+ tier (list 121.50)",
      "available": true,
      "stock_status": "in_stock",
      "back_in_stock_date": null,
      "match_reasons": [
        { "attribute": "category", "requested": "Copy paper", "actual": "Copy paper" },
        { "attribute": "size", "requested": "A4", "actual": "A4" },
        { "attribute": "weight", "requested": "80 gsm", "actual": "80 gsm" }
      ]
    }
  ],
  "figures": {
    "subtotal": "2,340.00",
    "delivery": "150.00",
    "vat": "174.30",
    "total": "2,664.30",
    "vat_rate": "7",
    "lines": [
      {
        "sku": "PL-CP-A4-80-NUSA",
        "quantity": 20,
        "unit_price": "117.00",
        "line_total": "2,340.00",
        "discount": "10+ tier (list 121.50)"
      }
    ]
  },
  "criteria": { "category": "Copy paper", "size": "A4", "weight_gsm": 80, "quantity": 20 },
  "meta": {
    "interpretation": "rules",
    "elapsed_ms": 44.8,
    "snapshot": {
      "path": "…/data/catalog.duckdb",
      "products": 72,
      "price_tiers": 105,
      "built_at": "2026-10-26 14:22:45.965504",
      "base_url": "http://localhost:8000/paperlane/",
      "freshness": {
        "built_at": "2026-10-26 14:22:45.965504",
        "age_seconds": 12884.5,
        "age_human": "3h",
        "stale_after_hours": 24.0,
        "stale": false
      }
    },
    "interpretation_detail": "no model client supplied"
  }
}
```

Note `unit_price` is `117.00`, not the list price `121.50`: the 10+ tier applies
at quantity 20. `discount` names which price was used and what the list price was,
so the two can be checked against each other.

`meta.interpretation` is `rules`, `model`, or `mixed`. It is disclosure, not
decoration: it says whether a model read the request. When the model is configured
but unreachable it still says `rules`, with the reason in
`interpretation_detail`.

### `clarified`

```json
{
  "outcome": "clarified",
  "candidates": [],
  "questions": [
    {
      "field": "colour",
      "question": "When you say colour, do you mean the paper's own colour (such as white or ivory), or the colour of printing on it?"
    }
  ],
  "reply": "So far I have: category Coloured paper, colour_mode Full colour (CMYK).\nWhen you say colour, do you mean the paper's own colour (such as white or ivory), or the colour of printing on it?",
  "criteria": { "category": "Coloured paper", "colour_mode": "Full colour (CMYK)" }
}
```

A clarification is only asked when the detail is **needed**, **absent**,
**uninferable** and **answer-changing**. At most two are asked at once.

### `no_match`

```json
{
  "outcome": "no_match",
  "candidates": [],
  "relaxed": "weight",
  "alternatives": [
    {
      "sku": "PL-CP-A5-80",
      "name": "PaperLane Essentials A5 80gsm",
      "unit_price": "72.00",
      "quantity": 1,
      "line_total": "72.00",
      "discount": "list price",
      "match_reasons": []
    }
  ],
  "reply": "Nothing in the catalog satisfies every requirement you gave.\nIf you could relax the weight, these are the closest options — they do not match your original request:\n  PaperLane Essentials A5 80gsm (PL-CP-A5-80) — 72.00 per pack of 500 sheets [relaxed: the weight]"
}
```

`candidates` is empty and `relaxed` names what was dropped. Alternatives are never
presented as matches; note their `match_reasons` are empty, because they matched
nothing. There is no `figures` key: nothing was priced.

### `refused`

```json
{
  "outcome": "refused",
  "candidates": [
    {
      "sku": "PL-CL-A4-100-IVY",
      "name": "Heritage Ivory A4 100gsm",
      "unit_price": "168.00",
      "available": false,
      "stock_status": "out_of_stock",
      "back_in_stock_date": "20 November 2026",
      "match_reasons": [
        { "attribute": "size", "requested": "A4", "actual": "A4" },
        { "attribute": "colour (paper shade)", "requested": "ivory", "actual": "ivory" }
      ]
    }
  ],
  "refused": [ { "sku": "PL-CL-A4-100-IVY", "…": "same object" } ],
  "reply": "Heritage Ivory A4 100gsm (PL-CL-A4-100-IVY) is out of stock, so I cannot quote it as a purchase today. It is expected back 20 November 2026.\nI have not quoted it, because I can only price items you can actually order."
}
```

A refusal is not the same as a non-match: the product exists and matches, it just
cannot be bought. It carries no `figures` — no price is given for something the
customer cannot order — and the reply says so explicitly.

---

## `POST /api/quote`

Structured requirements. **No model is ever consulted**, so this endpoint is
reproducible byte for byte.

```json
{
  "category": "Flyer printing",
  "size": "LTR",
  "sides": "double",
  "colour_mode": "Full colour (CMYK)",
  "quantity": 5
}
```

| Field | Accepted values |
|---|---|
| `category` | `Copy paper`, `Coloured paper`, `Card and photo paper`, `Flyer printing` (case-insensitive; aliases resolved) |
| `size` | `A3`, `A4`, `A5`, `LTR`, `LGL`, or `letter`/`legal`/dimensions |
| `weight_gsm` / `_min` / `_max` | 1–1000 |
| `colour_shade` | paper colour, e.g. `ivory` |
| `colour_mode` | `Full colour (CMYK)`, `Black and white` |
| `finish` | `Gloss`, `Matte`, `Uncoated`, `Laid`, `Smooth` |
| `sides` | `single`/`double` or `one-sided`/`two-sided` |
| `quantity` | 1–100000, default 1 |
| `budget_per_unit` | decimal baht; compared at the requested quantity |
| `budget_basis` | free text, default `per pack, before VAT`; a basis containing `including VAT` compares against the VAT-inclusive price (PR7) |

Vocabulary is **resolved, not trusted**. `"size": "letter"` and `"size": "LTR"`
reach the same product, because the two entry points must not disagree about the
same request. A value the catalog cannot express is a `422`, never a silent
filter drop.

`meta.interpretation` is always `"structured"` here.

---

## `POST /api/quote/lines`

Price several known SKUs as one order, so delivery and VAT are computed once.

```json
{
  "lines": [
    { "sku": "PL-CP-A4-80", "quantity": 20 },
    { "sku": "PL-PR-A4-MT-100-10", "quantity": 5 }
  ]
}
```

Response is `{ "outcome": "quoted", "figures": {...}, "meta": {...} }` with
`figures.delivery` charged **once per order**, against the combined pre-tax
subtotal. On this basket the subtotal is 3,010.30, which clears the 3,000.00
threshold, so delivery is `0.00` and the total is `3,221.02`.

Charging delivery per line was measured at `3,542.02` on this exact basket —
321.00 too high — which is why the threshold is tested against the aggregate, not
per line.

An unknown SKU is a `422` naming it:

```json
{ "error": "invalid_request", "detail": "unknown SKU(s): PL-FAKE-1", "field": "lines" }
```

---

## `GET /api/products`

The normalised catalog.

| Query | Type | Default |
|---|---|---|
| `size` | string | — |
| `category` | string | — |
| `weight_min` / `weight_max` | integer | — |
| `in_stock_only` | boolean | `false` |
| `limit` | integer | `200` (max 1000) |

Returns `{ "count", "returned", "products": [...] }`, where `count` is the number
matching before `limit` is applied. 72 products in the committed snapshot, 70 in
stock.

---

## `GET /api/health`

```json
{
  "snapshot_present": true,
  "path": "…/data/catalog.duckdb",
  "products": 72,
  "price_tiers": 105,
  "catalog_readable": true,
  "healthy": true,
  "model_configured": false,
  "model_reachable": false,
  "freshness": {
    "built_at": "2026-10-26 14:22:45.965504",
    "age_seconds": 12884.5,
    "age_human": "3h",
    "stale_after_hours": 24.0,
    "stale": false
  }
}
```

Always `200` — a health check answers even when the thing it reports on is
missing. With no snapshot it returns `healthy: false` **and a `remedy`** naming the
command that builds one, because a diagnosis without a remedy is a dead end.

`freshness.stale` is a **report**, not a gate: with the threshold crossed, every
endpoint still answers. The threshold is 24 hours by default and
`PAPERLANE_STALE_AFTER_HOURS` overrides it. An unreadable or missing snapshot
reports `age_seconds: null` rather than `false`, so "cannot tell" does not read as
"fresh".

---

## `GET /api/diff`

Compares the staged snapshot against the serving one.

```json
{
  "comparable": false,
  "reason": "no new snapshot to compare",
  "added": [], "withdrawn": [], "price_changed": [],
  "availability_changed": [], "tier_changed": [], "parse_failed": []
}
```

`comparable: false` with a `reason` distinguishes *"nothing changed"* from
*"nothing to compare against"*. They are different answers and only one of them is
reassuring.

---

## Errors

Two status families, and the shapes are deliberately identical so a caller
parses one format.

### Client errors — `422`

```json
{ "error": "invalid_request", "detail": "B5 is a paper size this catalog does not stock", "field": "size" }
```

Framework validation errors are normalised onto this same shape, with the full
list under `issues`:

```json
{
  "error": "invalid_request",
  "detail": "Field required",
  "field": "request",
  "issues": [ { "field": "request", "detail": "Field required" } ]
}
```

No stack trace, no file path, no framework internals ever appear in a response.
That is asserted directly by `test_no_stack_trace_is_exposed`.

### Missing snapshot — `503`

```json
{
  "error": "no_snapshot",
  "detail": "No catalog snapshot at /tmp/…/nope.duckdb. Build one with: ./run.sh ingest --base-url http://localhost:8000/paperlane/",
  "snapshot_path": "/tmp/…/nope.duckdb",
  "remedy": "./run.sh ingest --base-url http://localhost:8000/paperlane/"
}
```

A missing snapshot is not the caller's mistake, so it is not a `4xx`; and it is
not an unexplained `404` either, because "not found" without a remedy is a dead
end.

### Model outage — not an error at all

A model outage degrades the *answer*, never the service. The rule interpreter
answers and `meta.interpretation` reports `rules`. There is no status code for
"the model was down", because it never changes the status. Asserted by
`TestModelDegradation::test_an_unreachable_model_still_answers`, which points the
client at a dead port and expects a normal `quoted` response.

---

## The page endpoints

`GET /` serves the single page. `POST /ask` is the form target htmx posts to; it
returns an HTML fragment, not JSON, because the two have different obligations —
the JSON endpoint must expose structure for a harness, the fragment must render
something a person can read.

The fragment escapes everything: reply text contains crawled product names, which
are untrusted input. The page never interprets them as markup.
