# MVC_PLAN.md — a minimum viable complete plan for A3

A scoping plan for the **devx AI Labs FDE take-home, A3 Product Discovery**, written
against `devx_FDE_A3_Product_Discovery/devx_FDE_A3_Brief.pdf`.

**MVC here means "minimum viable complete"** — the smallest system that still
produces evidence on every axis the brief scores. It does not mean
Model-View-Controller.

**This document is not a description of the repository next to it.** The submission
in `devx_FDE_A3_Product_Discovery/` is the full build: 11,043 lines of source, 9,986
lines of tests, 28 evaluation cases, six Tier 2 extras. This is the plan for a
deliberately smaller version — roughly 1,760 lines of source — and it is here
because the *reasoning* about what to cut is the transferable part.

---

## 1. The objective function

The brief states it twice, and both sentences do more scope-cutting than any
architectural argument:

> "A harder assignment earns no extra points; an excellent A1 beats an average A3."

> "We care more about evidence that your system works, and honesty about where it
> does not, than about polish."

So the thing being maximised is **evidence per hour**, not features per hour. Every
decision below follows from that. It is why the plan is ~1,760 lines and not 11,000,
and why "we built less, and here is what we proved" is a defensible position rather
than an apology.

The brief also gives a hard number: **"Plan for about 6 hours of focused work.
Please do not spend much more; good judgment about scope is part of what we look
at."** Overrunning is itself a scored failure. The budget below treats 6 hours as a
ceiling, not a target.

---

## 2. What ships

| Layer | Choice | Est. size |
|---|---|---|
| Crawl | `httpx` + `selectolax` (`LexborHTMLParser`), 2 req/s, 103 requests ≈ 52 s floor; measured 102.6 s at the default 1 req/s | ~150 lines |
| Store | One DuckDB file, three tables: `products`, `price_tiers`, `review_items` | ~120 lines |
| Pricing | Integer satang + `Decimal` with `ROUND_HALF_UP` | ~200 lines |
| Interpret | Rules parser first; model as an optional upgrade behind env vars | ~250 + 150 lines |
| Search | Hard filters, then deterministic ranking. No embeddings | ~200 lines |
| Reply | Rendered by code from pricing output. The model never writes it | ~200 lines |
| API + page | FastAPI on `:8001`; one static HTML page with `fetch()` | ~150 + 40 lines |
| Eval | 12 cases as JSON fixtures, results as Markdown | ~300 lines |

Roughly **1,760 lines of source, 800 of tests.**

### The five commands

The brief asks for "how to run it in 5 commands or fewer". Five, exactly:

```bash
uv sync                       # 1. dependencies
./run.sh ingest               # 2. crawl the site into a snapshot (~100s at 1 req/s)
./run.sh ask "letter-size flyers, one side, colour, under 250 a pack, 20 packs"
                              # 3. the brief's own example, answered
./run.sh eval                 # 4. the 12 recorded cases
./run.sh serve                # 5. optional page on http://127.0.0.1:8001
```

Command 2 requires the catalog site to be served first, which is why `ingest`
defaults to `http://localhost:8000/paperlane/` and says so when it fails — a
sixth command the user does not have to type.

`ask` is a **new** subcommand in this plan. The full build has only `ingest`,
`serve`, `eval` and `diff`; there is no CLI path to ask a question, so a demo
depends on `curl` or the browser. Adding `ask` costs ~30 lines and is worth it:
the brief permits "a simple UI **or** CLI", and a one-line CLI question is the
shortest possible proof that the thing works.

---

## 3. What does not ship, and what licenses each cut

A cut is only safe if it removes no evidence from a scored axis. Each row cites the
sentence that permits it.

| Cut | Licensed by | Cost of cutting |
|---|---|---|
| Embeddings / hybrid search | *Nice to have* | Paraphrase-only requests miss. State it as a limitation |
| Multi-item baskets | *Nice to have* | One product per request |
| Conversation memory | *Nice to have* | Single-turn. State it; the brief scores honesty |
| Metrics / observability | *Nice to have* | Keep **one log line per request** (~5 lines). That is the cheap 80% |
| Mutated-site harness, snapshot diff | Not required | The refresh rehearsal (Step 10, §5) covers the scored need |
| htmx / Next.js | *"a simple UI or CLI"* | Next.js adds a build step, a second process, CORS, and eats the 5-command budget |
| 28 eval cases | *"at least 10"* | 12 cases cover every must-have and every pricing rule |

