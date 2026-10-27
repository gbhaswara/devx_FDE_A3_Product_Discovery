# PaperLane product discovery

A sales assistant for a paper merchant. A customer describes what they need in
their own words; the assistant finds the right products from the crawled
catalog, prices them to the satang, and writes a reply a salesperson can send.

Built for the devx AI Labs FDE take-home, assignment **A3 — Product Discovery**.

---

## 1. How to run it

From a clean checkout, in this directory:

```bash
uv sync                                    # 1. install dependencies
./run.sh test                              # 2. the full suite, offline, no model
./run.sh serve                             # 3. the app on http://127.0.0.1:8001
./run.sh eval                              # 4. the recorded evaluation set
./run.sh ask "A4 80gsm copy paper, 20 reams" --conversation demo \
  && ./run.sh ask "make it 50" --conversation demo   # 5. two turns, no server needed
```

Step 5 is deliberately two turns: the second one is understood without repeating
the product, and the reply says which requirements it remembered.

Those five are the demo path. Five further commands exist to *prove* something
rather than demonstrate it, and none is needed to see the system work:

- `./run.sh diff` compares the current snapshot with the previous one. It reports
  `comparable: false` on a fresh checkout — see below for why that is correct.
- `./run.sh verify-refresh` (~55s) mutates a git-ignored copy of the site,
  ingests it into a throwaway snapshot, and checks that every change it declared
  in advance is reported under the correct kind. It needs no server and no
  network beyond loopback.
- `./run.sh metrics` reads the records the assistant writes and reports five
  measures — fallback rate, zero-result rate, extraction backlog, p95 latency,
  and reply/total disagreement. On a fresh checkout it says plainly that there is
  no data rather than reporting zero rates, which would look like a healthy
  system. After `./run.sh eval`, `./run.sh metrics --eval` gives the same
  measures over the evaluation harness's records. `GET /api/metrics` serves them
  from the running service. Details, thresholds and limitations:
  `docs/observability.md`.
- `./run.sh similarity` measures the semantic tiebreak. It is the only command
  that needs an embedding provider, and it says `NOT MEASURED` when it cannot.
- `./run.sh eval --cases eval/conversation-cases.json` scores the conversation
  layer — 11 recorded conversations, 24 turns — and prints a single-turn replay
  digest: the 22 comparable cases must produce the same reply as before the
  feature existed. `eval/conversation-negative-control.json` is the same file
  wrong in five ways and exits 1, so the harness is shown able to fail.

**None of the five demo commands needs an embedding provider**, and none sets
`PAPERLANE_EMBED_*`. That is not luck: with no provider configured the similarity
term is *omitted* from the ranking rather than set to a constant, so the ordering
is the pre-semantic one by construction.

That is the whole demo. The catalog snapshot (`data/catalog.duckdb`) is
committed, so steps 3 and 5 work without crawling anything or starting a server.

Step 5 is the shortest honest demo: it asks one question through the same
interpreter, search, pricing and rendering the HTTP service uses, and prints the
reply. `--json` gives the identical shape `POST /api/ask` returns; `--verbose`
adds how the request was read. It also writes a request record, so
`./run.sh metrics` afterwards counts it.

`./run.sh diff` reports `comparable: false` on a fresh checkout, and that is
correct rather than broken: there is no previous snapshot to compare against
until you have refreshed at least once. Run `ingest` twice and the second diff
has a baseline.

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
                        data/catalog.duckdb  (committed)

              ----------- one request, top to bottom -----------

    request text
        |
        v
    interpret.py  --->  Criteria   (aliases.py resolves vocabulary;
    rules first,                    criteria.py is the typed shape)
    model optional
        |
        v
    conversation.py  merges Criteria across turns. No-op without a
    conversation id. The model never sees the transcript, so every
    constraint traces to a turn that stated it.
        |
        v
    assistant.py  —  validate, then search() (hard filter + total rank),
        |            then quote() (pure, integer satang, half-up).
        |            Produces exactly one outcome:
        |            quote / clarify / no match / refuse
        v
    api.py (JSON)  +  ui.py (one page, htmx)

              ---------- what proves it ----------

    evaluate.py (28 cases)  +  conversation_eval.py (11 conversations)
        |
        v
    records.py (one per request)  ->  metrics.py (derived on read)
