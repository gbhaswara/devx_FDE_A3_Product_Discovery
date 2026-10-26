# PaperLane product discovery

A sales assistant for a paper merchant. A customer describes what they need in
their own words; the assistant finds the right products from the crawled
catalog, prices them to the satang, and writes a reply a salesperson can send.

Built for the devx AI Labs FDE take-home, assignment **A3 — Product Discovery**.

---

## 1. How to run it in five commands

From a clean checkout, in this directory:

```bash
uv sync                                    # 1. install dependencies
./run.sh test                              # 2. 682 tests, offline, no model
./run.sh serve                             # 3. the app on http://127.0.0.1:8001
./run.sh eval                              # 4. the recorded evaluation set
./run.sh diff                              # 5. snapshot vs previous snapshot
./run.sh verify-refresh                    # 6. prove the refresh path works (~55s)
```

A sixth command sits outside the five because it is a verification step rather
than part of the demo path. `verify-refresh` mutates a git-ignored copy of the
site, ingests it into a throwaway snapshot, and checks that every change it
declared in advance is reported under the correct kind. It needs no server and
no network beyond loopback.

That is the whole demo. The catalog snapshot (`data/catalog.duckdb`) is
committed, so step 3 works without crawling anything.

Step 5 reports `comparable: false` on a fresh checkout, and that is correct
rather than broken: there is no previous snapshot to compare against until you
have refreshed at least once. Run `ingest` twice and the second diff has a
baseline.

**Rebuilding the catalog from the site** takes two more commands, because the
site has to be served first:

```bash
python3 -m http.server 8000                # serve the catalog site, from THIS dir
./run.sh ingest --base-url http://localhost:8000/paperlane/
```

`ingest` crawls 103 pages at one request per second — about two minutes — then
swaps the new snapshot into place atomically. Re-running it against an unchanged
site reports `no_change: true` and commits nothing.

Serve from **this** directory, not its parent. The site lives at
`./paperlane/`, so the base URL is `/paperlane/`; serving the parent directory
puts the site at `/devx_FDE_A3_Product_Discovery/paperlane/` and the ingest fails
with `HTTP 404` on `index.html`.

**Two ports, and they are not interchangeable.** 8000 serves the *catalog site*
the crawler reads; 8001 serves the *assistant*. Binding the assistant to 8000
collides with the site. `./run.sh serve` defaults to 8001 for that reason.

**The model is optional.** With no environment variables set, every structured
case still runs and every request is still answered — by the rule-based
interpreter, which is a complete first-class path, not a stub. To enable the
model:

```bash
export PAPERLANE_LLM_BASE_URL=http://127.0.0.1:20128/v1
export PAPERLANE_LLM_API_KEY=...
export PAPERLANE_LLM_MODEL=9inference
```

No credential is committed anywhere in this repository; configuration is by
environment variable only.

---

## 2. Architecture overview

```
                    the catalog site (static HTML, 36 pages)
                                  |
                                  |  httpx + selectolax, 1 req/s, sequential
                                  v
    crawl.py  ->  extract.py  ->  normalize.py  ->  catalog.py
    fetch        4 markup          canonical          DuckDB snapshot
    + politeness shapes           vocabulary         rebuild-and-swap
                                  |
                                  v
                        data/catalog.duckdb
                                  |
              +-------------------+-------------------+
              |                   |                   |
              v                   v                   v
        aliases.py           search.py           pricing.py
        synonym &            hard filter,        pure functions,
        notation             deterministic       integer satang,
        resolution           rank, justify       Decimal, half-up
              |                   |                   |
              +-------------------+-------------------+
                                  |
                                  v
                        interpret.py  ->  assistant.py
                        rules first,      one of four outcomes:
                        model optional    quote / clarify / no match / refuse
                                  |
                                  v
                     api.py (JSON)  +  ui.py (one page, htmx)
                                  |
                                  v
                          evaluate.py (28 recorded cases)
```

Three properties hold structurally rather than by convention:

**Money never leaves Python.** Arithmetic is on integer satang; `Decimal` with
explicit `ROUND_HALF_UP` is used where a percentage is involved. There is no
float in any monetary path, and the model never computes or sees a total.

**One pricing path.** `/api/ask`, `/api/quote`, `/api/quote/lines`, the web page
and the evaluation harness all call the same `quote()`. A pricing bug cannot
appear in one entry point and not another.

**The model interprets, the code decides.** The model's only job is turning
free text into a criteria object. Its values are then re-resolved through the
same alias functions the rules use — never trusted verbatim — and re-validated
against the catalog's own vocabulary. A reply is rendered deterministically from
pricing output, so the model has no path into the numbers or the product names.

Module map:

| Module | Responsibility |
|---|---|
| `money.py` | `Money` as integer satang; `Decimal` conversion; half-up rounding |
| `pricing.py` | Tiers, sale precedence, per-order delivery, VAT. Pure functions |
| `crawl.py` | Sequential fetch at 1 req/s with retry and a page budget |
| `extract.py` | Four markup shapes → raw fields; no vocabulary decisions |
| `normalize.py` | Raw fields → catalog vocabulary (`LTR`, `90`, `Gloss`, …) |
| `catalog.py` | DuckDB build, atomic swap, health, diff, review carry-forward |
| `aliases.py` | Synonyms, trade notation (`4/4`), pound→gsm, budget phrasing |
| `criteria.py` | The typed request; `None` means "not stated", never "false" |
| `interpret.py` | Rules interpreter, model merge, validation |
| `search.py` | Hard filtering, deterministic ranking, justification |
| `assistant.py` | Four outcomes and reply rendering, with guards |
| `api.py` / `ui.py` | JSON endpoints and the single page |
| `evaluate.py` | The recorded evaluation harness |

Full detail in `docs/`: `pricing.md`, `ingestion.md`, `search.md`,
`assistant.md`, `api.md`, `refresh.md`.

---

## 3. Key decisions and trade-offs

**Python, not TypeScript.** The scored claims are arithmetic and correctness of
pricing. Python's `Decimal` and explicit integer satang make that verifiable;
JavaScript's single number type does not.

**DuckDB, not SQLite.** Superseded on every axis this assignment scores:
columnar scans over 105 price rows, native `read_only()` connections for
concurrent request handling, and a snapshot that is a single portable file.
Postgres was rejected because a server plus Docker plus credentials kills the
five-command run.

**FastAPI + htmx, not Next.js.** One process, one origin, no build step, no CORS
— which is what keeps the run instructions to five commands. Next.js adds a
build step and a second process for no scored benefit here.

**httpx + selectolax, not Scrapling.** Scrapling's dependency risk on Python 3.14
bought nothing: the site is 36 static pages with four known markup shapes.

**Rebuild-and-swap, not incremental update.** A refresh builds a complete new
snapshot and swaps it in atomically, keeping the old one as a diff baseline.
Incremental updates invite a half-written catalog; a swap is either done or not.

**Expected totals are recomputed, never transcribed.** The evaluation harness
derives every expected figure from the catalog by independent integer arithmetic
that does not call the pricing engine. Calling `quote()` to check `quote()` would
let a pricing bug agree with itself.

**The rules interpreter is a first-class path, not a fallback.** It handles the
common request shapes completely. The model's values merge *over* the rules and
are then re-validated, because the rules are guaranteed consistent with the
catalog's vocabulary and never invent a value.

---

## 4. Known limitations

Stated as limitations, not as strengths.

**Weight conversions are only partly verified.** The pound-to-grammage table
(`20→75`, `24→90`, `28→105`, `32→120`) is implemented from the brief, but only
the 20 lb and 24 lb rows can be checked against real products — the v1 catalog
stocks no 28 lb or 32 lb paper. Two of four rows are therefore untested against
live data. Cases 23 and 24 in the evaluation set are recorded as not applicable
for exactly this reason rather than being counted as passes.

**Pack-size ambiguity is surfaced, not resolved.** "Under 250 a pack" is compared
against whatever unit the product is actually sold in — a ream, a pack, a pad.
When a customer's "pack" might mean 50 sheets or 500, the reply states the basis
it used rather than guessing silently. That is honest, but it is not a
resolution.

**Semantic search is a tiebreak only.** Search is hard filtering plus
deterministic ranking. A request phrased entirely in paraphrase, with no size,
weight, category or trade term the aliases recognise, will miss. There is no
embedding layer.

**Single-turn.** No conversation memory. Each request is interpreted on its own,
so "make that 40 packs instead" is not understood as a follow-up.

**No auth and no rate limiting** beyond the crawler's own 1 req/s politeness.
The app is local-only and not hardened for exposure.

**Two behaviours are implemented but not demonstrated end to end.** Discontinued
products and prompt-injection defences are unit-tested, but the v1 catalog has no
discontinued item and no page carrying an injected instruction, so neither can be
exercised against live data. Both are marked not-run in the evaluation results.

**The reply axis of the evaluation is mostly mechanical.** It checks that a reply
exists, names no absent SKU, and carries no total it did not earn. "Would a
salesperson send this?" is a judgement the harness does not make.

---

## 5. What I would do with another week

In order, because the order is the judgement:

1. **Supplier onboarding.** Per-site parser profiles with a regression corpus per
   site, so adding a second merchant is a config file plus fixtures rather than
   new code. This is the difference between a demo and a product.
