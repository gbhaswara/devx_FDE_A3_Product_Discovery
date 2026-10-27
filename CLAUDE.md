# CLAUDE.md

Entry point for an AI agent working in this repository. Read `AGENTS.md` for the working rules; this file is the orientation and command reference.

## What this is

The **devx AI Labs AI Forward Deployed Engineer** take-home, **Option A3 — Product Discovery**: a sales assistant over the PaperLane paper catalog website, in Bangkok.

A customer sends *"We need letter-size flyers, one side, colour, under 250 a pack, 20 packs."* The system reads the live catalog, finds matching products, explains why each matches, and returns a complete price breakdown — every figure computed in deterministic code.

**Status: complete.** Tier 1 and every Tier 2 extra are shipped and archived, along with conversation memory and the gap-closure work. **221 tasks closed across the five earlier archived changes and none open** (86 Tier 1 + 26 + 27 + 28 + 54); `add-gap-closure` closed 5 more and is archived. 1194 tests pass offline under `unshare -rn` (7 skip) with no model configured. The version is `0.9.0`. Nothing is under construction.

## Read in this order

| # | File | Why |
|---|---|---|
| 1 | `devx_FDE_A3_Product_Discovery/devx_FDE_A3_Brief.pdf` | The customer's specification: PR1–PR8, must-haves 1–8, nice-to-haves, "what we look for". Authoritative. |
| 2 | `00_START_HERE_All_Briefs.md` | Submission requirements, rules, the seven scoring areas, the three post-submission rounds. |
| 3 | `openspec/specs/*/spec.md` | Behavioural contracts — **eleven** capabilities, **86 requirements, 227 scenarios**. These are the live specs. |
| 4 | `openspec/changes/archive/` | The changes that produced them, each with `proposal.md` / `design.md` / `tasks.md`. **All archived** — there are no active changes. |
| 5 | `ANALYZE_01.md` | The evidence, written during planning. §2 traps, §11b gap audit, §12 verification log. Cite it rather than re-deriving facts. |
| 6 | `ANALYZE_POST.md` | The same system re-analysed from the code as built — §1 data, §2 search, §3 agents, §4 pricing. Read this for what actually shipped; `ANALYZE_01.md` for what was decided. |
| 7 | `ARCHITECTURE.md`, `DESIGN.md`, `TEST.md`, `BUG.md` | How it is built, how it reads, how it is proven, what is known to break. |
| 8 | `devx_FDE_A3_Product_Discovery/README.md` | The submission's front door: the five-command demo path and the evidence table. |
| 9 | `devx_FDE_A3_Product_Discovery/GAPS_ANALYSIS.md` + `GAPS_RESPONSE.md` | A production-readiness review of the finished system, and the finding-by-finding answer — which gaps were closed, which the brief puts out of scope, and why. |

The brief PDF and the A3 section of `00_START_HERE` were extracted and diffed: **identical, no drift**. If they ever disagree, the PDF wins and the discrepancy gets raised.

## Layout

```
DEVXLABS/
├── AGENTS.md                    working rules for this repo
├── ARCHITECTURE.md              system structure
├── DESIGN.md                    product and interaction design
├── TEST.md                      testing and evaluation strategy (eight layers)
├── BUG.md                       data traps, analysis defects, shipped-code defects
├── CHANGELOG.md                 history; current status is 0.9.0
├── ANALYZE_01.md                planning analysis and verification log
├── ANALYZE_POST.md              post-implementation design, grounded in the code
├── MVC_PLAN.md                  a separate scoping exercise — NOT this repo
├── 00_START_HERE_All_Briefs.md  all three assignment briefs + rules
├── openspec/
│   ├── config.yaml              schema: spec-driven
│   ├── specs/{catalog-ingestion,catalog-refresh,conversation-memory,
│   │          evaluation-harness,observability,pricing-engine,product-search,
│   │          quote-api,refresh-verification,sales-assistant,
│   │          semantic-ranking}/spec.md          the eleven live specs
│   └── changes/archive/2026-10-26-*  and  2026-10-27-*
│       ├── proposal.md  design.md  tasks.md
│       └── specs/*/spec.md
└── devx_FDE_A3_Product_Discovery/
    ├── devx_FDE_A3_Brief.pdf    READ-ONLY input
    ├── paperlane/               READ-ONLY input — the site to crawl
    ├── run.sh                   the command surface (see below)
    ├── src/paperlane/           27 modules
    ├── tests/                   29 modules, 1194 tests
    ├── eval/                    cases.json, held-out-cases.json, conversation-cases.json,
    │                            the three negative/control sets, results.md
    ├── docs/                    11 documents, one per layer or capability
    ├── data/                    catalog.duckdb is committed; *.jsonl is not
    ├── README.md  CUSTOMER_SUMMARY.md  GAPS_ANALYSIS.md  GAPS_RESPONSE.md
    └── pyproject.toml  uv.lock
```