```

Four properties hold structurally rather than by convention:

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

**The guarantee survives memory.** This one only became load-bearing once
conversations existed, which is where the previous three could have quietly
weakened. The merge happens *after* interpretation and only over typed
criteria, and only the current turn's text ever reaches an interpreter. So every
constraint in a merged request is traceable to a turn that stated it, and the
model still has no channel into the numbers.

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
| `conversation.py` | The continuation rule, the two bounded stores, no text retained |
| `api.py` / `ui.py` | JSON endpoints and the single page |
| `evaluate.py` | The recorded evaluation harness |
| `conversation_eval.py` | The conversation harness and the single-turn replay digest |
| `records.py` / `metrics.py` | One request record; five measures derived on read, never counted |
| `embeddings.py` / `similarity.py` | The optional tiebreak provider and its measurement command |

`refresh.py` / `mutate.py` are test tooling rather than serving code: they stand
up a mutated copy of the site and verify a refresh against a declared manifest.
`cli.py`, `ask_cli.py`, `refresh_cli.py` and `ingest.py` are the command surface
`run.sh` dispatches to. `model.py` is the only module that talks to a language
model; `embeddings.py` talks to an embedding provider and is inert when none is
configured.

Full detail in `docs/`: `pricing.md`, `ingestion.md`, `search.md`,
`assistant.md`, `api.md`, `refresh.md`, `refresh-verification.md`,
`semantic-ranking.md`, `observability.md`, `conversation-memory.md`,
`chat-channel.md`. In the repository root, `TEST.md` lists the eight test layers
and the per-module test inventory, and `ANALYZE_POST.md` is this design written
out in full — the data, search, agent and pricing layers, and why the build is
ordered the way it is.

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

**Weight conversions are only partly verified against live data.** The
pound-to-grammage table (`20→75`, `24→90`, `28→105`, `32→120`) is implemented
from the brief, but the committed v1 catalog stocks no 28 lb or 32 lb paper, so
only two of four rows can be checked against it. Cases 23 and 24 are scored
against the mutated v2 catalog, which does contain `28 lb` and `32 lb` products,
rather than being counted as passes against v1.

**No single evaluation run scores all 28 cases.** Four behaviours have no live
data in v1, so they are scored against the mutated v2 snapshot that
`./run.sh verify-refresh` builds. The honest summary is **24/24 on v1 and 21/21
on v2** — seven cases are pinned to v1 because their expected product sets
enumerate v1's exact offering, which v2 genuinely extends; rewriting them from
v2's own output would make the expectation circular. Per-case reasoning is in
`eval/results.md`.

**Pack-size ambiguity is surfaced, not resolved.** "Under 250 a pack" is compared
against whatever unit the product is actually sold in — a ream, a pack, a pad.
When a customer's "pack" might mean 50 sheets or 500, the reply states the basis
it used rather than guessing silently. That is honest, but it is not a
resolution.

**Semantic search is a tiebreak, and its benefit here is unmeasured.** Search is
hard filtering plus deterministic ranking, with an optional similarity term that
decides ties *among items priced equally*. A request phrased entirely in
paraphrase, with no size, weight, category or trade term the aliases recognise,
will still miss — embeddings never enter the filter, by design, because letting
them in would make membership approximate.

Measured against the recorded set with `bge-m3`, the term reorders 3 of 28 cases,
changes no first result, and produces **0 improvements and 0 regressions**. It
is a better tiebreak than SKU order; it is not a quality win, and it is not
described as one. See [`docs/semantic-ranking.md`](docs/semantic-ranking.md).

**Conversation memory, deliberately conservative.** A follow-up that names no new
category or size continues the previous request, and the reply says which
requirements it remembered. The model never sees the conversation: the merge
happens after interpretation over typed criteria, so every constraint is
traceable to a turn that stated it. The cost is that "the cheaper one" with no
subject is a fresh request rather than a reference. See
[`docs/conversation-memory.md`](docs/conversation-memory.md).

**Three defects were shipped in that feature and found afterwards**, by probing
the running service rather than by reading the module: a first turn stating only
a quantity or only a budget could not be continued (A12), an unparseable turn
permanently erased the conversation (A13), and the turn number saturated once the
retained-turn cap was reached (A14). All three are fixed and all three are
registered in `BUG.md` Part 2b with how they were found. A13 is the interesting
one: it was D3 working as written, so fixing it meant answering a question the
decision left open — an empty turn is now *fresh for the reply* and *transparent
for the state*. Each fix arrived with a test and a falsification check: the fix
was reverted, the new test and evaluation case were confirmed to fail, and the
fix restored.

**The conversation harness cannot falsify its own pricing axis.** A fresh turn is
compared against the standalone run of the same request, and both call the same
pricing code, so the axis cannot disagree with itself from a case file. It is
checked structurally instead — a `quoted` outcome must carry a total — and the
harness does not claim more than that.

**No auth and no rate limiting** beyond the crawler's own 1 req/s politeness.
The app is local-only and not hardened for exposure.

**Two behaviours are implemented but not demonstrated end to end.** Discontinued
products and prompt-injection defences are unit-tested, but the v1 catalog has no
discontinued item and no page carrying an injected instruction, so neither can be
exercised against live data. Both are marked not-run in the evaluation results.

**The reply axis of the evaluation is mostly mechanical.** It checks that a reply
exists, names no absent SKU, and carries no total it did not earn. "Would a
salesperson send this?" is a judgement the harness does not make.

**Logging and metrics have four stated limitations.** In `data/requests.jsonl`:
**no rotation** (it grows without bound; the remedy is manual), and **p95 is over
a count window of the last 1000 records, not a time window**, so a burst can
flush history. The **request digest is a grouping aid, not anonymisation** — a
16-character hash of a short string is brute-forceable — and **redaction is
pattern-based**, so it catches the shapes it knows and the structural guarantee
(no field that could hold a key) is what actually carries the weight. Full
reasoning in [`docs/observability.md`](docs/observability.md).

---

## 5. What I would do with another week

In order, because the order is the judgement:

1. **Supplier onboarding.** Per-site parser profiles with a regression corpus per
   site, so adding a second merchant is a config file plus fixtures rather than
   new code. This is the difference between a demo and a product.
2. **Price-change monitoring.** Alert on movement beyond a threshold between
   snapshots. The diff already computes this; what is missing is the delivery
   channel and the judgement about what counts as noteworthy.
3. **A real semantic *retrieval* layer.** The tiebreak built here cannot help a
   paraphrase-only request, because embeddings never reach the filter. Doing that
   safely means measuring recall against a labelled set — not vibes — and being
   willing to lose the "cannot change membership" guarantee. I would want numbers
   before making that trade.
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
  defects from that phase are recorded in `CHANGELOG.md`, each with *how* it was
  found rather than only what changed; three more, from conversation memory, were
  found later by probing the running service and are registered in `BUG.md`
  Part 2b. Total register: 15 data traps, 9 analysis defects, 5 shipped-code
  defects.
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
| No credential reaches a record | `tests/test_records.py::TestNoCredentialInRecords` sets a sentinel key, makes a model call, and scans the log |
| The metrics are derived, not counted | `tests/test_metrics.py::TestDerivedOnRead` deletes a record and asserts the metric moves |
| The disagreement metric can fail | `tests/test_metrics.py::TestDisagreement` corrupts a stated total and asserts the count goes non-zero |
| The conversation layer is scored | `./run.sh eval --cases eval/conversation-cases.json` — 11 conversations, 24 turns |
| That harness *can* fail | `./run.sh eval --cases eval/conversation-negative-control.json` exits 1 |
| Memory did not change single-turn replies | `tests/test_single_turn_unchanged.py` — a SHA-256 of every case's `{outcome, text}`, recorded from the commit *before* the feature existed |
| The three conversation defects are fixed | `BUG.md` Part 2b; each fix was reverted to confirm the new test fails |
| The test inventory | `TEST.md` — eight layers and a per-module count (1095) |

---

## Scope note: two tiers

This submission is deliberately split into two tiers, and both are named here
rather than blurred.

**Tier 1 — the core, and what the assignment is actually scoring:** the crawler
and snapshot, the normalisation layer, the pricing engine, search and
interpretation, the four assistant outcomes, the JSON API, and the evaluation
harness with its results. Everything in sections 1–7 above. **Complete** — 86 of
86 tasks closed.

**Tier 2 — extras, each independently droppable.** Six were planned and all six
are built; a seventh, conversation memory, was planned as a nice-to-have and
grew into a full change of its own. Each shipped as its own OpenSpec change
under `openspec/changes/archive/`, with its own capability spec:

| Item | State |
|---|---|
| Multi-item basket quoting | Built — `POST /api/quote/lines`, evaluation cases 16 and 27 |
| Single-page interface | Built — `ui.py`, all four outcomes rendered |
| Snapshot diff as a demo artefact | Built — `GET /api/diff`, `./run.sh diff` |
| Mutated-site refresh demonstration | Built — `./run.sh verify-refresh` mutates a copy of the site, ingests it, and verifies all 12 injected changes are reported under the correct kind. Closed by `add-mutated-site-refresh-harness` |
| Hybrid semantic tiebreak | Built — `embeddings.py`, optional `PAPERLANE_EMBED_*` configuration, similarity term after price; measured with `./run.sh similarity`. Closed by `add-semantic-tiebreak` |
| Structured logging and the five metrics | Built — `records.py`, `metrics.py`, `./run.sh metrics`, `GET /api/metrics`. Closed by `add-observability`. See `docs/observability.md` |
| Conversation memory | Built — `conversation.py`, the continuation rule, two bounded stores, disclosure in every continued reply, and its own evaluation. Closed by `add-conversation-memory` |

**221 tasks are closed across the five archived changes and none is open:**
86 (Tier 1) + 26 + 27 + 28 + 54 (the four Tier 2 / nice-to-have changes).

**The brief's five nice-to-haves, and where each landed:**

| Nice-to-have | State |
|---|---|
| Hybrid search (filters plus semantic) | Built as a tiebreak that cannot change membership — see above |
| Multi-item quotes | Built — `POST /api/quote/lines` |
| Conversation memory | Built — continuation rule in `conversation.py`, two bounded stores, disclosure in every continued reply, and its own evaluation. See `docs/conversation-memory.md` |
| Defences against untrusted text | Built — sanitising boundary in `model.py`, escaping in `ui.py`, plus tests |
| Notes on deploying behind LINE or WhatsApp | `docs/chat-channel.md` — platform limits, the webhook and identity work, and the gaps that must close before this is internet-reachable. Memory now exists; an authenticated conversation principal does not |

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

