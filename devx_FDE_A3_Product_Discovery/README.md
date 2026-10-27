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
  network beyond loopback. With `--keep` it leaves the snapshot behind, and
  `./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb` scores
  the same case set against that second catalog.
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
  layer — 12 recorded conversations, 27 turns — and prints a single-turn replay
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

**Ingesting without disturbing the committed snapshot.** The demo round supplies
an updated site and asks for a live re-ingest, so `ingest` takes `--db` (or the
`PAPERLANE_DB` environment variable) and `serve`, `eval`, `ask` and `metrics`
accept the same, all resolving through one path. That means a new site can be
ingested into a separate file and served from it, leaving `data/catalog.duckdb`
byte-for-byte intact — the property is asserted by comparing the committed file's
bytes rather than its size or mtime. Without the flag everything defaults to
`data/catalog.duckdb` exactly as before, so the five demo commands are unchanged.
Every response also reports the snapshot `path` it was computed from and how old
it is.

Serve from **this** directory, not its parent. The site lives at
`./paperlane/`, so the base URL is `/paperlane/`; serving the parent directory
puts the site at `/devx_FDE_A3_Product_Discovery/paperlane/` and the ingest fails
with `HTTP 404` on `index.html`.

**Two ports, and they are not interchangeable.** 8000 serves the *catalog site*
the crawler reads; 8001 serves the *assistant*. Binding the assistant to 8000
collides with the site. `./run.sh serve` defaults to 8001 for that reason.

**What the page gives you.** Two equal columns — the catalog on the left, the
assistant on the right — each half the page. The catalog lists every product in
the snapshot under its category, with size, weight, pack size, the effective unit
price and an out-of-stock label. Categories are collapsed on arrival, so all of
them are visible at once instead of the first few and a scrollbar; opening one
shows its products in place, and the page scrolls rather than clipping them
inside a fixed-height box. Clicking a row fills the search box — it never submits
and never quotes, so a click cannot spend a model call or invent a quantity; you
still press **Ask**. A row's price is what a one-unit quote returns for that SKU,
which is why the one sale item shows 259.00 rather than its 299.00 list price:
the quote would not honour the list price, so the column must not advertise it.
Below 900 px the two columns collapse to one, search first.

### Deploying the UI

`./run.sh serve` **is** the deployment. One process serves the page, the fragment
it swaps in, the asset it loads and the JSON API, all on one origin. There is no
build step, no bundle, no second server and no static-file mount to configure —
the page is a Python string in `ui.py` and the result panel is rendered by the
same code path that answers `/api/ask`.

```bash
./run.sh serve                          # 127.0.0.1:8001, the default
./run.sh serve --port 8020              # a different port
./run.sh serve --host 0.0.0.0           # bind every interface
./run.sh serve --db /tmp/v2.duckdb      # serve a different snapshot
```

| Route | What it is | Returns |
|---|---|---|
| `GET /` | the whole UI | one HTML document |
| `POST /ask` | what htmx calls | a `<div class="panel">` fragment, not a page |
| `GET /static/htmx.min.js` | the vendored script | ~48 KB, `application/javascript` |
| `GET /api/*` | the documented JSON API | see `docs/api.md` |

**It needs no internet, and that is deliberate.** The page used to load htmx from
`unpkg.com`. That made the one interactive surface the only part of the system
depending on a CDN — while the tests, the evaluation and the CLI are all offline
by design. Worse, it failed *silently*: the form carries `hx-post` and no
`method` or `action`, so with no script the browser just issues a `GET` of the
current URL and the page reloads with the input cleared. The API kept answering,
so every `curl` check still passed while a human saw a dead form.

htmx 1.9.12 is now vendored at `src/paperlane/static/htmx.min.js` and served from
this origin. Its SHA-384 is recorded in `src/paperlane/static/VENDOR.md` and is
the same value the page carried as its Subresource Integrity hash, so these are
provably the bytes the CDN used to serve. `tests/test_ui_offline.py` holds both
halves: the page names no external host, and the route returns those exact bytes.

**Reaching it from another machine.** `--host 0.0.0.0` binds every interface,
but read the limitation in §4 first: there is **no authentication and no rate
limiting** on the app. Do not expose the port directly; put it behind a proxy
that terminates TLS and authenticates. With nginx:

```nginx
server {
    listen 443 ssl;
    server_name paperlane.example.com;
    # ssl_certificate / ssl_certificate_key …

    location / {
        auth_basic           "PaperLane";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass           http://127.0.0.1:8001;
    }
}
```

**What it reports at startup.** It prints the product and tier counts and the
snapshot path it is serving, then the catalog's age — `Catalog is 4h old (stale
above 24h)`. Age is stated, never gated on, because a server that refuses to
start on an old snapshot would fail the demo round. With no snapshot at all it
refuses to start and prints the `ingest` command rather than running a service
whose every request returns 503.

**One process, not many.** It calls `uvicorn.run` once with `log_level="warning"`.
There is no `--reload` flag — `serve` is the serving command, and `./run.sh serve
--reload` is rejected as an unknown argument. For a dev loop, run the same
application through uvicorn directly:

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn paperlane.api:create_app \
  --factory --reload --port 8001
```

DuckDB is opened read-only per request, so concurrent reads are fine, but do not
put multiple workers behind a load balancer while a re-ingest may swap the
snapshot file underneath them.

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

    evaluate.py (28 cases)  +  conversation_eval.py (12 conversations)
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
| `api.py` / `ui.py` | JSON endpoints, the two-column page, and the route that serves the vendored script |
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
on v2**, and both numbers come from `./run.sh`:

```bash
./run.sh verify-refresh --keep
./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb   # 21/21
./run.sh eval                                                          # 24/24
```

Seven cases are pinned to v1 because their expected product sets
enumerate v1's exact offering, which v2 genuinely extends; rewriting them from
v2's own output would make the expectation circular. Per-case reasoning is in
`eval/results.md`.

**Pack-size ambiguity is surfaced, not resolved.** "Under 250 a pack" is compared
against whatever unit the product is actually sold in — a ream, a pack, a pad.
When a customer's "pack" might mean 50 sheets or 500, the reply states the basis
it used rather than guessing silently. That is honest, but it is not a
resolution.

**The held-out set fails, and that is the honest result.** Against 11 requests in
phrasings the rules were never tuned on (`eval/held-out-cases.json`), 8 pass and 3
fail, all from one cause: a noun the aliases cannot map — a shade, or a weight in
pounds with no catalog equivalent — is dropped rather than surfaced, so the answer
silently widens to every paper of that size. "The pink A4 coloured paper" quotes
all seven A4 coloured papers instead of the one; "pastel grey A4 paper" returns all
33 A4 papers when nothing grey is stocked; "30 lb letter paper" returns all 19
letter papers. The failures are kept in the run, not pruned to get a clean sweep,
and a test asserts at least one remains. The recorded set was written *while* the
rules were built and used to fix them, so it cannot measure this; a held-out set is
the only thing that can.

**Freshness is reported, not enforced.** The catalog's age is on every surface
(`./run.sh metrics`, `GET /api/health`, the `snapshot.freshness` block) with a
24-hour threshold, but nothing is gated on it. A snapshot past the threshold is
labelled, not withheld — a gate that refuses to serve would fail the demo round,
which re-ingests a live unseen site and asks for answers immediately.

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

I used **opencode** with the **9router** endpoint (`9inference`, resolving to
`deepseek-v4.1-flash`) and a spec-driven workflow of my own (`openspec`) to keep
the proposal, eight capability specs, design decisions and an 86-task list in one
place. The model drafted the site analysis, the specs and most of the code; I
reviewed and corrected all of it, and the scope verdict is mine. It earned its
place finding defects: the live-model evaluation exposed a clarification branch
that tests had made unreachable, plus a colour ambiguity only the model's
phrasing triggered. The register holds 15 data traps, 9 analysis defects and 5
shipped-code defects. I kept the pricing arithmetic, the evaluation design and
the five-axis definitions. At runtime the model interprets free text only — it
never prices, selects a product or writes a total.

---

## 7. Where the evidence is

| Claim | Where to check |
|---|---|
| Prices are correct to the satang | `tests/test_pricing.py` (49 tests), `docs/pricing.md` |
| The evaluation passes | `./run.sh eval`, and `eval/results.md` for the full run |
| The second catalog scores the rest | `./run.sh verify-refresh --keep` then `./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb` — 21/21, and the run names the catalog it scored |
| The evaluation *can* fail | `./run.sh eval --cases eval/negative-control.json` — four deliberate corruptions, one per scoring axis |
| The scoring detects what it claims | `./run.sh eval --self-check` |
| A misread request is scored, not just a mis-ranked one | `./run.sh eval` — `interpretation` is the first axis; `tests/test_evaluate.py::TestInterpretationAxis` |
| Behaviour on unseen phrasing, warts included | `./run.sh eval --cases eval/held-out-cases.json` — 11 requests the rules were never tuned against, 8 pass and 3 fail on purpose |
| The catalog's age is visible | `./run.sh metrics` (prints `catalog age:`), `GET /api/health`, and the `snapshot.freshness` block in every API payload |
| The crawler is faithful | `./run.sh diff`, `tests/test_extract.py`, `docs/ingestion.md` |
| The documented API is real | `tests/test_api.py::TestDocumentedExamples` executes every example |
| The page works with no internet | `tests/test_ui_offline.py` — no external host in the markup, and `GET /static/htmx.min.js` serves the vendored build |
| The catalog column cannot drift from the quote | `tests/test_ui_catalog.py` — every row's price is compared against `/api/quote/lines` at quantity 1, and every product name is resolved back through the interpreter |
| The vendored script is the CDN artefact, not a lookalike | SHA-384 in `src/paperlane/static/VENDOR.md` equals the SRI value the page carried before vendoring |
| No credential is committed | `.gitignore`; `./run.sh test` includes a scan |
| No credential reaches a record | `tests/test_records.py::TestNoCredentialInRecords` sets a sentinel key, makes a model call, and scans the log |
| The metrics are derived, not counted | `tests/test_metrics.py::TestDerivedOnRead` deletes a record and asserts the metric moves |
| The disagreement metric can fail | `tests/test_metrics.py::TestDisagreement` corrupts a stated total and asserts the count goes non-zero |
| The conversation layer is scored | `./run.sh eval --cases eval/conversation-cases.json` — 12 conversations, 27 turns |
| That harness *can* fail | `./run.sh eval --cases eval/conversation-negative-control.json` exits 1 |
| Memory did not change single-turn replies | `tests/test_single_turn_unchanged.py` — a SHA-256 of every case's `{outcome, text}`, recorded from the commit *before* the feature existed |
| The four conversation defects are fixed | `BUG.md` Part 2b; each fix was reverted to confirm the new test fails |
| The test inventory | `TEST.md` — eight layers and a per-module count (1226) |

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
| Single-page interface | Built — `ui.py`, all four outcomes rendered, plus a collapsible catalog column that prefills the search |
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