Two of these deserve a sentence more than a row.

**Metrics stay as one log line, not a module.** The brief lists "logging and metrics
you would watch in production" as nice-to-have. A full observability layer is 1,176
lines in the full build (`records.py` + `metrics.py`) — far too much for this
budget. But a single structured line per request, with outcome and elapsed ms,
costs almost nothing and makes the *conversation about production* possible. Cut the
layer, keep the signal.

**The page is worth 40 lines even though the CLI would satisfy the brief.** The
demo round is a role-played call with a *salesperson*, and the axis being scored is
"replies a salesperson would be proud to send". A chat-shaped page sells that in a
way a terminal cannot. Forty lines, and it targets a scored axis directly.

---

## 4. The hour budget

| Window | Work | Checkpoint — what must be true |
|---|---|---|
| 0:00–0:40 | Recon: crawl by hand, map markup shapes, **find the tier JSON** | You know the data model before writing it |
| 0:40–1:30 | Schema + crawler + extractor | `ingest` reports 72 products, 105 tier rows, 0 review items |
| 1:30–2:15 | Pricing engine + unit tests | ~30 tests green; half-up rounding proven with a failing-then-passing case |
| 2:15–3:00 | Rules interpreter + criteria validation | **End-to-end system works with no model at all** |
| 3:00–3:45 | Filter/rank + four outcomes + reply | The brief's own example quotes correctly |
| 3:45–4:15 | API + static page | Demo path complete |
| 4:15–5:00 | 12 eval cases + `eval/results.md` | 12/12, or honest recorded failures |
| 5:00–5:30 | Model path behind env vars | Rules path still passes with the model off |
| 5:30–6:00 | README, customer summary, honesty pass | Five commands, counted, not estimated |

**This table is a prediction, and predictions of this kind have a bad record here.**
The full build's planning notes predicted 15–20 hours for the build and it took
2h02m; end to end, 4h15m from reading the briefs to a complete submission. The
estimate was wrong by roughly 8×, in the *safe* direction.

So treat the windows as an ordering, not a schedule. The ordering is the part that
was right, and the ordering is what this document is actually arguing for. If the
whole thing takes three hours, the order still holds. If recon overruns to 1h30m,
cut from the tail — the eval cases, not the pricing tests.

---

## 5. The logic, step by step

### Step 1 — Start from the scored axes, not the feature list

The brief names the axes explicitly: technical correctness, problem solving and
judgment, engineering quality, AI and data evaluation, communication, business and
pre-sales thinking, ownership. Features do not appear on that list; evidence does.

This is why §3 is a table of citations rather than a list of opinions. "I cut
embeddings" is a judgement call. "I cut embeddings because the brief files them
under nice-to-have and they add a provider dependency that can fail during your live
demo" is engineering.

### Step 2 — Test every must-have against an axis; that is what "Complete" means

| Must-have (brief) | Axis it feeds | Cuttable? |
|---|---|---|
| 1. Ingestion with provenance (URL + time) | Data | No — nothing works without it |
| 2. Defensible schema | Data | No — it *is* the data axis |
| 3. Assistant: criteria → tools → products, why, breakdown | Agent design, Business sense | No |
| 4. Pricing by deterministic code, never the model | Correctness | No — "to the satang" |
| 5. Clarify / no-match + alternatives / no invention | Business sense | No |
| 6. API and a UI **or** CLI | delivery | No — but CLI alone is permitted |
| 7. ≥10 requests with expected products and totals, plus results | AI and data evaluation | No |
| 8. Refresh without code changes | live demo round | No |

All eight stay. The scope reduction comes from the nice-to-haves and the *depth* of
each must-have, not from dropping any of them. That is the definition of minimum
viable **complete** — and it is why the cut list in §3 contains nothing from this
table.