2. **Price-change monitoring.** Alert on movement beyond a threshold between
   snapshots. The diff already computes this; what is missing is the delivery
   channel and the judgement about what counts as noteworthy.
3. **A real semantic layer.** Embeddings with *measured* recall against a
   labelled set — not vibes. The current tiebreak cannot help a paraphrase-only
   request, and I would want numbers before claiming a fix.
4. **Human-in-the-loop.** Let a salesperson edit a quote, and feed the edit back
   as a labelled evaluation case. That turns every correction into a regression
   test, which is how the evaluation set should grow.
5. **A chat-channel adapter.** LINE or WhatsApp over the same tool layer. The
   assistant's outcomes are already a small closed set, so the adapter is thin.

---

## 6. How I used AI tools

I used **opencode** as the driver with the **9router** endpoint (`9inference`,
which resolves to `deepseek-v4.1-flash`), plus a spec-driven workflow of my own
(`openspec`) to keep the plan, the specs and the task list in one place.

- **Planning and analysis.** I used the model to analyse the site and the brief,
  and to draft the OpenSpec change — proposal, eight capability specs, design
  decisions and an 86-task breakdown. I reviewed and corrected all of it; the
  scope verdict in `CHANGELOG.md` is my own, and it disagrees with the plan's own
  estimate.
- **Implementation.** The code was written with heavy model assistance, module by
  module, against the specs. Every module has tests I ran and read.
- **Finding defects.** This is where it earned its place. Running the evaluation
  set against the *live* model found a real defect that the test suite had
  hidden — a clarification branch that was dead in production because tests
  passed an argument the API never supplied, and a colour ambiguity that only the
  model's own phrasing triggered. I would not have found either by reading. Six
  real defects in total are recorded in `CHANGELOG.md`, each with *how* it was
  found rather than only what changed.
- **What I did not delegate.** The pricing arithmetic, the evaluation design and
  the decision about what the four axes should mean. Those are the parts the
  assignment is actually scoring, and they needed to be mine.

The model is also a runtime component: it interprets free text when configured.
It never computes a price, never selects a product, and never writes a total into
a reply — those are deterministic code paths with their own tests.

---

## 7. Where the evidence is

| Claim | Where to check |
|---|---|
| Prices are correct to the satang | `tests/test_pricing.py` (49 tests), `docs/pricing.md` |
| The evaluation passes | `./run.sh eval`, and `eval/results.md` for the full run |
| The evaluation *can* fail | `./run.sh eval --cases eval/negative-control.json` |
| The scoring detects what it claims | `./run.sh eval --self-check` |
| The crawler is faithful | `./run.sh diff`, `tests/test_extract.py`, `docs/ingestion.md` |
| The documented API is real | `tests/test_api.py::TestDocumentedExamples` executes every example |
| No credential is committed | `.gitignore`; `./run.sh test` includes a scan |

---

## Scope note: two tiers

This submission is deliberately split into two tiers, and both are named here
rather than blurred.

**Tier 1 — the core, and what the assignment is actually scoring:** the crawler
and snapshot, the normalisation layer, the pricing engine, search and
interpretation, the four assistant outcomes, the JSON API, and the evaluation
harness with its results. Everything in sections 1–7 above. **Complete** — 80 of
86 tasks closed, and every open task is Tier 2.

**Tier 2 — extras, each independently droppable.** Six were planned. Four are
built; two are not:

| Item | State |
|---|---|
| Multi-item basket quoting | Built — `POST /api/quote/lines`, evaluation cases 16 and 27 |
| Single-page interface | Built — `ui.py`, all four outcomes rendered |
| Snapshot diff as a demo artefact | Built — `GET /api/diff`, `./run.sh diff` |
| Mutated-site refresh demonstration | Built — `./run.sh verify-refresh` mutates a copy of the site, ingests it, and verifies all 12 injected changes are reported under the correct kind |
| Hybrid semantic tiebreak | **Not built** — search is hard filtering plus deterministic ranking, with no embedding layer |
| Structured logging and the five metrics | **Not built** — no logging or metrics module |

### On the six-hour estimate

The brief estimates roughly six hours. The measured figure, from filesystem
mtimes, is **4h15m from reading the briefs to a complete submission** — 1h58m of
planning and 2h02m of building.

My planning notes predicted the build alone would take 15–20 hours. **That
prediction was wrong by about 8×**, and the error is worth stating rather than
quietly dropping: it assumed Tier 1 would be built by hand from scratch, when in
fact it was built against a specification precise enough (65 requirements, 132
scenarios, every task carrying its own verification) that most of the work was
transcription. `CHANGELOG.md` records the prediction, the measurement, and why
they diverged.

The wall-clock figure is not a claim of six hours of focused effort — it includes
idle time and every model round-trip. It does establish that the scope did not
need trimming to fit the brief.

