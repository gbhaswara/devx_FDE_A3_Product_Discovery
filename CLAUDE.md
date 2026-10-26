# CLAUDE.md

Entry point for an AI agent working in this repository. Read `AGENTS.md` for the working rules; this file is the orientation and command reference.

## What this is

The **devx AI Labs AI Forward Deployed Engineer** take-home, **Option A3 — Product Discovery**: a sales assistant over the PaperLane paper catalog website, in Bangkok.

A customer sends *"We need letter-size flyers, one side, colour, under 250 a pack, 20 packs."* The system reads the live catalog, finds matching products, explains why each matches, and returns a complete price breakdown — every figure computed in deterministic code.

**Status: planning complete, implementation not started.** Do not write implementation code until the user starts `/opsx-apply`.

## Read in this order

| # | File | Why |
|---|---|---|
| 1 | `devx_FDE_A3_Product_Discovery/devx_FDE_A3_Brief.pdf` | The customer's specification: PR1–PR8, must-haves 1–8, nice-to-haves, "what we look for". Authoritative. |
| 2 | `00_START_HERE_All_Briefs.md` | Submission requirements, rules, the seven scoring areas, the three post-submission rounds. |
| 3 | `openspec/changes/add-paperlane-product-discovery/proposal.md` | The PRD: scope and the Tier 1 / Tier 2 split. |
| 4 | `openspec/changes/add-paperlane-product-discovery/design.md` | Technical decisions and the reasoning behind them. |
| 5 | `openspec/changes/add-paperlane-product-discovery/specs/*/spec.md` | Behavioural contracts — eight capabilities, 65 requirements, 132 scenarios. |
| 6 | `openspec/changes/add-paperlane-product-discovery/tasks.md` | The build order, 86 tasks, each with its own verification. |
| 7 | `ANALYZE_01.md` | The evidence. §2 traps, §11b gap audit, §12 verification log. Cite it rather than re-deriving facts. |
| 8 | `ARCHITECTURE.md`, `DESIGN.md`, `TEST.md`, `BUG.md` | How it is built, how it reads, how it is proven, what is known to break. |

The brief PDF and the A3 section of `00_START_HERE` were extracted and diffed: **identical, no drift**. If they ever disagree, the PDF wins and the discrepancy gets raised.

## Layout

```
DEVXLABS/
├── AGENTS.md                    working rules for this repo
├── ARCHITECTURE.md              system structure
├── DESIGN.md                    product and interaction design
├── TEST.md                      testing and evaluation strategy
├── BUG.md                       data traps, accepted risks, failure modes
├── CHANGELOG.md                 history
├── ANALYZE_01.md                analysis and verification log
├── 00_START_HERE_All_Briefs.md  all three assignment briefs + rules
├── openspec/
│   ├── config.yaml              schema: spec-driven
│   └── changes/add-paperlane-product-discovery/
│       ├── proposal.md  design.md  tasks.md  .openspec.yaml
│       └── specs/{catalog-ingestion,catalog-refresh,evaluation-harness,
│                  observability,pricing-engine,product-search,
│                  quote-api,sales-assistant}/spec.md
└── devx_FDE_A3_Product_Discovery/
    ├── devx_FDE_A3_Brief.pdf    READ-ONLY input
    ├── paperlane/               READ-ONLY input — the site to crawl
    └── src/  tests/  eval/  data/  docs/     (to be created)
```

`paperlane/` and the brief PDF are **read-only**. Never edit the site to make a test pass.

## Environment

| Tool | Version present |
|---|---|
| Python | 3.14 |
| `uv` | 0.12.20 |
| `openspec` | 1.14.0 |
| `pdftotext` / `pdfinfo` | available |
| `duckdb` | **not yet installed** — `uv sync` will add it |
| `git` | repo initialised, remote `origin` set, **0 commits**, **no `.gitignore` yet** |

There is no `pip` module and no `sqlite3` CLI. Use `uv`. Run Python as `python3`.

The store is **DuckDB**, not SQLite — decided and verified (`ANALYZE_01.md` §3).

Add `.gitignore` (`.env`, `*.duckdb.wal`, `__pycache__`) before the first commit, and check `git status` for credentials before every commit.

## Commands

Planning:

```bash
openspec validate add-paperlane-product-discovery --strict   # must pass
openspec status --change add-paperlane-product-discovery
```

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

Planned implementation entry points (do not exist yet — defined in `tasks.md` 1.3):

```bash
uv sync
./run.sh ingest --base-url http://localhost:8000/paperlane/
./run.sh serve
./run.sh test      # unit + extraction + integration; offline, no model
./run.sh eval      # recorded cases against a loaded snapshot
./run.sh diff      # current snapshot vs previous
```

## Memory tooling — do this at every phase boundary

Full detail is in `AGENTS.md` §"Memory tooling". The short version:

**Before** a phase or `tasks.md` group: recall. **After** it: write. Both tools, both directions.

| Tool | Call | When |
|---|---|---|
| `hindsight.recall({query})` | wider, cross-project | before a phase |
| `local-memory.memory-read({query})` | repo-scoped, authoritative | before a phase |
| `hindsight.retain({content})` | durable note | after a phase |
| `local-memory.memory-write({content, type})` | `type` ∈ `decision` / `code_fact` / `mistake` / `pattern` / `task_archive` | after a phase |

Record decisions with the alternative rejected, verified facts that were expensive to establish, and mistakes with how they were caught. **Never** record a credential, a key fragment, or an endpoint with embedded auth — both stores persist beyond this repository.

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

The brief plans **~6 hours** and explicitly scores *"good judgment about scope."* Work is split in two tiers:

- **Tier 1** — the six-hour core: ingestion, pricing, search, assistant, API, refresh, evaluation, README + customer summary. A complete submission on its own.
- **Tier 2** — chosen extras, each independently droppable: semantic tiebreak, multi-item baskets, diff-as-demo, the UI, a self-built mutated site, parser comparison, metrics.

**Never trade a Tier 1 item for a Tier 2 one.** No Tier 2 work while a Tier 1 task is unfinished.

## Working with the LLM

The provider is **9router**, model **`9inference`**, via environment variable only. It is a reasoning model and fails in specific ways that are already documented — do not rediscover them:

- The response body appends a stray `data: [DONE]` after the JSON. Parse with a terminating-newline strip, not bare `json.loads`.
- With a small output-token budget it returns HTTP 200 with `content: null` and spends everything on reasoning. Budget **≥ 1000** output tokens.
- `response_format={"type": "json_object"}` makes it worse, and `reasoning_effort="none"` is ignored. Validate the parsed criteria instead of relying on a structured-output flag.

The model emits **criteria only**. Products and prices come from the filter and the pricing layer.

## When unsure

- Ambiguity in the brief → ask. The brief explicitly welcomes clarifying questions.
- Ambiguity in the code → choose the option that is easier to explain out loud.
- Spec versus site → the site wins on facts, the spec wins on intent. Record the conflict; never resolve it silently.
- Do not edit `openspec/changes/...` while implementing. If reality contradicts a spec, stop and raise it.