### Step 3 — Find the load-bearing must-have

Must-have #4 (correct pricing) depends on #1 (ingestion) having captured **volume
tiers**. So one question decides the whole architecture:

> Are volume prices in the HTML?

Measured against the real site:

```
Tier data present in the initial HTML:   0 matches for "10+" / "50+" / "100+"
data-sku hooks on one product page:      6
paperlane/assets/tiers.js:               fetch(root + 'api/pricing/' + sku + '.json')
Tier JSON documents on disk:             59
Example: paperlane/api/pricing/PL-PR-LTR-MT-100-40.json
  {"sku": "...", "unit": "pack", "vat_included": false,
   "tiers": [{"min_qty": 5, "unit_price": 211.5},
             {"min_qty": 20, "unit_price": 198.0}], "updated": "2026-10-01"}
```

**They are not in the HTML.** They arrive as 59 separate documents, fetched by
JavaScript driven by `data-sku` attributes on the page.

The brief warns about exactly this, twice:

> "Treat it like a real website and inspect it carefully; not all content is in the
> initial HTML."

> "Complete, correctly typed records, including what is hidden in variants or loaded
> by script."

A naive HTML-only crawler captures every list price, loses every volume price, and
**fails silently**. The eval still runs, totals are still produced, and they are
wrong by the discount. A plausible wrong number is worse than a crash, because
nobody investigates it.

This is why recon is the first 40 minutes and why the crawl is 103 requests rather
than 36 pages. The 103 decomposes exactly, which is how you know the crawl is
complete rather than merely finished:

```
index.html                1
category pages            7
product pages            36
tier documents           59
                        ---
                        103   ← matches ingest_runs.pages_fetched
```

Note what is *not* in that list: `delivery.html`. It is a static policy page with no
SKUs on it, so the crawl never fetches it. That is a deliberate exclusion, and it is
the kind of thing worth being able to say out loud — 103 is not "all the files", it
is "everything with product data on it".

### Step 4 — That one fact forces the schema

Tier documents carry `min_qty` + `unit_price` rows per SKU. That cannot be a column
on `products`. It is a table:

```
products       72 rows   ← one per SKU; provenance: source_url, crawled_at
price_tiers   105 rows   ← (sku, min_qty, unit_price_satang)
review_items    0 rows   ← anything unparseable: url, reason, raw_excerpt
```

Three details that are cheap now and expensive later:

- **`review_items` is the insurance policy.** When the *updated* site arrives in the
  demo round with markup you have never seen, the parser must not crash and must not
  guess. It records the URL, the reason, and the raw excerpt. The ingest report then
  says `72 products, 105 tier rows, 0 open review items` — and if those counts move,
  it is visible in the output rather than discovered in a quote.
- **Provenance is must-have #1 verbatim** — "source URL and time" — so both columns
  are `NOT NULL` and that is asserted by a test, not by intention.
- **`ingest_runs` records what the crawl actually did**: `pages_fetched`,
  `skus_found`, `tier_docs_found`, `status`. The full build's committed snapshot
  shows `103, 72, 59, ok` — that row is the difference between "I crawled the site"
  and "here is what the crawl found".

### Step 5 — Pricing must be integer satang; here is the forcing function

Two rules make floating point unacceptable:

> **PR5:** "VAT = 7% of (subtotal + delivery), rounded half-up to 2 decimals."

> **PR6:** "When a customer gives a maximum price per pack, compare it with the unit
> price they would pay at the requested quantity, before VAT."

PR5 names the rounding mode. Python's built-in `round()` is banker's rounding —
`round(2.5) == 2`, `round(0.5) == 0`. Over many orders that produces one-satang
errors, and the brief says "to the satang". So: **integer satang everywhere**,
`Decimal` + `ROUND_HALF_UP` at the single point where a fraction appears.

PR6 forces an ordering constraint that is easy to invert: the budget is compared
against the **tier price at the requested quantity**, not the list price. "Under 250
a pack, 20 packs" is tested at the 20+ tier (198.00), not at list (225.00). Get it
backwards and you reject products that qualify — a silent, plausible failure of
exactly the kind Step 3 was about.

