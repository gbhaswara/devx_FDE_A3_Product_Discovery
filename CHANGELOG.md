# CHANGELOG.md

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file records the project's own history. The planning entries are **artefacts of reasoning, not shipped code** — they are listed so the reasoning trail is auditable in the interview. The 0.5.0 entry below them is shipped code, and every claim in it is backed by a command whose output is recorded in `eval/results.md`. The planning artefacts named below — `ANALYZE_01.md`, `ANALYZE_POST.md`, `FIXED.md` and `MVC_PLAN.md` — now live under `devx_FDE_A3_Product_Discovery/docs/pre/` and `docs/post/`; historical entries keep the names they were written with.

Current status: **0.9.0 — Tier 1, three Tier 2 extras, conversation memory, and the gap-closure change, all complete; the brief audit and the refresh hardening after it are closed too.** **239 tasks closed across the six archived changes, none open** (86 + 26 + 27 + 28 + 54 + 18). **1263 tests** (1,260 passing offline under `./run.sh test-offline`, 3 provider tests skipped; 1,263 passing with a local Ollama embedding server), the 24 v1-runnable evaluation cases pass (and 21 against the mutated second catalog), the conversation set passes 12/12 over 27 turns, both negative controls fail as designed, and the held-out set reports 9/11 with two failures retained (`A34` closed the third). Requirements now live in the **eleven** main specs under `openspec/specs/` — 86 requirements, 227 scenarios; the changes that produced them are under `openspec/changes/archive/`.

---

## Session timeline — first conversation through complete submission

Reconstructed from filesystem mtimes (`find -printf '%T@'`) on the machine where the work happened, not from memory. All times are local (UTC+7), 2026-10-26.

| # | Time | Phase | Artefacts produced |
|---|---|---|---|
| 1 | 11:44:31 | Briefs extracted and read | `00_START_HERE_All_Briefs.pdf` → `.md`, `devx_FDE_A3_Brief.pdf` → text |
| 2 | 11:45:02 → 12:11:24 | **Explore** — A3 chosen over A1/A2; site inspected; stack decided | evidence gathered, no files yet |
| 3 | 12:11:24 | OpenSpec initialised | `openspec/config.yaml`, `.opencode/commands/*`, skills |
| 4 | 12:12:17 → 13:19:14 | **Propose** — requirements and capability specs | `proposal.md`, 8 × `specs/*/spec.md` |
| 5 | 13:21:31 | Specs complete | 65 requirements, 132 scenarios |
| 6 | 13:26:46 | Documentation started (first of the seven) | `AGENTS.md` |
| 7 | 13:28:10 | Git repository initialised with remote | `.git/` |
| 8 | 13:38:14 | Design and task breakdown | `design.md`, `tasks.md` (86 tasks) |
| 9 | 13:39:37 → 13:42:26 | Verification pass — every number recomputed from source; defects found and fixed | `ANALYZE_01.md` §12 corrections table |
| 10 | 13:42:26 | Seven docs complete | `AGENTS.md`, `ARCHITECTURE.md`, `BUG.md`, `CHANGELOG.md`, `CLAUDE.md`, `DESIGN.md`, `TEST.md` |
| 11 | 13:42:26 → 13:57:31 | **Apply** — scaffold, dependencies, `.gitignore`, `run.sh` | `pyproject.toml`, `run.sh`, `.venv` |
| 12 | 13:57:31 → 15:15:39 | Build — groups 1–7 (money, crawl, catalog, search, assistant, API) | 17 modules in `src/paperlane/`, 6 × `docs/*.md` |
| 13 | 15:25:52 → 15:58:24 | Build — groups 8–9 (evaluation harness, submission docs) | `evaluate.py`, `eval/*`, `README.md`, `CUSTOMER_SUMMARY.md` |
| 14 | 15:59:14 | Verification — groups 11.1–11.3, 11.5 | 590 tests, 24/24 eval, negative control exits 1 |

### Measured durations

| Phase | Start | End | Duration |
|---|---|---|---|
| Extract and read briefs | 11:44:31 | 11:45:02 | 0h00m31s |
| Explore and analysis | 11:45:02 | 12:11:24 | **0h26m22s** |
| OpenSpec init | 12:11:24 | 12:12:17 | 0h00m53s |
| Propose (proposal + specs) | 12:12:17 | 13:21:31 | **1h09m14s** |
| Design and tasks | 13:21:31 | 13:38:14 | 0h16m43s |
| Seven docs + verification | 13:38:14 | 13:42:26 | 0h04m12s |
| **Planning total** | **11:44:31** | **13:42:26** | **1h57m55s** |
| Scaffold | 13:42:26 | 13:57:31 | 0h15m05s |
| Implementation (first module → last doc) | 13:57:31 | 15:59:14 | **2h01m43s** |
| **Briefs read → submission complete** | **11:44:31** | **15:59:14** | **4h14m43s** |

Both totals are reconstructed from filesystem mtimes (`find -printf '%T@'`), not from memory. The second is wall-clock, which is the only thing mtimes can measure — it is not a measure of focused effort, and it includes idle time and every model round-trip.

### Does the plan fit the brief's six hours?

The brief says *"Plan for about 6 hours of focused work. Please do not spend much more."* This section was written during planning as a prediction. It is now a **measured result**, and the measurement contradicted the prediction, so both are recorded.

**What was predicted, at 13:42:26.** Planning cost 1h58m. The build estimate was **15–20 focused hours**, which does not fit six. The stated conclusion was that the brief's budget was exceeded by roughly 3×, that the gap was a deliberate scope decision, and that trimming to six hours was the user's call.

**What was measured, at 15:59:14.** The implementation took **2h01m43s** of wall-clock from the first module to the last doc, and **4h14m43s** total from reading the briefs to a complete submission. The build fit inside the brief's six-hour envelope with room to spare, and the whole exercise fits inside it too.

**The estimate was wrong by roughly 8×, and the error is the finding.** The prediction assumed Tier 1 was "a crawler, a four-shape extraction ladder, … a 28-case evaluation harness" costed as if each component were built from scratch by hand. What it failed to account for was that the specification was already complete: 65 requirements, 132 scenarios, and a task list where every task states its own verification. Implementation against a verified spec is largely transcription, and the parts that were not — pricing arithmetic, evaluation design — were the parts the planning had already pinned down numerically. `ANALYZE_01.md` §8's three-day plan was inherited from a generic "build a product from scratch" intuition and was never re-derived from the artefact count.

**This is the same failure mode the planning phase kept catching in the numbers**: a plausible figure that nobody recomputed, and that would have been asserted as fact. The planning section caught nine such defects in the catalog data by recomputing from source; it did not occur to me to recompute the *estimate* from the same source. Had the submission been delivered with the 15–20 hour claim intact, it would have been a false statement about my own work — and it would have made a scope-trimming decision look necessary when it was not.

**What survives from the original section.** The distinction between planning cost and build cost is still worth stating, and it is now measured on both sides: 1h58m of planning plus 2h02m of building, with the planning buying a spec precise enough to build against quickly. The reasoning was not just cheap, it was *load-bearing* — the nine catalog defects it caught before implementation are why the evaluation set passed on its first live run instead of being debugged into agreement.

**What does not survive.** The claim that Tier 1 could not fit six hours. It fit. There is no scope gap to defend, and the scope-trimming question that was flagged as "the user's unresolved call" is now moot for Tier 1. The genuinely open item is smaller and different: whether the three unbuilt Tier 2 items are worth adding, which is a cost/benefit question rather than a schedule one.

### Environment facts recorded at this point (13:42:26)

Superseded by the 0.5.0 entry below; kept because the delta is the history.

- Git: repository initialised, remote `origin` configured, **0 commits**, no `.gitignore` yet.
- Implementation directories (`src/`, `tests/`, `eval/`, `data/`, `docs/`) did **not** exist. Nothing had been built.
- Python 3.14.4, `uv` 0.12.20, `openspec` 1.14.0, `duckdb` not yet installed.
- `openspec validate add-paperlane-product-discovery --strict` passes.

---

## [Unreleased]

### Changed — 2026-10-29 · chat back on the hosted provider, embeddings stay local

The deployment configuration is the original split, which is also the one the
brief's constraints imply: **criteria extraction runs on 9router's `9inference`**
(`http://127.0.0.1:20128/v1`, key from `PAPERLANE_LLM_API_KEY`), and **embeddings
run on local Ollama** (`bge-m3:latest`, 1024-dim, `PAPERLANE_EMBED_*`). The two
namespaces were already separate, so this is configuration and documentation —
no code change.