`paperlane/` and the brief PDF are **read-only**. Never edit the site to make a test pass.

## Environment

| Tool | Version present |
|---|---|
| Python | 3.14.7, in `devx_FDE_A3_Product_Discovery/.venv` |
| `uv` | 0.12.20 |
| `openspec` | 1.14.0 |
| `duckdb` (Python) | 2.0.0 |
| `pdftotext` / `pdfinfo` | available |
| `duckdb` CLI / `sqlite3` CLI | **not installed** — use the Python module |
| `git` | 35 commits, remote `origin` set, history pushed |

**Always use the project virtualenv's interpreter: `devx_FDE_A3_Product_Discovery/.venv/bin/python`.** Bare `python3` resolves the project-root `paperlane/` directory as a namespace package and shadows the real package — a confusing `ImportError` for `paperlane.cli`. `run.sh` already does this; prefer `./run.sh`.

There is no `pip` module and no `sqlite3` CLI. Use `uv`. Bare `python3` can only work when the module does not import `paperlane`.

The store is **DuckDB**, not SQLite — decided and verified (`ANALYZE_01.md` §3).

`.gitignore` exists at both the repository root and in `devx_FDE_A3_Product_Discovery/`, covering `.env`, `*.duckdb.wal`, `*.duckdb.tmp`, `*.previous.duckdb`, `__pycache__`, `.venv`. **Check `git status` for credentials before every commit** — `tests/test_hygiene.py` also scans for one on every test run, so this is a checked fact rather than a habit.

## Commands

Everything is dispatched through `devx_FDE_A3_Product_Discovery/run.sh`. Run it with no argument to list the subcommands.

```bash
cd devx_FDE_A3_Product_Discovery

uv sync                                        # install; no network beyond PyPI
./run.sh test                                  # the suite: offline, no model, no network
./run.sh serve                                 # the app on http://127.0.0.1:8001
./run.sh eval                                  # the recorded cases against the loaded snapshot
./run.sh ask "A4 80gsm copy paper, 20 reams"   # one question, no server needed
./run.sh ask --conversation demo "make it 50"  # continue a conversation; --forget discards it
./run.sh diff                                  # current snapshot vs previous
./run.sh metrics                               # five measures derived from request records
./run.sh metrics --eval                        # the same, over the last evaluation run
./run.sh similarity                            # the semantic tiebreak; needs an embedding provider
./run.sh verify-refresh                        # mutate a copy of the site, refresh, verify (~55s)
./run.sh ingest --base-url http://localhost:8000/paperlane/   # re-crawl
```

`./run.sh eval` also takes `--cases <path>` and `--self-check`. The conversation
set is `eval/conversation-cases.json`; the held-out set is
`eval/held-out-cases.json` (11 requests, unseen phrasing, 3 failures retained by
design — it is *not* a regression set). The two negative controls are
`eval/negative-control.json` and `eval/conversation-negative-control.json`, and
both are *expected* to exit 1.

`ingest`, `serve`, `eval`, `ask` and `metrics` all take `--db <path>` (or read
`PAPERLANE_DB`), resolving through one `resolve_db_path`, so a live re-ingest of
an unseen site can be served from a separate snapshot without overwriting
`data/catalog.duckdb`. Without the flag the default is `data/catalog.duckdb`
exactly as before. Every API response names the snapshot it used and its age.

Serving the site — required, because volume prices load over HTTP and not from disk:

```bash
cd devx_FDE_A3_Product_Discovery && python3 -m http.server 8000
# then: http://localhost:8000/paperlane/
```

**Serve from the parent of `paperlane/`, not from inside it.** The site's own root is `/paperlane/`, and every page declares `<body data-root="../">` so `assets/tiers.js` resolves volume-pricing URLs relative to it. Serving from inside `paperlane/` makes the URL `http://localhost:8000/` and the brief's documented `http://localhost:8000/paperlane/` returns 404.

Verified working:

```bash
curl -o /dev/null -w '%{http_code}\n' http://localhost:8000/paperlane/                                       # 200
curl -o /dev/null -w '%{http_code}\n' http://localhost:8000/paperlane/product/flyers-ltr-gloss.html          # 200
curl -s http://localhost:8000/paperlane/api/pricing/PL-PR-LTR-GL-130-40.json                                 # tiers 5+ 249.10, 20+ 233.20
```

OpenSpec — note that the changes are **archived**, so they are validated by
directory, and `openspec list` reports no active changes by design:

```bash
openspec validate --specs --strict            # the eleven live specs
openspec list                                 # "No active changes found." — correct
openspec show semantic-ranking                # one spec, rendered
```

`openspec validate add-paperlane-product-discovery` **fails** with *"Unknown item"* — that change is archived, not active. Do not treat the failure as a problem to fix.

## Memory tooling — do this at every phase boundary

Full detail is in `AGENTS.md` §"Memory tooling". The short version:

**Before** a phase or a `tasks.md` group: recall. **After** it: write. Both tools, both directions.