Worth its own test, with a case where banker's rounding and half-up disagree. If no
such case exists in the catalog, construct one in the pricing tests — the engine is
where the claim lives, so the engine is where it must be proven.

### Step 6 — The agent design is one sentence; take it literally

> "the model decides intent, code decides facts and prices"

So the model has **one** job: free text → a criteria object. It does not filter,
rank, price, or write the reply. Everything downstream is code.

Why that is the correct design and not a shortcut:

- **A hallucinated total is structurally impossible.** The model never emits a number
  that reaches a customer, because the reply is rendered from pricing output.
- It is the cheapest thing that satisfies must-have #3, where "validated" means the
  model's values are re-resolved through the catalog's own alias functions. An
  invented size is *dropped*, not trusted.
- It collapses the debugging surface. When a case fails you know whether intent
  (model) or facts (code) was at fault, because the two never mix.

And the sequencing, which is the single most valuable decision in this plan:

> **Build the rules interpreter first. It is a complete path, not a stub.**

That yields a working end-to-end system at hour 3:00. The model then becomes an
*upgrade* rather than a *dependency*. If model integration is still failing at 5:30,
there is a demo; if the endpoint is slow, rate-limited, or returns `content: null`,
there is a demo. This is invisible when things go well and decisive when they don't.

It also gives a real number for the comparison: the same 12 cases, run with the
model off and on. If the model adds nothing, that is worth knowing and worth saying.

### Step 7 — The four outcomes are derived from the rules, not invented

The brief asks for clarification, "no exact match" with closest alternatives, and no
invented products. PR8 adds a fourth case that people wrongly merge:

> **PR8:** "Out-of-stock and discontinued items must not be quoted as available."

An out-of-stock item **matches** the request. It exists, it is the right product, it
just cannot be ordered today. That is not "no match". Collapsing the two tells the
customer the product does not exist — false, and it loses the sale twice: once now,
and once when they find it on the website.

| Outcome | When | Why it is a distinct case |
|---|---|---|
| `quoted` | Matches and available | — |
| `clarified` | A missing detail would change the answer | Asking beats guessing |
| `no_match` | Nothing satisfies every constraint | Plus closest alternatives, explicitly labelled non-matches |
| `refused` | Matches but cannot be ordered | PR8: the item exists, it just cannot be supplied |

Declare it as a **closed set with required fields**, enforced in code. Then a
`no_match` carrying a price is a defect rather than a nuance, and a caller branches
on `outcome` instead of parsing prose.