Measured with `./run.sh eval` against the hosted provider: **22–24/24** requests
reach the same outcome under both strategies across three consecutive runs (22,
23, 24), every quoted total identical, and all 24 verdicts pass. The variance is
the model answering or declining (#12 `refused` vs `no_match`; #17 `4/4`), not a
wrong price — the hosted model is not deterministic. Latency 1.2–2.4 s per
criteria extraction over five calls, and sustained runs hit the gateway's
upstream rate limit.

The local fallback stays documented and measured, because it is what makes the
system runnable offline: `qwen3.5:4b` @ `sha256:d8b0f5e9760c…` agrees on 20/24,
`qwen3.5:9b` on 22/24 outcomes but only 20/24 identical totals at 2.5× the
latency. Those are the numbers from the previous entry, unchanged.

- **A38 — a configured model that cannot answer reported perfect agreement.**
  `./run.sh eval` with a model configured but no key printed `model: available`
  and `24/24 requests reached the same outcome`. Both columns were the rules run:
  every model call raised `HTTP 401`, interpretation fell back to rules, and the
  harness compared the rules path with itself. It now probes the client once
  before comparing, reports `model: configured, unreachable` with the reason, and
  leaves the model column `not run`. Found by running the documented command in a
  shell that had no key — the exact way a reader would meet it.

- **`.env` is loaded, and the offline run does not read it.** `run.sh` sources
  `.env` for `serve`, `ask` and `eval`; `test` and `test-offline` skip it so the
  provider-free guarantee still means what it says. `.env` stays git-ignored, and
  `.env.example` carries the shape with no key.

Verification: `./run.sh test-offline` **1,260 passed + 3 skipped**;
`./run.sh test` with Ollama `bge-m3` **1,263 passed, 0 skipped**; `./run.sh eval`
with the hosted model **24/24 verdicts, 22–24/24 outcome agreement across three
runs**, and once rate-limited at 503 with the harness reporting it as
unreachable rather than agreement.

### Changed — 2026-10-28 · the model path runs against a local Ollama

The assistant's model-assisted path now works end to end against a local
OpenAI-compatible server, with no credential. The embedding path already used
Ollama (`bge-m3`); the criteria-extraction path did not, because three
assumptions held only for the one hosted provider it was built against. All
three are registered in `BUG.md` Part 2f.

- **A35 — a keyless server was treated as unconfigured.** `ModelConfig.configured`
  required `base_url and api_key and model`, so Ollama, llama.cpp and vLLM —
  which accept requests with no `Authorization` header — were unreachable. The
  fallback to rules was silent: no error, and no `fallback_reason`, because "no
  client" means "no model deployed" by design. The key is now optional and the
  header is sent only when one is set.
- **A36 — a thinking model spent the budget and returned `content: ""` with HTTP
  200.** `qwen3.5:0.8b` and `:2b` return empty at 2000 tokens; `:4b` answers but
  takes 41 s, four seconds inside the 45 s timeout. `reasoning_effort: "none"`
  turns thinking off on Ollama — `think: false` is ignored and `"low"` still
  thinks. The parameter is opt-in via `PAPERLANE_LLM_REASONING_EFFORT`, because
  the first provider returned empty content whenever it received it at all.
- **A37 — the documented comparison never reached the model.** `./run.sh eval`
  printed `model: not configured` whatever the environment held: the eval branch
  of `cli.main` never built a client, and the side-by-side table in
  `eval/results.md` came from a direct call during development. The branch now
  constructs `ModelClient(ModelConfig.from_env())` when configured and passes
  `None` otherwise, so the model-free run is unchanged.

**Measured, not assumed.** `qwen3.5:4b` @ `sha256:d8b0f5e9760c…` with
`reasoning_effort=none` answers in **0.5 s warm** (7.8 s on the first call while the model loads) and matches the best measured total accuracy: 20 of 24
identical totals, the same as `qwen3.5:9b` at 2.5× the latency; the
"big model is too slow" figure was the thinking path, not the size. The digest is
quoted because an Ollama tag is a mutable pointer: a later `ollama pull` of the
same tag changed the model's criteria on the same requests with no code change.
Over the 24 v1 cases the rules path and the model reach the **same outcome on
20**; all four disagreements are model vocabulary errors and the rules are right
in each — three are the model inventing `category: Copy paper` from the bare word
"paper".
A one-line prompt rule was measured and rejected: it fixed one case and broke
two. The rules path therefore stays the default, and the model remains a
decomposer whose output is re-resolved through the alias tables before use.

Verification: `./run.sh test-offline` **1,260 passed + 3 skipped**;
`./run.sh test` with the Ollama embedding provider **1,263 passed, 0 skipped**;
`./run.sh eval` 24/24 with `model: available` and a populated comparison column;
`--catalog v2` 21/21; held-out still 9/11 with two failures retained. Six new
model tests and two new CLI-wiring tests; the configured wiring test fails
against the old call with `KeyError: 'model_client'`.

### Changed — 2026-10-28 · the offline suite exercises loopback, and the provider tests run against Ollama

Two test-environment limitations were reported as skips, which made them look
like coverage gaps rather than something fixable. Both are fixed in the harness;
no test was weakened and no product code changed.

- **Five loopback tests did not run offline.** `unshare -rn` starts with `lo` down,
  so the two `test_ingest` collapse-gate tests and the three `test_mutate` `serve`
  tests skipped, and their behaviour was covered only by
  `./run.sh verify-refresh`. The namespace still has no route outside itself;
  `./run.sh test-offline` now brings `lo` up inside it (`ip link set lo up`,
  unprivileged in a user namespace), so the same five run while the offline
  guarantee is unchanged. Offline moves from 1,244 passed + 8 skipped to
  **1,249 passed + 3 skipped**.
- **The three provider tests skip whenever no server answers.** With
  `PAPERLANE_EMBED_BASE_URL=http://localhost:11434` and
  `PAPERLANE_EMBED_MODEL=bge-m3:latest` (Ollama, 1024-dim), the full suite is
  **1,252 passed, 0 skipped** in about 48s, with the mutated catalog present.
  They still skip under `test-offline`: the provider is a host process and the
  namespace's loopback is its own, so the only honest options are skip there or
  claim a network the guarantee forbids.

`run.sh` gained the `test-offline` subcommand, and its usage text now separates
"needs no model" from "needs no network". The three remaining skips are reported
in the summary, never counted as passes.

### Fixed — 2026-10-28 · a pound weight the table's own factor determines

The held-out set reported 8/11. Two failures are retained on purpose, because
neither has a fix that does not first invent a synonym or change the interpreter
contract. The third was fixable, and is closed here.

- **A34 — `30 lb` was dropped.** `_POUND_PATTERN` matched, `30` was absent from
  `POUND_TO_GSM`, and the unlisted branch returned `(None, None, None)` under the
  comment *"no conversion is defensible"*. That comment was right about a guess
  and wrong about this value: all four agreed rows share one factor — 75/20 =
  90/24 = 105/28 = 120/32 = 3.75 — so 30 lb is 112.5 gsm by the table's own
  arithmetic. `aliases.POUND_TO_GSM` now carries `30: 113`, rounded half-up, the
  rule the money path already uses. `normalize.POUND_TO_GSM` deliberately keeps
  the brief's four: it cross-checks a page stating both forms, so
  `30 lb (112 gsm)` must raise rather than be corrected to a value the page did
  not state. Unlisted pound values still return nothing, which stays an accepted
  risk in `BUG.md` Part 3.

Offline suite 1244 passed + 8 skipped at this commit; online 1249 passed + 3
skipped; `./run.sh eval` 24/24; `--catalog v2` 21/21; held-out **9/11**, with
cases 2 and 3 still failing on purpose. (The harness entry above later turned the
five loopback skips into passes, so the current offline figure is 1249 + 3.)

### Fixed — 2026-10-27 · a refresh could replace a good catalog with a collapsed one

The demo round supplies an updated site and asks for a re-ingest with no code
change. Probing that path with a rewritten copy of the site found the two failures
that matter most for it, both registered as `BUG.md` A31/A32 before either was
touched.

- **A31 — unknown availability read as in stock.** `extract._stock_state` treated
  any page that did not contain a recognised out-of-stock phrase as `in_stock`.
  When the availability wording changed, **all six affected rows silently became
  available**; nothing crashed and no review row appeared. Availability is now a
  closed set — `In stock`, `Out of stock … expected back <date>`, `Discontinued` —
  and anything else becomes `unknown` plus an `availability not recognised` review
  row, so the page is authoritative instead of the parser's default.
- **A32 — a collapsed crawl still swapped.** A structurally valid snapshot with
  almost no rows replaced the serving catalog. `ingest._swap_refusal` now refuses
  a swap when the new snapshot has zero SKUs or fewer than half the serving row
  count, exits **3**, and keeps the staging file for inspection. A first ingest is
  never refused, exactly half is allowed, and a genuine catalog cut passes
  `--accept-shrink`.

Both were reproduced first. Tests were seen to fail against the old code: three
for the availability set (`test_extract.py::TestUnknownAvailability`) and six for
the gate (`test_ingest.py::TestSwapGate`), plus two loopback tests for the
collapsed crawl. Full suite 1251 collected / 1248 passed + 3 skipped; offline
1243 passed + 8 skipped; `./run.sh eval` 24/24; `verify-refresh --keep` 12/12;
`eval --catalog v2` 21/21. The real 103-request ingest over HTTP still swaps 72
products against 72, with zero review rows.

### Fixed — 2026-10-27 · the brief audit's remaining eight defects

The section-by-section review of the brief's five "what we look for" areas found
eight defects beyond A20–A22, each reproduced against the running service and the
stored snapshot before being written down. All eight are closed:

- **A23** — a sibling variant's restock date was copied onto in-stock rows; each
  row's own availability cell now decides both status and date.
- **A24** — a budget stated per ream or per sheet was compared as if it were per
  pack; `comparable_unit_price` now converts by the pack's sheet count.
- **A25** — the stated budget basis was echoed without being constrained to one
  the engine can apply; a non-canonical basis is now rejected at the API boundary
  (422) and the canonical set lives in `pricing.BUDGET_BASES`.
- **A26** — the same SKU split across two lines missed its volume tier; the tier
  is chosen from the order's total for that SKU.
- **A27** — the free-delivery threshold was named only to the customer who had
  already met it; the reply now states the threshold and the shortfall.
- **A28** — "I could not find anything close" was said about an item that exists
  and is out of stock; the near match is kept and reported with its restock date.
- **A29** — a request naming two products was merged into one impossible request
  or half-answered; it now asks which one, rather than guessing.
- **A30** — the reply never said that a slightly larger order would cost less; the
  next tier is named when the total would fall.

Verification for the closing run: 1251 collected / 1248 passed + 3 skipped,
`./run.sh eval` 24/24, `verify-refresh --keep` 12/12, `eval --catalog v2` 21/21.
Each fix carries its failing run and its guard in `BUG.md` Part 2c.

### Fixed — 2026-10-27 · an unavailable line was quoted in a multi-line basket

`POST /api/quote/lines` priced `PL-CL-A4-100-IVY` (out of stock, back 20 November
2026) as available: `{"outcome":"quoted","figures":{...,"total":"340.26"}}`, with
no stock field. `/api/ask` and `/api/quote` refuse it correctly, because
availability is a **search-layer** filter — but the basket path prices known SKUs
through `pricing.quote()` and never consults the catalog. PR8 is unconditional, so
an unorderable item must not be quoted as available on any entry point.

The endpoint now checks stock itself. Any unavailable line refuses the **whole
basket** — quoting the rest and dropping the line silently would return a total the
customer reads as complete. The refused item is built by `search.make_candidate`
and worded by the shared `assistant.refusal_text`, so a refusal has one shape and
one wording wherever it is produced. The new `api._record_refusal` files it as
`refused`, not `failed`: the request was valid and the refusal is an answer.

Three tests were written first and run against the old handler; all three failed
`assert 'quoted' == 'refused'`. `tests/test_ui_catalog.py` was adapted — it posts
one SKU per request now, because a chunk containing an out-of-stock row refuses the
whole chunk — and still compares every row against the endpoint. Recorded as
`BUG.md` **A22**.

### Fixed — 2026-10-27 · a budget was compared on the wrong basis

Two failures of one requirement. PR7 says the assumption must be **stated and
honoured**; the code stated a label and compared before VAT regardless, and the
label itself was wrong when the customer wrote *"a pack including VAT"*.

- **A20.** `interpret._BASIS_PATTERNS` was one ordered list of alternatives, so
  `per|a|each pack` matched before `including vat` and the qualifier was dropped:
  `parse_budget("… under 240 a pack including VAT …")` returned
  `(240.00, 'per pack, before VAT')`. The list is now two questions — the unit word
  (`_UNIT_PATTERNS`) and the VAT qualifier (`_INCLUSIVE_VAT`) — composed by
  `_budget_basis`.
- **A21.** `check_budget` carried the basis as a footnote: with
  `basis="per pack, including VAT"` it still compared the ex-VAT 233.20 against a
  240.00 ceiling and returned `within_budget=True`, although the pack costs 249.52
  including VAT. `pricing.comparable_unit_price(facts, quantity, basis)` now
  returns the number the budget is compared **against** — gross when the basis says
  so — and `search._evaluate` and `assistant._quantity_changes_the_answer` both call
  it, so the filter, the reply and the clarification rule agree by construction
  rather than by three copies of one condition.

Both fixes had their tests written and seen failing first. One evaluation reply
changed, as intended: case 18 (*"budget 1500 including VAT"*) now states 111.96,
the VAT-inclusive figure it compared, where it stated 104.64 — the only one of the
28 whose reply differs. The single-turn digest was retaken with that justification
recorded in `tests/test_single_turn_unchanged.py`. Recorded as `BUG.md` **A20** and
**A21**.

### Fixed — 2026-10-27 · stored timestamps were local time wearing a UTC label

`/api/health` reported a catalog built three minutes earlier as
`age_seconds: -25098.7`, `"just now"`, `stale: false`. Two representations of the
same instant disagreed inside one file: `meta.built_at` held
`2026-10-27T09:30:09.402283+00:00`, `ingest_runs.finished_at` held
`2026-10-27 16:30:09.402283`.

DuckDB's `TIMESTAMP` has no zone and converts an aware datetime into the
**session** timezone before storing it, so `datetime.now(timezone.utc)` landed as
`Asia/Jakarta` wall time. Every reader does the opposite: `parse_stored_timestamp`
tags a zone-less value as UTC, deliberately, so a nine-hour-old catalog cannot
look fresh in a UTC+7 timezone. The catalog therefore read seven hours younger
than it was, and a snapshot built moments ago had a negative age — the freshness
signal could not fire for seven hours longer than configured, which is the one
job it has.

`catalog.stored_timestamp` now converts to UTC and drops the zone at all four
write sites (product and tier `crawled_at`, run `started_at`/`finished_at`). Naive
values pass through, documented as already-UTC. The conversion is in the writer
rather than in a session setting, so it does not depend on the host timezone. The
snapshot was rebuilt over HTTP at 1 req/s: both representations now agree and
`age_seconds` is `4.4`.

No price, stock state or answer changed. Recorded as `BUG.md` **A19**; three tests
were written first and failed by exactly 25200 s — the offset, not a rounding.
The two pre-existing freshness tests that caught it were not wrong, and were not
changed.

### Fixed — 2026-10-27 · `unit_word` held the volume-pricing note on four SKUs

`/api/products` returned `"No volume pricing for this item."` as the `unit_word`
for `PL-CL-LTR-24-BRT`, `PL-CS-A4-160-AST`, `PL-CS-A4-250-BLK` and
`PL-PH-A4-230-MT`. Those pages state the unit on the price line
(`Price: … 289.00 THB / ream`) and their only `.muted` element is the volume note.
`extract._unit_word` read `.muted` first and returned it, so the slash tail was
never reached.

The branch order was the bug, so the branch order changed: the slash tail is read
first when the price line has no `.muted` of its own, and `.muted` remains the
fallback for the layout that publishes its unit there. No check for the note's
text — a sentence-shaped unit would still be wrong, but only a structural fix
survives a copy change. Replies and the catalog column were never affected because
both use `pack_sheets` through `assistant.unit_phrase`.

The new test was run before the fix, against a real page copied into
`tests/fixtures/`: `assert 'No volume pr...or this item.' == 'ream'`. The snapshot
was then re-ingested over HTTP at 1 req/s, not edited in place: against the
previous snapshot, **4 product rows differ, all in `unit_word`**, plus the
`crawled_at`/`built_at` provenance that must move. 72 products, 105 tiers, 2 out of
stock, 1 on sale, 0 review items — unchanged. Recorded as `BUG.md` **A16** and
closed as **F-1**.

### Added — 2026-10-27 · the evaluation can name the catalog it scored

`run_eval()` has taken `catalog_name` since the second catalog existed, but the
CLI never passed it, so `./run.sh eval --db .refresh-verification/mutated.duckdb`
labelled the run **v1** and scored 17/24: the four v2 cases were skipped and the
seven v1-pinned cases were held against a catalog that had genuinely changed.
The 21/21 figure was real but reachable only by importing `run_eval` in Python.

`./run.sh eval --catalog {v1,v2}` now selects the catalog the expectations were
written for, defaulting to `v1` so the existing command is unchanged. Two
mismatches are refused with exit 2 rather than labelled wrongly: a conversation
set given `--catalog v2` (those cases carry no per-catalog expectation), and
`--catalog v2` with no `--db` (the committed snapshot is v1, so the run would
print a v2 label over v1 data).

Verified with the commands now written beside the claim:

```
./run.sh verify-refresh --keep
./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb   # 21/21, exit 0
./run.sh eval                                                          # 24/24, exit 0
```

`eval/results.md`'s second-catalog table was also stale — it predated the
interpretation axis — and is repasted from the current run. No pricing, model,
case file, or dependency changed.
`tests/test_evaluate.py::TestTheCatalogFlagOnTheCommandLine` pins the flag
reaching the runner and both refusals.

### Changed — 2026-10-27 · the split is half and half, and the catalog is a set of drop-downs

Reported from use: the left column could not show all of its categories. It was
a fixed-height scroller inside a sticky panel, so on a 900-pixel window the first
category filled the box and the other three sat below an inner scrollbar.

Three changes, each the smallest one that answers the report:

- **The two columns are equal tracks** — `minmax(0, 1fr) minmax(0, 1fr)`. The
  zero minimum is the part that matters: `1fr` alone is `minmax(auto, 1fr)`, so a
  long product name would widen its own column past the half and the split would
  stop being 50-50.
- **A category is a `<details>`** — native disclosure, no script, keyboard
  operable and announced as expanded or collapsed. Every group starts closed, so
  all four categories and their counts are on screen at once; opening one shows
  its products.
- **The panel has no height of its own** — the `max-height` / `overflow-y`
  scroller and the sticky positioning are gone, so content is no longer clipped
  and the page scrolls instead.

The click contract is unchanged: a row fills the search box and stops. It now
sits inside a disclosure, and the handler is delegated to `document`, so a row in
a group opened after load behaves exactly like one open at load. No new endpoint,
no dependency, and no client state beyond that prefill.

**The clipping was a defect; the 50-50 half was a preference.** `BUG.md` records
it as **A18**. Every row was already in the response, which is why all 19 tests in
`test_ui_catalog.py` passed while the column showed one of its four categories:
a DOM assertion cannot see a scrollbar. The equal split is implemented as asked
and is not claimed as a bug.

`test_ui_catalog.py::TestTheCatalogIsCollapsible` (5) and
`TestTheSplitIsHalfAndHalf` (2) pin the structure; the escaping, price-parity and
"every name resolves" tests run against the new markup unchanged. Checked in a
browser at 1440×900 and 390×844 — four categories and their counts on screen at
once, opening one pushes nothing out of the document, and a row inside a group
opened after load fills the search box and sends no request. Suite 1183 → 1190,
and every recorded count moved with it (`README.md`, `TEST.md`, `CLAUDE.md`, the
status line above).

### Fixed — 2026-10-27 · a bare quantity that is also a grammage no longer changes the paper

Reported from use, as a five-turn conversation. *Change it to 50* quoted; *change
it to 100*, then *60*, then *50* again all came back as no-match — including the
last turn, which restated a quantity that had already quoted. Registered as
**A17** in `BUG.md` Part 2b before the fix.

Two correct rules met on the number 100. The weight parser reads a bare number as
a grammage when the catalog stocks it (*A5 gloss 130* needs no unit), and the merge
reads a bare number in a refinement as the quantity. Turn three therefore set both:
100 packs **and** 100 gsm. The weight stuck, so every later turn carried it;
returning to 50 changed the quantity but not the paper.

`aliases.bare_grammage` now exposes the question `Criteria` loses — was the weight
read from a bare number or from a unit — and `merge_turn` reclaims the number when
it is the one the turn just adopted as its quantity. Interpretation stays per-turn
and model-independent (D1); the decision sits beside the bare-quantity rule that
already lived there. An explicit *100 gsm* still corrects the weight.

- `tests/test_aliases.py::TestBareGrammage` (7), three merge tests, and
  `test_conversation_api.py::TestABareNumberThatIsAlsoAGrammage` (3), which replays
  the reported sequence and asserts the recovered total.
- `eval/conversation-cases.json` case 12 scores the same sequence.
- `test_conversation.py` also pins that refinements past the retained-history cap
  still carry the full requirement set: 20 refinements with `max_turns=3` keep the
  category, size and weight. "How many changes can I make?" has no answer bounded
  by the store. Measured against a live server as well: 101 turns in one
  conversation, 100 of 100 refinements quoted, every total identical to a fresh
  standalone quote for the same SKU and quantity, and turn 101 still knew it was
  160 gsm A4 card. The only quantity ceiling is the request contract (1..100,000):
  the catalog carries no stock count, only in/out of stock.
- **Falsification:** reverting the merge change fails 4 of the new tests and leaves
  the explicit-weight guard passing.
- No capability spec changed. The conversation spec already said a bare number in
  a refinement is the quantity; the code was not doing what it said, so the fix
  restores the stated behaviour rather than adding a new one.
- `docs/conversation-memory.md` states the ambiguity and the reclaim rule, and
  `README.md`'s conversation counts move from 11 conversations / 24 turns to
  12 / 27.
- The suite is 1183 tests, up from 1169; the conversation set is 12 conversations
  over 27 turns.

### Changed — 2026-10-27 · the page is a catalog list beside the assistant

The interface was one narrow column: a search box and a result. It is now two —
the catalog on the left, the assistant on the right — because the brief asks for
product discovery, and someone who does not yet know the catalog's vocabulary had
no way to find out what exists short of guessing a phrasing.

**Scope, stated plainly.** The brief's only UI requirement is must-have 6, *"An
API … and a simple UI or CLI"*; no capability spec constrains layout. A browsable
list is therefore an addition, not a compliance fix, and it earns its place in one
line: the catalog is the thing being searched, so showing it is the cheapest way
to make an unknown catalog legible. It is presentation over data the API already
served — no new endpoint, no new query shape, no new dependency.

**What a click does, and what it deliberately does not.** A row fills the search
box and stops. It does not submit, so it cannot spend a model call or invent a
quantity, and there is still exactly one way an answer is produced. The name in
`data-request` is the product's own name, verified for **all 72** to resolve back
to that product through the interpreter: 70 quote it, and the 2 out-of-stock items
are refused by name. A test holds that, because "most names work" is the kind of
claim that rots the moment the catalog changes.

**The price on a row is the quote's price.** It is `pricing.unit_price` at
quantity 1, not `list_price_satang`, because a sale price replaces the list price
*and* every tier (PR3). One SKU sells at 259.00 against a 299.00 list; a column
built from the stored list price would advertise a figure the assistant then
refuses to honour. The agreement with `/api/quote/lines` is asserted, not
intended. The column says "each, before VAT, at quantity 1" for the reason
recorded as **T1**: the one misreading it must not invite is comparing a unit
price against a budget at another quantity.

- `render_catalog` in `ui.py`: grouped by category, every field escaped, an
  out-of-stock label, and three states — products, empty snapshot, no snapshot.
- `GET /` loads the list. With no snapshot it renders the remedy on the page
  instead of failing, because the page is where someone looks; a corrupt or
  unreadable snapshot still raises, which is an operational fault rather than a
  state to paper over.
- CSS grid, collapsing to one column below 900 px with the search first. No new
  asset, no CDN, no framework: the vendored htmx is still the only script.
- `tests/test_ui_catalog.py`, 19 tests. **Falsification:** pricing from the stored
  list price fails 2, dropping the escape fails 1, removing the missing-snapshot
  branch fails 2 — each verified and restored.
- While building it, `unit_word` was found to hold "No volume pricing for this
  item." on four SKUs: those price boxes have no unit element, so the extractor's
  `.muted` fallback picks up the volume note and never reaches the `/ pack` tail.
  The column uses `pack_sheets` — the rule the reply already used, now shared as
  `assistant.unit_phrase` so the two cannot drift. The extraction defect is
  registered as **A16** in `BUG.md` and left **OPEN**, because fixing it changes
  the committed snapshot and belongs in its own change.
- The suite is 1169 tests, up from 1150.

### Fixed — 2026-10-27 · the page no longer depends on a CDN, and its deployment is documented

Found while answering a question the README could not: *how do you serve the
UI?* It could not answer because there was no deployment section at all —
`--host`, `0.0.0.0`, reverse proxies and TLS appeared nowhere — and reading
`ui.py` to write one turned up a worse problem than a missing paragraph.

**The defect.** The page's only script came from `unpkg.com`, and the form is
htmx-only: `hx-post` with no `method` and no `action`. With no internet the script
never loads, the browser falls back to a `GET` of the current URL, and pressing
**Ask** reloads the page and discards the input. No error, no request, nothing in
a log. Every `curl` check kept passing, because the JSON API never needed htmx.

The uncomfortable part is *why* the test suite could not see it. Offline is a
property this project verifies obsessively — `unshare -rn`, no model, no
provider — but it was verified for the assistant and never for the page. "Runs
offline" had been checked everywhere except the one surface a human touches.
It is registered as **A15** in `BUG.md` Part 2b.

**The fix.** htmx 1.9.12 is vendored at `src/paperlane/static/htmx.min.js` and
served same-origin from `GET /static/htmx.min.js`. The bytes are provably the
ones the CDN was serving: their SHA-384 is the same value the page carried as its
Subresource Integrity hash, and `static/VENDOR.md` records it with the licence
and the reason. A missing asset returns 500 with a remedy, not an empty 200.

- `tests/test_ui_offline.py` — 9 tests. No external host in the markup, the
  same-origin script tag, *the form is still htmx-only* (the premise the whole
  argument rests on), the exact bytes and content type, a cache header that is
  not `immutable`, absence from the OpenAPI paths, hash equality end to end, and
  `VENDOR.md` still describing the shipped file. Reverting to the CDN tag fails
  three of them — verified, then restored.
- Wheel packaging checked, not assumed: `uv build` includes `static/htmx.min.js`,
  and an installed-wheel copy serves all 48,101 bytes.
- `README.md` gains **Deploying the UI**: the routes, `--host`/`--port`/`--db`,
  the offline guarantee and what used to break, an nginx example with TLS and
  basic auth because the app has neither, what the server prints at startup, and
  why it is one process rather than a worker pool.
- The suite is 1150 tests, up from 1141. Every recorded count was updated
  (`TEST.md`, `CLAUDE.md`, `README.md`, the status line above) — a stale count is
  the same class of defect as a stale hash.

**What this is not.** Not a no-JS fallback. The page still needs JavaScript to
submit; making `POST /ask` return a full document to a non-htmx caller would
change the response contract and the tests around it, and the brief asks for one
simple interface, not a progressive-enhancement exercise. Stated as a limitation
rather than left implied.

### Added — 2026-10-27 · `add-gap-closure` (acting on the gap analysis)

The OpenSpec change is 5/5. This closes the three findings in the gap analysis
that sat inside the brief's scored areas, and answers the rest in
`devx_FDE_A3_Product_Discovery/GAPS_RESPONSE.md`.

**Why this and not everything.** `GAPS_ANALYSIS.md` reviews the finished system as
a **production** sales assistant. Read that way most of what it finds is real, and
most of it is out of scope: the brief states PR1–PR8 are *"the customer's agreed
specification"*, so reconciling them against a real supplier's tax policy, quote
expiry or order workflow would contradict the brief rather than improve the
submission. Three findings were inside the brief's scored areas and are now
closed. The refusals are argued in the response document rather than left implied,
because a take-home that quietly expanded to cover a production security review
would fail the part of the brief that scores scope judgment.

**A fifth scoring axis: was the request understood?** The harness had four axes —
retrieval, match, pricing, reply — and none asked whether the request was *read*
correctly. Validating criteria is not validating the reading of them: an A4 request
misread as A3 produces typed, in-range criteria drawn from a known vocabulary and a
perfectly correct quote for something nobody asked for. Every criterion can be
individually valid while the *set* is wrong, so no existing axis could see it, and
a misread surfaced as a retrieval failure — naming the symptom and hiding the cause.

- `interpretation` is now the **first** member of `AXES`, because it is the
  earliest thing that can go wrong.
- A case declares `expect.criteria` — a **subset** of the fields the request
  states — and `expect.absent_criteria`, what it must **not** invent. Two
  directions, because they are different defects; "under 250 a pack" becoming
  "80 gsm or lighter" is the second kind, and a subset check alone would miss it.
- The declared set is deliberately **never** a transcription of
  `criteria.describe()`. That would be the engine agreeing with itself, the same
  anti-pattern `recompute_totals` avoids for money. A test asserts every case's
  declared set is smaller than what the engine derives, or declares an absent
  field, so the axis can always disagree independently.
- A case recording no criteria reports `n/a`, not pass. Counting the unexamined
  as correct is how an axis reports a sweep it did not earn.
- `self_check()` gained three checks, including one that corrupts a derived size
  and asserts interpretation fails **while** retrieval, pricing and reply stay at
  pass.
- `negative-control.json` gained a fourth corruption on the new axis — case 10's
  `20 lb → 75 gsm` conversion recorded as 70 — and it fails on interpretation
  **alone**. The products and the price are the engine's own and correct; only the
  reading is wrong, which is the finding reproduced as a test.

**A held-out set the rules were never tuned against.** The analysis's sharpest
point: *"a system may pass its 28 ranking cases while performing poorly on new
requests, unfamiliar phrasing."* True — all 28 recorded cases were written while
the rules path was being built and were used to fix it, which makes them a good
regression set and a biased estimate of unseen behaviour. `eval/held-out-cases.json`
is 11 requests in phrasings that appear nowhere in `cases.json`.

- Expectations are derived by filtering the committed catalog directly and
  applying the **documented** ranking chain (availability, then effective unit
  price at the requested quantity, then sku) — never by reading the engine's
  response. Deriving a SKU set from `run_case()` and writing it down would make the
  set a recording of current behaviour, bugs included.
- It is a separate file, not cases 29+. Once a case is in the regression set it
  gets fixed against like the others, and the held-out property dies quietly in one
  commit. A test asserts a default `./run.sh eval` does not load it.
- **It fails, and the failures are kept.** 8 of 11 pass; 3 fail from one root
  cause — an unmappable noun is dropped rather than honoured, so the answer
  silently widens. *"the pink A4 coloured paper, 2 packs"* reads the shade as
  `None` and quotes all seven A4 coloured papers (price moving with it); *"pastel
  grey A4 paper"* returns all 33 A4 papers when nothing grey is stocked; *"30 lb
  letter paper"* returns all 19 letter papers. A test asserts at least one failure
  **remains**, because a held-out set that passes completely is evidence about its
  author.

**Freshness, reported and never gating.** The analysis: *"the pricing engine can
calculate perfectly using outdated prices."* Worse than it looked — `health()`
reported counts and `metrics` reported five measures, and none reported the
catalog's **age**, so a twelve-day-old catalog and a fresh one rendered
identically. Now `age_seconds`, `age_human` and `stale` are derived from the
ingest timestamp and surfaced on `GET /api/health`, in the snapshot block of every
API response, in `./run.sh metrics`, and at `serve` startup. The threshold is a
named constant (`STALE_AFTER_HOURS`, 24, overridable by
`PAPERLANE_STALE_AFTER_HOURS`).

- The stored timestamp is zone-less. The crawl stamps it with
  `datetime.now(timezone.utc)` and DuckDB returns a naive `TIMESTAMP`, so reading
  it as local time in a UTC+7 deployment would make a nine-hour-old catalog look
  minutes old. It is read as UTC, and a test asserts that.
- An unknown age is `None`, not `False`. "Not stale" and "cannot tell" must not
  read the same. Same rule as `criteria.py`: absent is not negative.

**Ingest into a named snapshot, so an unseen site can be demonstrated live.** The
demo round supplies an updated site and asks for a re-ingest. `ingest` already
discovered categories from the home page and took `--base-url`/`--rate`, so the
real gap was the **snapshot path**: a live re-ingest would have overwritten
`data/catalog.duckdb`, the file the recorded expectations are written against.
Now `ingest` takes `--db` (and `PAPERLANE_DB`), and `serve`, `eval`, `ask` and
`metrics` accept the same, all resolving through one `resolve_db_path`. Without the
flag every path is `data/catalog.duckdb` exactly as before. The property is
asserted by comparing the committed file's **bytes**, not its size or mtime, which
a rewrite would pass.

**`GAPS_RESPONSE.md`** answers every finding in `GAPS_ANALYSIS.md` with one of four
verdicts — closed, already closed, out of scope by the brief, or not fixable in
kind — and names the reason. Two refusals are argued in full: the hard
completeness gate (it would fail the demo round's live re-ingest, refusing to
publish in the room) and tax/quote-expiry/concurrent-price-change reconciliation
(the brief defines PR5 and PR4). The architectural blind spot — internal
consistency is not external truth — is accepted as a limitation rather than
papered over, because no internal check can establish a fact about the outside
world without a second source, which the brief rules out. `GAPS_ANALYSIS.md` is
committed alongside it so every citation resolves.

#### Fixed — a scorer bug found by the held-out set, on its first run

`_same_value` compared derived criteria to expected ones with a case-sensitive
string equality, so a case recording `"White"` failed against the engine's
`"white"` — a mismatch of the catalog's capitalisation, not of the reading. Found
by **running the held-out set**, where case 6 reported
`interpretation: colour_shade expected 'White', read as 'white'` on a case whose
product and price were both right. Comparison is now case-insensitive
(`casefold`), so the axis fails on a wrong reading rather than on spelling. A
genuinely different value still fails, and a test asserts the misread case still
does.

#### Changed — two case files, and the recomputation behind each change

- **26 of 28 cases in `eval/cases.json` and `eval/negative-control.json` now carry
  `expect.criteria`** (cases 16 and 27 are `multi_line`, priced through a different
  endpoint, and are `n/a` on this axis by design). The criteria were **injected
  from the request text and verified against the engine's derivation**, then six
  over-declared cases (10, 11, 12, 13, 17, 25) were trimmed to the field(s) that
  carry the case's meaning — because a test asserting the declared set is a
  *proper* subset caught cases 10 and 11 declaring exactly what the engine derives,
  which is the transcription D2 forbids.
- **`negative-control.json` now has four corruptions, not three** (cases 4, 6, 10,
  14). The fourth is on the new axis. The `_comment` names all four, and the
  tests assert `failed: 4` rather than `failed: 3` — recomputed from the run, not
  transcribed.
- **One dead constant removed.** `EXPECTED_CATEGORIES = 4` in `ingest.py` was
  never read: categorisation is decided from the crawled rows, and the constant
  would have been a second, silently-wrong source of truth had it ever been used.

**Verification.** 1141 tests pass offline under `unshare -rn` (7 skip, 0 fail), up
from 1095 — the increase is 31 tests across the two new modules plus 15 in
`test_evaluate.py`, all gathered by `--collect-only` rather than estimated.
`./run.sh eval` is 24/24 and the conversation set 11/11, unchanged. Both negative
controls exit 1; `./run.sh eval --self-check` exits 0 with the three new checks;
`./run.sh eval --cases eval/held-out-cases.json` exits 1 with 8/11. The
single-turn digest is unchanged, so no reply text moved.

---

### Added — 2026-10-27 · `add-conversation-memory` (the brief's third nice-to-have)

The OpenSpec change is 54/54. This is the seventh and last of the extras, and it
started as a nice-to-have rather than a Tier 2 item: the brief lists "conversation
memory" among its optional items, and `ANALYZE_01.md` §8 cut it deliberately with
the reason *"single-turn + explicit clarify beats half-built memory."*

**That reasoning is about a half-built memory, and it is right about that.** A
store that accumulates state without a rule for discarding it produces
confidently wrong answers, which is worse than asking again. The scope cut was
correct about the failure mode and wrong about the conclusion, because the second
most natural thing a customer says is a refinement, and the assistant could not
hear it: *"make it 50"* returned a clarification instead of a quote.

**What was built.**

- `src/paperlane/conversation.py` — the merge rule as a pure function over two
  `Criteria` objects, an in-memory store bounded to 100 conversations and 20
  turns each, and an optional JSONL-backed store for a restart-surviving demo.
  The store holds `Criteria`, **never the customer's text**.
- The merge is wired between `interpret` and `validate` in `api.py` and
  `ask_cli.py`, so a merged value the catalog cannot stock is caught by the same
  check that guards a fresh request.
- `./run.sh ask --conversation <id>` and `--forget`, plus the page, which starts
  a conversation per load and shows the turn number and what was remembered.
- `eval/conversation-cases.json` — 11 recorded conversations, 24 turns — and
  `conversation_eval.py` to score them.
- `docs/conversation-memory.md` — the rule, the bounds, the two stores, and the
  one thing a conversation id is not.

**The rule, and the decision that took two attempts.** A turn is a *continuation*
when it names no new **subject**, and a subject is a category or a size — the two
fields that name *which thing* is being discussed:

```python
SUBJECT_FIELDS = ("category", "size_code")
```

Weight is deliberately **not** a subject field. *Make it 100 gsm* adjusts the
paper already under discussion; including weight in the predicate was the first
version and it was wrong, because it made the refinement discard the size and the
category it was refining.

**The structural decision, which is the one that matters.** The model never sees
the conversation. The merge happens **after** interpretation, over typed
`Criteria`, and only the current turn's text ever reaches an interpreter. So every
constraint in a merged result is traceable to a turn that stated it. The
alternative — passing the transcript to the model — reads better in a demo and is
untestable: there is no assertion that distinguishes "the model remembered" from
"the model made it up". The cost is real and documented: *"the cheaper one"* with
no subject is a fresh request rather than a reference.

**Off by default, and that is asserted.** With no `conversation_id`, the single
turn path is byte-identical to before the feature existed. That is not claimed
from inspection: `tests/test_single_turn_unchanged.py` pins a **SHA-256 of every
case's `{outcome, text}`**, recorded from commit `d4a67db` — the commit before the
conversation work — with 0 differences across 28 cases. If that test fails, the
question is not "update the digest"; it is "which reply changed, and why".

**Verification.** Conversation eval 11/11 over 24 turns; single-turn replay 22/22
comparable cases unchanged (6 not comparable); the conversation negative control
exits **1** with all five deliberate corruptions rejected. 1095 tests pass, eval
24/24 on v1 and 21/21 on v2, `verify-refresh` 12/12. Every command in
`docs/conversation-memory.md` was run as written.

#### Fixed — three defects found after it shipped, all in conversation memory

Found by **probing the running service** rather than by reading the module, and
registered in `BUG.md` Part 2b *before* being fixed, per that file's own rule.
Each fix arrived with a test **and** a falsification check: the fix was reverted,
the new test and evaluation case were confirmed to fail, and the fix restored. A
guard that has never been seen to fail is a guess.

- **A12 — a first turn stating only a quantity, or only a budget, could not be
  continued.** `has_any_constraint()` is False for those turns, and gating the
  *earlier* criteria on it threw the conversation away. **Found by** asking
  *"20 reams"* and then *"make it 50"*. Fixed by replacing the narrow predicate
  with the broader `_states_something`, now the only continuation basis, at all
  four call sites. Pinned by eval cases 9 and 10 plus unit, HTTP and CLI tests.
  Falsified: restoring the old predicate fails exactly cases 9–10 and exits 1.
- **A13 — one unparseable turn permanently erased the conversation.** *"A4 80gsm
  copy paper, 20 reams"*, then *"too expensive"*, then *"make it 50"* clarified
  instead of quoting. **This one was D3 working as written**, so fixing it meant
  answering a question the decision left open: an empty turn is now *fresh for the
  reply* and *transparent for the state*. `MergeResult` carries `empty` and
  `record_turn` keeps the criteria while still appending the turn. A turn that
  *names a subject* still replaces the criteria, so D3's protection against a
  wrong carry is untouched. Falsified: restoring the old `record_turn` fails case
  11 with `criteria['category'] is None, expected 'Copy paper'`.
- **A14 — the turn number saturated at 21 and stopped distinguishing turns.**
  `turn_index` derived from the retained turn list, which is capped at
  `MAX_TURNS`. **Found by** running 25 turns and reading the numbers. Fixed with a
  persisted `turns_seen` counter: `turn_index = max(turns_seen, len(turns)) + 1`.
  25 turns now write 1…25.

### Added — 2026-10-26 · `add-observability` (Tier 2, third of three)

Closes tasks 10.6 and 10.7 of `add-paperlane-product-discovery`. The OpenSpec
change is 28/28. **All six Tier 2 extras are now built**, and the Tier 1 change
stands at 86 of 86 tasks closed.

**The problem.** The assistant answers correctly or incorrectly with no
operational signal either way. A model that silently degraded to the rule path
looked identical to a model that was working; a catalog gap looked identical to
a parsing defect. Neither would have been noticed by a customer complaint —
which is the wrong way to find out.

**What was built.**

- `src/paperlane/records.py` — one structured JSONL record per handled request:
  endpoint, interpretation path, whether a model was configured, the fallback
  reason, outcome, candidates considered, items returned, the quoted total, the
  total the reply **actually printed**, per-stage timings, snapshot identity,
  request length and digest. Frozen, and validated at construction.
- `src/paperlane/metrics.py` — the five measures, all derived from records on
  every read. No counter is incremented while a request is handled.
- `GET /api/metrics` and `./run.sh metrics` — the same payload from the service
  and from the command line.
- `docs/observability.md` — the schema, the five measures with their alarm
  thresholds, and the limitations.

**Three definitional choices that make the measures mean something.**

- **`fallback_rate`'s denominator is model-eligible requests only.** A
  deployment with no model configured answers everything with rules, and that is
  correct behaviour. Counting it as fallback would make the metric permanently
  alarming, and a permanently red metric is an ignored metric.
- **`zero_result_rate` excludes clarifications and refusals.** A clarification is
  the system correctly declining to guess; a refusal is the system correctly
  declining to sell. Counting either as a miss would make the metric measure
  questions rather than failures.
- **p95 is nearest-rank, not interpolated.** With a small window an interpolated
  p95 reports a duration between two observed requests — a number no request
  experienced.

Every rate returns `null` rather than `0.0` on an empty basis, and the payload
carries `record_count`, `window`, `has_data` and a `note`. A rate of 0% over 0
requests and a perfect run are opposite findings and must not print the same.

**The disagreement metric, and why it is the one worth having.** The reply
contract is *supposed* to make a reply whose printed total differs from the
computed total impossible. "Supposed to be impossible" is exactly the claim that
should be measured. For every record whose reply printed a total, that figure is
parsed from the rendered text and compared against `evaluate.recompute_totals()`
run on the same SKUs and quantities — independent integer arithmetic, separately
asserted by AST inspection not to call `quote()`. So it compares two
implementations, not a reply agreeing with itself.

The tempting version — compare `reply.total` against `reply.quote.total` — is
worthless, because both come from the same object and always agree. It is
structurally incapable of failing, and a test asserts the shipped version does
not read `quoted_total` at all.

**Observed: 0 disagreements over 17 checked replies** on a real `./run.sh eval`
run. The metric reports how many replies it *checked*, not just how many
disagreed, because "0 over zero checked" and "0 over seventeen" are opposite
findings that would otherwise print identically. A record that stated a total
but cannot be re-derived is reported as a disagreement *with a reason*, not
skipped — dropping the uncheckable records would make the metric look better the
less it was able to do.

**A defect the credential test found, which is the reason the test exists.** The
first version of `TestNoCredentialInRecords` failed: a model client that raises
with its own key in the message had that message travel through `interpret` into
`fallback_reason` and into the record. Redaction now happens in the record's own
constructor, in two passes — configured key values replaced literally, then
credential-shaped patterns — so no caller can bypass it by forgetting. The
realistic leak was never a field someone added for a key; it was an error
message.

**Two design corrections, both recorded rather than quietly made.**

- `ANALYZE_01.md` §9a specified logging the raw request text. The observability
  spec forbids retaining conversation content by default. **The spec won** — it
  is the later and more considered artefact, and `AGENTS.md` ranks it above the
  analysis. What shipped is `request_chars` and a 16-character `request_digest`,
  with text capture as an explicit opt-in (`PAPERLANE_RECORD_TEXT`, bounded by
  `PAPERLANE_RECORD_TEXT_MAX`, default 200). Recorded as defect A11 in `BUG.md`.
- **The harness writes to its own log.** The first version had `./run.sh eval`
  append 24 records to `data/requests.jsonl`, which would drag the live fallback
  and zero-result rates toward whatever the case list emphasises — and the
  negative control, whose purpose is to fail, would have poisoned them outright.
  The harness now writes `data/eval-records.jsonl`, each run stamped with a
  `run_id`, and `metrics --eval` reports **the most recent run** rather than a
  union of runs. Verified: two runs plus the negative control leave 48 lines in
  the file and 24 records in the report.

**A test-isolation defect found by the suite itself.** `api.py` ends with
`app = create_app()`, so an eagerly resolved record writer bound at import —
before any fixture could set `PAPERLANE_RECORD_PATH` — and 32 records from the
test run landed in the real `data/requests.jsonl`. Resolution is now lazy and
cached **per configured path**, so the failure counter survives across requests
without one test's records landing in another test's file. An autouse fixture
redirects both logs to `tmp_path`; the suite now leaves both files absent.

**Verification.** 937 tests pass offline under `unshare -rn` (7 skip: the
loopback and embedding ones), and 937 online (4 skip); eval 24/24 on v1 and
21/21 on v2; `--self-check` exit 0; negative control exit 1; `verify-refresh`
exit 0 with all 12 changes verified; `./run.sh similarity` exit 0. Every command
in `docs/observability.md` was run as written and its quoted output copied from
the run. *(Count as at this entry; conversation memory later took the suite to
1095 — see the entry at the top of this section.)*

### Added — 2026-10-26 · `add-semantic-tiebreak` (Tier 2, second of three)

Closes task 10.5 of `add-paperlane-product-discovery`. The OpenSpec change is
26/26. Tier 2 now stands at five of six extras built; only the observability
change remains.

**The problem.** Search was hard filtering plus a deterministic ranking whose
only price-independent term was the SKU. Two items that both match "A4 80gsm
copy paper" were ordered by SKU, which is arbitrary from the customer's point of
view.

**What was built.**

- `src/paperlane/embeddings.py` — an optional client for a local embedding
  server, a per-snapshot cache, and cosine similarity as a dot product. No
  credential is read or sent; there is no API-key setting to leak.
- The similarity term enters the ranking as a **tiebreak**, and only as one:
  it scores candidates that have already passed every hard constraint, so there
  is no code path from a score to membership. That is the whole safety
  guarantee, and it is structural rather than careful.
- `./run.sh similarity` — a measurement command that runs every recorded case
  with the term off and on and reports counts.

**The measured result, which changed a decision.** The design put similarity
*before* price, verified on the machine and recorded in `design.md`. Measured,
it reordered 13 of 28 cases and moved the expected first result in 9, with **0
improvements and 6 regressions**. Case 26 showed it plainly: `PL-CP-A4-70`, the
cheapest qualifying item, fell to fourth — contradicting the system's own stated
rule that the cheapest qualifying item ranks first, and the spec's scenario
"similarity does not override a stated preference for cheaper".

The term was moved **after** price. Re-measured: 3 of 28 cases reorder, 0 first
results change, **0 improvements and 0 regressions**. Three reorderings are ties
on price among equally-valid items, which is exactly what a tiebreak is for.
Case 25 swaps two A4 80gsm coloured papers at the same price; the order carries
no correctness claim either way.

So the honest finding is that the feature is a *better* tiebreak than SKU order,
not that it improves answers. `README.md`, `docs/search.md` and
`docs/semantic-ranking.md` all say zero rather than dressing it up.

**Two corrections the work forced, both recorded rather than quietly made.**

- The design specified a **2s** embed timeout, from warm-only measurements. A
  cold model load costs 2.0s for one text and 2.8s for all 72, so a 2s timeout
  failed the first request after every restart — the feature degraded on first
  use and looked broken. Now 10s, with the cold/warm figures in the docs.
- `_relax` truncated to five alternatives *before* returning them, so enabling
  similarity changed which five a reviewer saw. That is a display cap, not
  membership, but the two were indistinguishable from the outside. Truncation
  moved to the caller, and the invariant is now tested against the full
  qualifying set — which is why the test compares `_relax` output rather than
  the reply.

**A bug the tests caught in the measurement command.** `render()` accepted an
`out` stream but only honoured it on the "not measured" branch; every count went
to stdout regardless. Found by asserting on a captured buffer instead of
eyeballing console output.

**Verification.** 765 tests pass offline (7 skip under `unshare -rn`); eval
24/24 on v1; `--self-check` exit 0; negative control exit 1; `verify-refresh`
exit 0. With no provider configured, the `/api/quote` response has **no**
`semantic` key and candidates carry **no** `similarity` field — verified
directly, so the unconfigured path is the old response shape rather than merely
an old ordering. With a dead provider the request is still answered with HTTP
200, `semantic: "unavailable"`, and the same total.

### Added — 2026-10-26 · `add-mutated-site-refresh-harness` (Tier 2, first of three)

Closes tasks 10.4, 11.4 and 10.3 — 83 of 86 now closed. The remaining three
(10.5, 10.6, 10.7) belong to the other two Tier 2 changes.

**The problem.** `./run.sh diff` reports six change kinds, and on the committed
catalog all six are empty. An empty report is equally consistent with a correct
diff, a diff that reads nothing, and a diff that reads the wrong thing. The v1
catalog contains no adversity — every page parses, nothing is discontinued, no
page carries an injected instruction, no price has ever changed — so the refresh
path could not be exercised, and "the diff works" rested on reading the code.

**What was built.**

- `src/paperlane/mutate.py` — copies the site, injects **twelve declared
  changes** across all six kinds plus the parse-failure kind, and emits a
  manifest of exactly what it injected. Generation is deterministic (two runs
  produce byte-identical trees); the source site is never written to.
- `src/paperlane/refresh.py` — serves the mutated copy over loopback, ingests it
  into a throwaway snapshot, diffs that against the committed baseline, and
  verifies the report against the manifest **in both directions**.
- `src/paperlane/refresh_cli.py`, `./run.sh verify-refresh` — the command, with
  distinct exit codes: 0 verified, 1 discrepancy, 2 could not run. About 55s.
- `tests/test_mutate.py` — 77 tests. The generator is test tooling whose only job
  is to be trustworthy, so the tests are about its honesty: faithful copy, source
  untouched, determinism, every injected page reachable by the crawler's own
  selectors, and six **distinctly named** verification failures.

**What the injections make demonstrable for the first time:** a discontinued item,
an injected instruction, 28 lb and 32 lb conversions, a budget met exactly, a
subtotal exactly at the delivery threshold, an unparseable page reaching the
review floor, and a catalog that shrinks.

**Second-catalog evaluation.** The mutated snapshot is a second catalog the
evaluation set runs against. Cases 21–24 (discontinued, injection, 28 lb, 32 lb)
were recorded as not applicable; they now **run and pass** on it. Inapplicability
became a fact about a *named* catalog (`requires_catalog`) rather than a
permanent verdict, and a run now records which catalog it scored. Seven cases are
pinned to v1, because their expected product sets enumerate v1's exact offering
and rewriting them from v2's output would make the expectation circular.

**A real defect this exposed.** Scoring against v2 immediately failed cases 4 and
5 with `reply: names absent product(s)`. The reply was not hallucinating — the
*scorer* was: `_score_reply` and `_score_match` validated mentioned SKUs against
the committed snapshot regardless of which catalog was under test, so every
v2-only SKU looked invented. A single-catalog run could never have found it,
because the two catalogs were always the same object.

**A documentation defect found while verifying the doc.** `README.md` and
`docs/refresh.md` said to serve the site with `(cd .. && python3 -m
http.server 8000)`. That serves the parent directory, so `/paperlane/` returns
404 and ingest fails. Both corrected; verified by running the command as written.

**Verification.** 682 tests pass offline (4 tests skip under
`unshare -rn`); eval 24/24 on v1 and 21/21 on v2; `--self-check` exit 0;
negative control exit 1; `verify-refresh` exit 0 with all 12 changes verified;
`--drop-entry` exit 1 with the discrepancy named. A re-ingest of the real
site reproduces the committed snapshot's contents exactly — 72 products, 105 tier
rows, identical `meta`, 0 review items — with the file's bytes differing only in
the crawl timestamps recorded in provenance columns.

### Added — 2026-10-26 · Planning

#### Analysis

- `ANALYZE_01.md` — 1,688 lines, 12 sections. The evidence base for every design decision:
  - §0 locked decisions; §0a the six-hour-brief-versus-three-day-build scope framing
  - §1 ground truth on the site; §2 the traps that decide the score
  - §3 stack verdict with rejected alternatives; §4 target architecture
  - §5 pricing engine; §6 refresh path; §7 the 28-case evaluation matrix
  - §8 the three-day plan; §9 rubric mapping; §9a logging and metrics
  - §10 open questions; §11a brief-coverage traceability; §11b round-2 gap audit; §12 verification log
- Site inspection of all 36 product pages, 59 volume-pricing documents, 7 category pages, `delivery.html`, `robots.txt`, and `assets/tiers.js`. Findings recorded as verified facts rather than assumptions.
- Runtime verification of the two riskiest dependencies before committing to them:
  - **LLM endpoint** — authentication, chat completions, tool calling, strict-JSON mode, and model comparison.
  - **DuckDB on Python 3.14** — half-up `round()`, `ATTACH`-based diffing, atomic file swap, `read_json_auto`, full-text search, and concurrent read behaviour.

#### Change proposal (OpenSpec)

- Change `add-paperlane-product-discovery` created under `openspec/changes/`, schema `spec-driven`. Passes `openspec validate --strict`.
- `proposal.md` — why, what changes, eight new capabilities, impact, and the Tier 1 / Tier 2 split.
- `design.md` — the technical decisions and the constraints that drove them, including the LLM and store failure modes.
- `tasks.md` — 86 tasks in 11 groups. Groups 2–9 are Tier 1, group 10 is Tier 2 behind a hard gate, group 11 is integration verification, and group 1 is scaffold shared by both tiers. Every task states its own verification.
- Eight capability specs — 65 requirements, 132 scenarios, behaviour contracts only, naming no framework or library:
  | Capability | Requirements | Scenarios |
  |---|---|---|
  | `catalog-ingestion` | 13 | 25 |
  | `pricing-engine` | 9 | 19 |
  | `product-search` | 9 | 17 |
  | `sales-assistant` | 10 | 22 |
  | `quote-api` | 8 | 17 |
  | `catalog-refresh` | 6 | 11 |
  | `evaluation-harness` | 6 | 10 |
  | `observability` | 4 | 11 |

#### Repository documentation

> **Historical — as at planning.** The two counts that later changed are corrected here rather than in place: `TEST.md` now documents **eight** test layers and a per-module inventory of **1095** tests; `BUG.md` now carries **9** analysis defects (Part 2, A1–A9) and **5** shipped-code defects (Part 2b, A10–A14). The list is left as written so the planning inventory stays auditable.

- `AGENTS.md` — sources of truth in priority order, the brief's non-negotiable constraints, scope discipline, workflow boundary, code conventions, verification expectations.
- `ARCHITECTURE.md` — component view, the four load-bearing design decisions, data model, pricing pipeline, API surface, snapshot lifecycle, verified site facts, known architectural limitations.
- `DESIGN.md` — the two users, the interaction problem created by budget-depends-on-quantity, the four-part reply structure, the four outcomes as distinct designed states, deliberate omissions.
- `TEST.md` — four test layers, the two non-negotiable rules (recompute expectations, keep failures), evaluation coverage table, requirement-to-layer matrix, regression policy.
- `BUG.md` — 15 verified data traps with guards, 8 defects found and corrected in our own analysis, accepted risks, operational failure modes.
- `CLAUDE.md` — agent entry point and command reference.
- `CHANGELOG.md` — this file.

### Fixed — 2026-10-26 · Corrections made during planning

Recorded because the pattern matters more than the individual numbers: every one was a plausible figure that would have become a wrong test expectation, and every one was caught by recomputing from source rather than by review.

- A "no match" evaluation case used a budget of 200, which 15 products satisfy. Lowered below the cheapest catalog item.
- A worked example labelled a CMYK SKU as black-and-white. Corrected to the SKU's real row.
- An A5 copy-paper case carried a total belonging to a flyer. Traced to its source SKU and corrected.
- A multi-item case asserted "one delivery line" but computed no total, so the per-line-delivery bug it was meant to catch was undetectable. Exact expected total added.
- A claim that one page lacks a weight; in fact 10 of 36 state weight only in prose. Trap rewritten with the real distribution.
- A VAT-before-delivery error stated as 4.50; it is 10.50.
- A per-line delivery bug was stated to produce 259.02 VAT, then "corrected" to 260.02; the real figure is 231.72.
- **`PL-CP-A4-80`'s list price was recorded as 122.55, which is its 10+ tier price; the list is 129.00.** A published worked example (total 291.63) and a multi-item basket (total 3653.52) were both derived from it. Every total was recomputed; corrected to 298.53 and 3221.02. This is the one that would have silently corrupted the evaluation set, because the arithmetic was right and only the input was wrong.
- A recompute script crashed with `TypeError: NoneType * int` at quantity 1. The crash was a real pricing defect — the no-tier-met fallback — not a scripting slip. It became a named unit test.
- Category page count stated as 7 without distinguishing 4 index pages from 3 continuation pages. Counts now stated separately.
- Full-crawl request estimate corrected from 102 to 105 after the category count was resolved.

### Repository — as at 13:42:26

Superseded by the 0.5.0 entry below.

- **Git repository initialised** with remote `origin` configured. As of this entry the repository had **0 commits** and no `.gitignore`.
- No credential is present anywhere in the working tree; `.env` does not exist. Credentials remain environment-variable-only, per `AGENTS.md`.

### Not yet started — as at 13:42:26

Implementation. Nothing in `devx_FDE_A3_Product_Discovery/src/` existed; the directory held only the brief PDF and the read-only `paperlane/` site.

Both sections above are now historical. The current state is the 0.5.0 entry below and the "Not yet started" section at the end of this file.

### Repository — current state

- `.gitignore` exists at both the repository root and in `devx_FDE_A3_Product_Discovery/`, covering `.env`, `*.duckdb.wal`, `*.duckdb.tmp`, `*.previous.duckdb`, `__pycache__`, `.venv` and build output. Verified by `git add -An .` reporting **no** `.venv`, `__pycache__`, `.wal` or `.env` path.
- `data/catalog.duckdb` **is** committed, deliberately: it is what makes `./run.sh serve` work on a fresh checkout without crawling. `data/catalog.previous.duckdb` is not — it is a diff baseline, regenerable.
- No credential is present in the working tree or the index. `tests/test_hygiene.py` scans for one on every test run, so this is a checked fact rather than a claim.

---

## Releases

Milestones follow `tasks.md` group order. A milestone is complete when its stated verification has been run and passed — not when the code exists. Every milestone below 0.5.0 is now **shipped**, and the verification that closed each is named.

### 0.1.0 — Deterministic core · shipped

- `tasks.md` groups 1–2: scaffold, dependencies, integer-satang money with explicit half-up rounding, weight and size normalisation, tier selection, order assembly, budget comparison.
- Rationale for landing this first: the brief scores totals "to the satang", and this is the layer where a wrong number is invisible in every other test.
- Closed by: `tests/test_money.py` (25) and `tests/test_pricing.py` (49), both green before any later module existed.

### 0.2.0 — Catalog · shipped

- `tasks.md` group 3: rate-limited crawler, four-shape extraction ladder with a review floor, field normalisation, snapshot writer, extraction fixtures.
- Closed by: a full 103-request crawl producing 72 leaf SKUs, 105 tier rows and 2 review items; `tests/test_crawl.py` (13), `tests/test_extract.py` (49), `tests/test_normalize.py` (37), `tests/test_catalog.py` (45), `tests/test_ingest.py` (14).

### 0.3.0 — Search and assistant · shipped

- `tasks.md` groups 4–5: hard-constraint filtering with absent-attribute semantics, alias layer, deterministic ranking, `match_reasons`, criteria parsing with rule fallback, reply contract, clarify/no-match/refuse rules, no-invented-products assertion.
- Closed by: `tests/test_aliases.py` (99), `tests/test_search.py` (38), `tests/test_assistant.py` (67), `tests/test_model.py` (42).

### 0.4.0 — API and refresh · shipped

- `tasks.md` groups 6–7: the five endpoints, four-outcome status enum, error contract, build-then-swap snapshots, diff report, committed-snapshot path.
- Closed by: `tests/test_api.py` (68), including `TestDocumentedExamples` executing every example in `docs/api.md`; `./run.sh diff` reporting `comparable: true, no_change: true` with all six change lists empty against an unchanged site.

### 0.5.0 — Evaluation and submission (Tier 1 complete) · shipped

**Added**

- `tasks.md` group 8: the recorded case set (28 cases, 24 runnable) with every
  expected total recomputed from the catalog by independent integer arithmetic;
  four-axis scoring reported separately; failures and not-applicable cases
  retained with their causes; the interpretation-strategy comparison; and
  `eval/results.md` recording the actual run.
- `eval/negative-control.json`: the same set with three deliberate corruptions,
  so "the harness can fail" is reproducible rather than asserted.
- `./run.sh eval --cases <path>` and `--self-check` to run either control.
- `tasks.md` group 9: `README.md` and `CUSTOMER_SUMMARY.md`.
- `tests/test_hygiene.py`: a credential scan, so "no credential is committed" is
  a checked fact.
- This release is a complete submission. Tier 2 is optional beyond it.

**Verified**

- 590 tests pass under `unshare -rn` with no network and no `PAPERLANE_LLM_*` set.
- Evaluation: 24 of 24 runnable cases pass across four axes (retrieval 24/24,
  match 19/19 with 5 n/a, pricing 19/19 with 5 n/a, reply 24/24).
- `--self-check` exits 0. The negative control exits **1** with exactly the three
  corrupted cases failing, which is the point of it.
- Against the live model the run also passes 24/24, with the model's criteria
  agreeing with the rules on every structured case.

**Fixed** — six real defects, each found by building the evaluation set or by
running it against the live model. The *how* is the useful part, so it is
recorded for each.

- `_score_pricing` accepted only `outcome == "quoted"`, so the multi-line basket
  cases scored `n/a` on price — including case 16, the only case that can catch a
  per-line delivery charge. **Found by** `self_check()`: the deliberately
  corrupted per-line delivery figure passed. Fixed; the run went from 17 to 19
  priced cases.
- A budget's "under" was read as a weight ceiling, so *"A4 80gsm under 250 a
  pack"* became "80 gsm or lighter" and returned eleven items instead of five.
  **Found by** writing case 20's expectations from the catalog rather than from
  the reply. Fixed by scoping the qualifier to the weight's own clause, with a
  narrower vocabulary after the number than before it.
- "full colour" was treated as ambiguous, so *"two-sided full colour A5 130gsm
  gloss"* asked which colour was meant — a question the words had already
  answered — while the `4/4` spelling of the same request worked. Separately,
  "black and white" matched the shade pattern on the word "black". **Found by**
  probing synonym spellings while writing case 17. Fixed.
- The quantity clarification was dead code in production:
  `_quantity_changes_the_answer` read tiers from `product["tiers"]`, which
  `load_products()` never populates. Tests passed because they supplied a
  `product_tiers` argument the API never passed. **Found by** case 19, which
  expected a question and got a quote at quantity 1. Fixed by deriving the tier
  map from the price facts, and the test helper no longer passes the argument.
- The model merge retracted a settled colour: for case 1 the model returns a bare
  `{"colour": "colour"}`, and the merge consulted only the model's payload when
  deciding to re-open the ambiguity, ignoring that the rules had already read the
  word as print colour. Three cases degraded to clarification. **Found only by
  the live run** — a stub returning tidy payloads never triggers it. Fixed, with
  the flag now normalised against the final criteria.
- Four cases carried the wrong `behaviour` tag: case 22 was tagged as a synonym
  test when it is an untrusted-input test, and cases 9, 20 and 27 claimed to
  cover "inapplicable attributes" when none of them has an attribute the catalog
  cannot answer. **Found by** auditing the coverage table against what each case
  actually asserts, after `results.md` reported a behaviour as covered that no
  case exercised. Retagged. This is why coverage is a *declared* field from a
  closed vocabulary and not a keyword grep — and why it still needs a human to
  read it, since a declaration can be wrong too.

**Changed**

- Two of my own expectations in `eval/cases.json` were wrong when first written
  (case 20 named 70/75 gsm papers for an 80 gsm request; case 25 had `PL-CP-`
  where the SKU is `PL-CL-`). Both were caught because the harness compares
  against the catalog rather than against my notes. This is the argument for
  computing expectations instead of writing them down.
- `docs/api.md` claimed the development base URL was port 8000, which is the
  static site, not the assistant. Corrected to 8001 with the reason.


### 0.8.0 — Tier 2 extras and conversation memory · shipped

- `tasks.md` group 10 plus the brief's nice-to-haves, each cut as its own OpenSpec
  change and independently droppable: `add-mutated-site-refresh-harness` (27/27),
  `add-semantic-tiebreak` (26/26), `add-observability` (28/28), and
  `add-conversation-memory` (54/54). **221 tasks closed across the five archived
  changes, none open.**
- The version was carried at 0.7.0 while the three Tier 2 changes landed. It is
  cut to 0.8.0 here because conversation memory added a *capability* — a new spec,
  `conversation-memory` (8 requirements, 27 scenarios), and a new evaluation set —
  rather than closing an item the plan had already named. That is the same test
  the earlier milestones used.
- Rationale for landing conversation memory last: it changes the shape of a
  request, so every earlier layer had to be correct and pinned first. The merge
  sits **after** interpretation and re-validates through the same check a fresh
  request uses, so a merged value the catalog cannot stock is caught by the path
  that already existed.
- Closed by: **1095 tests** green (online 4 skip, offline 7 skip), eval 24/24 on
  v1 and 21/21 on v2, conversation eval 11/11 over 24 turns, single-turn replay
  22/22 comparable cases unchanged, both negative controls exit 1,
  `verify-refresh` 12/12 exit 0, and `./run.sh ask` exit 0. The full accounting of
  each is in the `[Unreleased]` entries above; the defects found afterwards are in
  `BUG.md` Part 2b and are summarised with their falsification evidence there.

### 1.0.0 — Tier 2 extras · partial

> **Historical — superseded.** Three of six items were shipped when this was written; the other three were built on 2026-10-26 and are recorded in the `[Unreleased]` entries above, along with conversation memory. This entry is left as it was written so the sequence of reasoning stays auditable.

`tasks.md` group 10, each item independently droppable. Gate: no Tier 2 work starts while a Tier 1 task is unfinished. Three of six items are shipped; three are not, and the three open ones are the reason 1.0.0 is not cut.

**Shipped 0.5.0 (built because they were cheap once the core existed):**

- Multi-item basket quoting — `POST /api/quote/lines`, exercised by evaluation cases 16 and 27.
- Single-page interface — `ui.py`, all four outcomes rendered.
- Snapshot diff as a demo artefact — `GET /api/diff` and `./run.sh diff`.

**Not shipped — 6 tasks open, each with the reason it is open:**

| Task | Item | Why it is still open |
|---|---|---|
| 10.4 | Self-built mutated site | Not built. Nothing to prove the diff against: `./run.sh diff` correctly reports `comparable: false` on a fresh checkout and `no_change: true` against the unchanged site, but no site has been constructed with injected added/withdrawn/price/tier/markup changes. |
| 11.4 | Verify refresh against the mutated site | **Blocked by 10.4.** There is nothing to re-ingest. |
| 10.3 | Diff as a demonstrated artefact | Partly done: the report and command exist and run, but "renders each change kind against a mutated site" cannot be verified without 10.4. Annotated open in `tasks.md` rather than claimed. |
| 10.5 | Hybrid semantic tiebreak | Not started. Search is hard filtering plus deterministic ranking. The README states the consequence as a limitation. |
| 10.6 | Structured logging and five metrics | Not started. No logging or metrics module exists. |
| 10.7 | Verify no credentials or unbounded conversation text in logs | **Blocked by 10.6.** There are no logs to inspect. |

The honest summary is that the three shipped items were built because the core made them nearly free, and the three open ones each need work that is genuinely separate: a constructed site, an embedding layer, and a logging module. None of the six is required by the brief's scored criteria, and none is claimed as done.

---

## Not yet started

> **Historical — superseded 2026-10-26, and again 2026-10-27.** This section described the state before the three Tier 2 changes were built. All three are now shipped and archived: 10.5 by `add-semantic-tiebreak`, 10.6 and 10.7 by `add-observability`. Conversation memory — a brief nice-to-have, not a `tasks.md` item — was then built by `add-conversation-memory`. `tasks.md` reads 86 of 86, all five archived changes total 221 closed tasks, and no change is active. Kept rather than deleted because the reasoning about *why* they were deferred is part of the record; see the `[Unreleased]` entries above for what closed each.

Three `tasks.md` items remain, all Tier 2, all named rather than omitted:

| Task | Item | Belongs to |
|---|---|---|
| 10.5 | Hybrid semantic tiebreak (Ollama `bge-m3`, optional by construction) | `add-semantic-tiebreak` |
| 10.6 | Structured logging and the five metrics | `add-observability` |
| 10.7 | Verify credentials and unbounded conversation text are absent from the logs | `add-observability` |

**Nothing in Tier 1 is open.** Tasks 10.3, 10.4 and 11.4 were closed by
`add-mutated-site-refresh-harness`: the diff now renders all six change kinds
against a mutated site, and a re-ingest reports every injected change with no
page disappearing without appearing in review. The earlier annotation calling
10.3 "partly open" no longer applies.

---

## Conventions for future entries

- One entry per user-visible or scoring-relevant change; group under `Added` / `Changed` / `Fixed` / `Removed`.
- **A `Fixed` entry states how the defect was found**, not only what changed. "Found by recomputing" is the useful part.
- A changed test expectation must cite the recomputation that justifies it. If the recomputation and the old expectation disagree, one of them is a finding — record which.
- Known limitations do not belong here; they belong in `BUG.md` Part 3 and the README's known-limitations section.
- Never record a credential, a key fragment, or an endpoint with embedded authentication.
