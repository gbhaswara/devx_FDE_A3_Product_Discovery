# Proposal

## Why

PaperLane's sales team answers the same ~30 catalog questions by hand — which paper suits a job, what it costs at the quantity asked for, whether it is in stock — and quoting the wrong price costs them money. The catalog is a static website with no search or quoting facility, and its prices are volume-tiered per item, so a correct answer depends on the *quantity asked for*, not the list price.

We are building a sales assistant over that site: it reads the live catalog, decides every price in deterministic code so the numbers cannot drift, and refuses to guess when nothing fits. This is the devx AI Labs A3 take-home; the analysis behind these decisions is in `ANALYZE_01.md`.

## What Changes

Everything below is new — this is a greenfield build. The deliverable is a self-contained service in `devx_FDE_A3_Product_Discovery/`, keeping the brief PDF and the extracted `paperlane/` site as read-only inputs beside it.

- **Ingestion** — crawl the catalog over HTTP at 1 req/s, parse four distinct markup shapes through a fallback ladder, normalise size/weight/colour/pack-size into a queryable store, and record provenance (source URL + crawl time) on every row.
- **Deterministic pricing** — a pure function layer implementing PR1–PR8: volume tiers per leaf SKU, sale-beats-tiers, flat delivery per order, 7% VAT on subtotal *plus* delivery, and budget comparison at the requested quantity. Money is integer satang end-to-end; the model never computes or states a price.
- **Search** — hard constraints as filters with explicit absent-attribute semantics, soft wishes as a deterministic ranking, an alias layer (`letter`/`8.5x11`/`4/4`/`cmyk`/`duplex`), and machine-readable `match_reasons` emitted by the filter layer that already ran.
- **Assistant** — parse a request into validated criteria, then reply with matching products, why they match, and a full price breakdown. Clarifies when a hard constraint is missing and the answer would change; returns closest alternatives when nothing matches; refuses out-of-stock and discontinued items. The model emits criteria only, never SKUs or prices, so "no invented products" is structural rather than a request.
- **API** — `POST /chat`, `POST /quote`, `GET /products`, `GET /health`, `GET /diff`, with a four-value status enum (`ok`/`clarify`/`no_match`/`refused`) that makes each must-have testable, and an error contract under which an unreachable LLM degrades to `clarify` instead of failing a quote.
- **Refresh** — rebuild-and-swap into a new DuckDB snapshot and emit a diff report (added / discontinued / price / stock / parse-failure) so re-ingesting an updated site needs no code changes.
- **Evaluation** — 28 recorded cases with expected SKUs and expected totals, scored on four axes, with failures kept in the results table.
- **Observability** — structured per-request logs and five production metrics (LLM fallback rate, zero-result rate, `NEEDS_REVIEW` count, p95 latency, quote/answer mismatch).

Two tiers are deliberate, per `ANALYZE_01.md` §0a. The brief plans ~6 hours and scores scope judgment, so:

- **Tier 1 (the six-hour core):** ingestion, pricing, search, assistant, API, refresh, evaluation, README + customer summary. This is a complete submission on its own.
- **Tier 2 (chosen extras, each separable):** hybrid semantic tiebreak, multi-item baskets, the diff report as a demo artifact, the htmx UI, an own mutated v2 site for stress-testing, LLM-vs-rule parser comparison, and the metrics layer.

Specs describe the full intended system. `tasks.md` orders Tier 1 first behind a hard gate, then Tier 2 in independently droppable blocks.

No breaking changes — there is no existing implementation to break.

## Capabilities

### New Capabilities

- `catalog-ingestion`: turning the live site into a normalised, provenance-stamped catalog — crawling within the rate limit, the four-shape extraction ladder with a `NEEDS_REVIEW` floor, field normalisation (size codes, four weight formats, colour shade vs print mode, pack size), and the snapshot store.
- `pricing-engine`: the pure, deterministic money layer — tier selection per leaf SKU, sale precedence, per-order delivery, VAT on subtotal plus delivery, budget comparison at the requested quantity, and integer-satang arithmetic with explicit half-up rounding.
- `product-search`: turning validated criteria into a ranked candidate set — hard-constraint filter semantics (including absent attributes), deterministic soft ranking, the alias/synonym layer, and `match_reasons` generation.
- `sales-assistant`: the conversational contract — criteria parsing with rule fallback, the reply contract (matches, why they match, price breakdown), clarify/no-match/refuse decision rules, closest-alternatives ordering, and the no-invented-products invariant.
- `quote-api`: the externally observable HTTP surface — endpoint set, request/response shapes, the status enum, and the error contract including LLM-unavailable degradation.
- `catalog-refresh`: re-ingesting an updated site without code changes — rebuild-and-swap snapshots, the diff report, and the review floor that prevents a page from silently disappearing.
- `evaluation-harness`: the recorded test set and its results — expected SKUs and totals per case, four-axis scoring, and retention of failing cases.
- `observability`: structured request logging and the production metrics that indicate silent quality degradation.

### Modified Capabilities

None — the project has no existing specs.

## Impact

- **New code:** `devx_FDE_A3_Product_Discovery/` gains a Python package (`src/paperlane/`), `tests/`, `eval/`, `run.sh`, `pyproject.toml`, `README.md`, and `CUSTOMER_SUMMARY.md`. Nothing outside this folder is modified; `paperlane/` and the brief PDF stay read-only inputs.
- **Dependencies (new):** `duckdb`, `fastapi`, `uvicorn`, `httpx`, `selectolax`, `pydantic`, `pytest`. All pure-Python wheels on Python 3.14; nothing compiles. No pandas, numpy, ORM, or Scrapling.
- **External services:** an OpenAI-compatible LLM endpoint (9router, model `9inference`) via environment variable only. The system must remain functional — degraded to `clarify` — when that endpoint is unreachable.
- **Data:** a committed `catalog.duckdb` snapshot plus the ability to rebuild it from the site. 72 leaf SKUs across 36 product pages and 59 pricing JSON files.
- **Rate limit:** the site permits max 2 req/s; the crawler runs at 1 req/s, so a full ingest is ~105 requests / ~105 seconds.
- **Repo:** the submission needs its own git repository with no API keys committed. `DEVXLABS` is now a git repository with remote `origin` configured (0 commits at the time of writing); a `.gitignore` must be added before the first commit.