The catalog supports three of the four today: 2 of 72 SKUs are out of stock (so
`refused` is demonstrable), and 1 is on sale (so PR3 — "a sale price replaces both
the list price and volume pricing" — is demonstrable). `discontinued` has **0 live
samples**, so that branch is implemented and unit-tested but not demonstrated end to
end. Record it as not-run-with-reason, never as a pass.

### Step 8 — Search: filters then ranking, because the brief says so

> "Hard constraints as filters, softer wishes as ranking; unit and size
> normalisation."

Mandatory attributes filter; preferences rank. No embeddings — hybrid search is
nice-to-have, and adding it means a provider, a timeout, and a new failure mode for
no scored gain. Deterministic ranking is also *auditable*, which matters when a
total is being defended in an interview.

The part that earns its keep is **normalisation**, which the brief names explicitly:
"letter-size" / "8.5 × 11 in" / "A4-ish" for the same size, "4/4" for double-sided
full colour, "24 lb" for 90 gsm. A closed alias table mapping informal trade language
onto the catalog's own vocabulary is a page of data and does more for the search axis
than any similarity score.

### Step 9 — The evaluation has one trap: circularity

Must-have #7 wants "expected products and totals". If the expected totals are
generated by running the system and pasting the output, the harness can only pass.
That is theatre, and it is the most common way this requirement is faked.

The fix is cheap: **declare the expectation separately from the request.**

```json
{
  "number": 1,
  "request": "letter-size flyers, one side, colour, under 250 a pack, 20 packs",
  "expect": {"outcome": "quoted",
             "skus": ["PL-PR-LTR-MT-100-40", "PL-PR-LTR-GL-100-40", ...]},
  "lines":  [{"sku": "PL-PR-LTR-MT-100-40", "quantity": 20}],
  "proves": "budget compared at the requested quantity (PR6); the brief's own example"
}
```

The fixture names the expected SKUs and the requested lines; a `recompute_totals()`
function derives the arithmetic **from the expected SKUs**. Now a case that
contradicts itself fails. In the full build this caught a fixture whose expected
subtotal was 76.50 higher than its own request implied — a real defect found by the
harness rather than by a reviewer.

Be precise about what this proves and what it does not. Recomputing from expected
SKUs validates **selection and quoting**. It uses the same pricing engine, so it does
**not** validate the engine — that is Step 5's unit tests. Two mechanisms, two jobs.
Saying so out loud is worth more than a clean 12/12.

**12 cases, chosen to cover rules rather than requests:**

| # | Covers | Case |
|---|---|---|
| 1 | PR6 + PR2 | The brief's own example: 20 packs, budget, 20+ tier applies |
| 2 | PR2 | Tier boundary: quantity just below vs just at a `min_qty` |
| 3 | PR3 | Sale item: sale price replaces both list and tiers |
| 4 | PR4 | Delivery free at ≥ 3,000, charged below it |
| 5 | PR5 | VAT half-up rounding on a value that distinguishes it from banker's |
| 6 | PR8 | Out-of-stock → `refused`, not `no_match` |
| 7 | — | `clarified`: genuinely ambiguous request |
| 8 | — | `no_match` with closest alternatives, labelled |
| 9 | Weight | `24 lb` → 90 gsm resolves to a real product |
| 10 | Size | `8.5 × 11` and `letter` resolve to the same SKUs |
| 11 | Colour | `4/4` → double-sided full colour |
| 12 | Bundle | Budget too low for the request → honest no-match, no invention |

Each case names the rule it proves, so coverage is auditable and gaps are visible.
That is what "AI and data evaluation" is actually scoring.

### Step 10 — Refresh is where a brittle parser dies live

> "In the demo round we will give you an updated version of the site and ask you to
> re-ingest it without code changes."

This is the must-have that punishes shortcuts taken in hour 1, in front of an
audience. If the extractor is per-page selectors or hardcoded SKUs, the new site
breaks it live.

The constraint, therefore, is **parse by shape, not by page.** The site has 4 markup
shapes across 36 product pages — a small closed set of strategies tried in order,
with anything unrecognised going to `review_items` instead of raising. Designed in at
hour 0:40 this is nearly free. Retrofitted at hour 5:00 it is a rewrite.

Rehearse it, cheaply: copy the site, plant a known set of changes (one SKU removed,
one price altered, one item moved out of stock), re-ingest, and check the counts move
in the direction predicted. That converts "it should work" into a number, and it is
the same 20 minutes whether you do it at hour 5:45 or skip it and hope.

### Step 11 — Every cut, and the sentence that licenses it

Restating §3 as a single argument, because this is the section a reviewer will read
when asking "why is there no embedding?":

- **Embeddings** — nice-to-have; adds a provider dependency that can fail during the
  live demo; and the full build's measurement is instructive: placed before price it
  reordered 13 of 28 cases with 0 improvements and 6 regressions, and after price it
  reordered 3 with 0 improvements and 0 regressions. A tiebreak that never helps is
  not worth a dependency.
- **Multi-item baskets** — nice-to-have; one product per request still demonstrates
  the pricing engine.
- **Conversation memory** — nice-to-have; single-turn is stated as a limitation, and
  the brief scores honesty about limits.
- **Metrics/observability** — nice-to-have; one log line keeps the production
  conversation alive for ~5 lines.
- **Mutated-site harness and snapshot diff** — not required; the Step 10 rehearsal
  covers the scored need.
- **htmx / Next.js** — the brief says "UI or CLI"; a framework adds a build step, a
  second process, CORS, and eats the five-command budget.
- **28 cases → 12** — "at least 10", and 12 covers every pricing rule.

### Step 12 — Why this plan survives the interview

Because every choice traces to a sentence in the brief or a measurement on the site.
The questions have short answers:

| Question | Answer |
|---|---|
| Why not embeddings? | Nice-to-have, and a provider dependency that can fail in your demo |
| Why four outcomes? | PR8 makes out-of-stock a different case from no-match |
| Why integer satang? | PR5 names half-up rounding; `round()` is banker's |
| Why not Next.js? | "UI or CLI" — and it breaks the five-command budget |
| Why only 12 cases? | "At least 10", and each one names the rule it proves |
| Why does the model not price? | "The model decides intent, code decides facts and prices" |

That is the actual deliverable. The code is evidence for the reasoning, which is why
1,760 defensible lines beat 11,000 unexplained ones on the axes that are scored.

---

## 6. The three things that will kill it

**1. Crawling HTML only and not noticing the tier documents.**
Fails *silently* with plausible wrong numbers. Nothing crashes; every total is just
short by the discount.
→ Recon first, then assert `105 tier rows` as a test, and put the crawl's own counts
in `ingest_runs`.

**2. Building the model path first.**
Turns a nice-to-have into a dependency. If the endpoint is slow, rate-limited, or
returns `content: null` at 5:30, there is nothing to demo.
→ Rules path complete and passing before the model exists.

**3. A parser tuned to today's markup.**
Dies in the demo round, live, on an unseen version of the site.
→ Shape-based strategies, a review queue for the unrecognised, and a rehearsal
against a mutated copy.

All three share a shape: they are cheap to prevent at hour 0 and expensive to fix at
hour 5. That is the argument for spending the first 40 minutes on recon instead of
code.

---

## 7. What this plan gives up, honestly

Not a limitations section for the README — a statement of what the reduction costs,
so the trade is visible rather than implied.

- **A paraphrase-only request will miss.** "Something cheap for handouts" has no
  size, weight, category, or trade term to filter on. Without embeddings there is
  nothing to fall back on. This is the largest real capability loss.
- **One product per request.** "50 flyers and 200 business cards" needs two
  conversations.
- **No follow-ups.** "Make that 40 packs" is not understood. In a chat channel — the
  channel the brief mentions for deployment — this is a genuine design gap, not a
  cosmetic one.
- **No dashboard.** The measures exist as log lines; nobody can look at a trend
  without reading JSON.
- **Four eval cases cannot run at all** against this catalog: `discontinued`
  (0 samples — all 72 SKUs are `in_stock` or `out_of_stock`, none discontinued),
  prompt injection (0 pages carry an attempt), and the 28 lb / 32 lb weight
  conversions (no 105 or 120 gsm product exists — the catalog's weights are 70, 75,
  80, 90, 100, 130, 160, 170, 180, 200, 230, 250). Implemented and unit-tested, not
  demonstrated end to end — which must be recorded as not-run with the reason, never
  counted as a pass.

---

## 8. Where the numbers in this document came from

Everything in this table was checked on this machine. The one row that is
**derived rather than measured** is flagged as such, because that distinction is the
whole point of the section:

| Figure | Value | Source |
|---|---|---|
| HTML pages | 45 (36 product, 7 category, 2 root) | `find paperlane -name '*.html'` |
| Tier documents | 59 | `find paperlane -path '*api/pricing*' -name '*.json'` |
| Crawl decomposition | 1 index + 7 category + 36 product + 59 tier = 103 | matches `ingest_runs.pages_fetched` |
| Crawl requests | 103 | `ingest_runs.pages_fetched` |
| Crawl duration | 102.6 s, measured (1.0 req/s) | `ingest_runs` after the timing fix — see below |
| Products / tier rows | 72 / 105 | `catalog.duckdb` |
| Markup shapes | 4 | `count(distinct source_shape)` |
| Out of stock / on sale / discontinued | 2 / 1 / 0 | `catalog.duckdb` |
| Tier data in initial HTML | none | `grep` for tier markers on a live product page |
| Tier loading mechanism | `fetch('api/pricing/<sku>.json')` | `paperlane/assets/tiers.js` |
| Full build size | 11,043 src / 9,986 test lines | `wc -l` |
| Full build scope verdict | 2h02m build, 4h15m end to end vs 15–20h predicted | `CHANGELOG.md` |

The `~1,760 line` figure for this plan is a **projection**, not a measurement, and
it is a bottom-up sum of the layer table in §2 — not a subtraction. The subtraction
was tried first and rejected, which is worth recording because it looks like it
should work and does not:

```
full build source            11,043 lines
minus embeddings               -473
minus records                  -657
minus metrics                  -519
minus mutate                   -915
minus evaluate                -1,158
                             ---------
"remaining"                   7,321 lines
```

7,321 is not a smaller system — it is the same system with its extras removed. The
modules that survive (`api.py` 996, `assistant.py` 716, `catalog.py` 690,
`extract.py` 675, `search.py` 615, `aliases.py` 538, `interpret.py` 430, `model.py`
417, `ingest.py` 358, `pricing.py` 304, `similarity.py` 282, `normalize.py` 265,
`refresh.py` 186, `cli.py` 182, `ui.py` 175, `money.py` 149, `crawl.py` 145,
`criteria.py` 112) are large because they carry depth this plan deliberately does
not buy: a four-shape extraction ladder with a review queue, an alias table covering
the whole trade vocabulary, a guard system on the assistant, a documented API with
executable examples.

So the honest relationship between the two numbers is: **1,760 is an independent
bottom-up estimate of a shallower system, and 7,321 is what the same system costs
when built to the full build's depth.** The gap between them is depth, not features.
That is the real scope decision, and it is a bigger one than any item in §3.

### A note on the crawl timing

*Historical, and since fixed. Kept because the reasoning is the point.*

The snapshot at the time of writing showed `started_at` and `finished_at` 0.37
seconds apart for 103 pages — an implied 280 req/s, which the crawler refuses to
exceed (`rate_per_second > 2.0` raises). The row was not evidence of a fast crawl;
it was evidence that `started_at` was stamped **after** the crawl, inside the
snapshot build. `catalog.py` set `started = datetime.now(...)` at the top of the
build function, so the pair measured database construction, not fetching.

Both consequences are now resolved:

- **The crawl duration is measured, not derived.** `ingest.py` stamps the start
  before the first request and passes it into `build_snapshot` as
  `crawl_started_at`. The committed row now reads **102.6 s for 103 requests —
  1.0 req/s**, which agrees with the configured rate instead of contradicting it.
  Three tests in `tests/test_catalog.py::TestIngestRunTiming` pin it, one of which
  asserts that a start an hour in the past yields a duration of at least an hour.
- **The ~52 second floor was arithmetic.** At the enforced 2 req/s the crawl
  cannot take less; the measured run went at the default 1 req/s and took twice
  that. The floor was right about the cap and wrong as a budget figure.

This is the same class of error §4 warns about — a plausible figure nobody
recomputed — caught here only because the arithmetic refused to agree. It was
also caught *again* by this document, which is the argument for writing the
rejected subtraction down.

The hour budget in §4 is likewise a prediction, and the one documented attempt at
predicting this work was off by 8×. The ordering is trustworthy; the clock is not.

---

## 9. Confidence

**High confidence**, because measured: the tier-document discovery, the schema
shape, the four-outcome split, the rounding requirement, and the 103-request crawl
decomposition. The crawl's *duration* is the one measured-looking number that is
actually derived — §8 explains why the snapshot cannot corroborate it.

**Medium confidence**: the 12-case set covers the rules, but whether those 12 are the
*right* 12 is a judgement that only running them against a real interpreter settles.
Expect to rewrite two.

**Low confidence**: the hour budget, and the claim that 1,760 lines is enough. Both
are projections from a build that took a different path, and the honest position is
that this plan's value is in its ordering and its citations — not in its clock. The
§8 subtraction makes the size risk concrete: the same feature set built to the full
build's depth came to 7,321 lines, so the depth assumptions in §2 are the ones most
likely to be wrong.