| Tool | Call | When |
|---|---|---|
| `hindsight.recall({query})` | wider, cross-project | before a phase |
| `local-memory.memory-read({query})` | repo-scoped, authoritative | before a phase |
| `hindsight.retain({content})` | durable note | after a phase |
| `local-memory.memory-write({content, type})` | `type` ∈ `decision` / `code_fact` / `mistake` / `pattern` / `task_archive` | after a phase |

Scope is `owner=PORTOFOLIO`, `repo=DEVXLABS`. Write the phase boundary, not a summary of the code — the code is already in the repository.

Record decisions with the alternative rejected, verified facts that were expensive to establish, and mistakes with how they were caught — `mistake` is the highest-value type for the interview and the one most likely to be skipped. **Never** record a credential, a key fragment, or an endpoint with embedded auth — both stores persist beyond this repository.

If a tool is unavailable, say so and continue; do not block on it, and do not silently skip the write.

## Hard rules

Non-negotiable, from the brief. Violating one costs more than any feature gains.

1. **Never commit an API key.** Environment variables only; `.env` is git-ignored.
2. **Crawl at ≤ 2 req/s.** `robots.txt` says `Crawl-delay: 1`; run at 1 req/s.
3. **Serve over HTTP.** Never read the catalog via `file://` or a direct path — volume prices will silently not load.
4. **Money is computed by code, never by the model.** No price, total or discount may originate from, or be restated by, a language model.
5. **Money is integer satang.** No floats in the money path; one explicit half-up helper.
6. **Re-ingest must need no code change.** The demo round supplies an updated site.
7. **Use the data only for this assignment.** No external data sources.
8. **Explain any line of it in the interview.** Do not commit code you cannot defend.

## The five things that are easy to get wrong

Each has a trap entry in `BUG.md` with the guard. Summary:

| Trap | The mistake | The correct behaviour |
|---|---|---|
| Budget × quantity | Comparing budget to list price | Compare at the **requested quantity**; the brief's own example flips from fail to pass between qty 1 and qty 20 |
| No tier met | Initialising the best price to `None` | Initialise to **list price**; most SKUs' lowest tier is 5+ or 10+ |
| Delivery | Charging per line | Charge **once per order**, against the summed pre-tax subtotal |
| VAT | Taxing subtotal only | Tax **subtotal + delivery** |
| Absent attributes | `WHERE sides = 'single'` | Absent is not-applicable, not false — that query returns zero paper products |

## Scope discipline

The brief plans **~6 hours** and explicitly scores *"good judgment about scope."* Work was split in two tiers, and both are complete.

- **Tier 1** — the six-hour core: ingestion, pricing, search, assistant, API, refresh, evaluation, README + customer summary. 86 of 86 tasks.
- **Tier 2** — the six planned extras, each independently droppable: multi-item baskets, the single-page UI, diff-as-demo, the self-built mutated site, the semantic tiebreak, and structured logging with metrics. All six built, plus **conversation memory** (a brief nice-to-have that grew into its own change).

The brief's five nice-to-haves all landed: hybrid search (as a tiebreak that cannot change membership), multi-item quotes **and** conversation memory, defences against untrusted scraped text, logging and metrics, and `docs/chat-channel.md` for the LINE/WhatsApp deployment notes.

**No new scope without saying so in one sentence and justifying it.** The submission is finished; a change from here is a new decision, not a continuation.

## Working with the LLM

The provider is **9router**, model **`9inference`**, via environment variable only. It is a reasoning model and fails in specific ways that are already documented — do not rediscover them:

- The response body appends a stray `data: [DONE]` after the JSON. Parse with a terminating-newline strip, not bare `json.loads`.
- With a small output-token budget it returns HTTP 200 with `content: null` and spends everything on reasoning. Budget **≥ 1000** output tokens.
- `response_format={"type": "json_object"}` makes it worse, and `reasoning_effort="none"` is ignored. Validate the parsed criteria instead of relying on a structured-output flag.
- The **user** message must carry the format instruction; putting it in the system message does not take effect.

The model emits **criteria only**. Products and prices come from the filter and the pricing layer. A model outage is a quality dip, not an outage: interpretation falls back to rules and anything unparseable becomes a `clarified` outcome, which is a normal state.

## When unsure

- Ambiguity in the brief → ask. The brief explicitly welcomes clarifying questions.
- Ambiguity in the code → choose the option that is easier to explain out loud.
- Spec versus site → the site wins on facts, the spec wins on intent. Record the conflict; never resolve it silently.
- Do not edit a spec while implementing. If reality contradicts one, stop and raise it. The specs are the live artefact under `openspec/specs/`; the `openspec/changes/` copies are archived history and must not be edited at all.
- A dated artefact (`ANALYZE_01.md`, an archived `tasks.md`) that has since been superseded is **superseded in place** with a note, not rewritten — see the convention at the end of `CHANGELOG.md`.
