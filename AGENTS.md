# AGENTS.md — working rules for this repository

Instructions for any AI agent or human contributor working here. Read this before touching code.

## What this repository is

A take-home submission for the **devx AI Labs AI Forward Deployed Engineer** assignment, **Option A3 — Product Discovery**: a sales assistant over the PaperLane paper catalog website.

Sources of truth, in order of authority:

| Priority | Source | What it governs |
|---|---|---|
| 1 | `devx_FDE_A3_Product_Discovery/devx_FDE_A3_Brief.pdf` | The customer's agreed specification: PR1–PR8, must-haves 1–8, nice-to-haves, "what we look for" |
| 2 | `00_START_HERE_All_Briefs.md` | Submission requirements, rules, the seven scoring areas, the three post-submission rounds |
| 3 | `openspec/changes/archive/2026-10-26-add-paperlane-product-discovery/` | The PRD: `proposal.md`, eight capability specs, `design.md`, `tasks.md`. The five later changes are beside it; the live contracts are `openspec/specs/` |
| 4 | `devx_FDE_A3_Product_Discovery/docs/` | `pre/ANALYZE_01.md` — the analysis and evidence behind the decisions, including verified site facts. `post/ANALYZE_POST.md`, `post/FIXED.md` and `post/MVC_PLAN.md` sit under the same tree |

The A3 brief PDF and the A3 section of `00_START_HERE_All_Briefs.md` were extracted and diffed: **identical content, no drift**. If they ever disagree, treat the PDF as authoritative and raise the discrepancy.

## Non-negotiable constraints from the brief

These are rules, not preferences. Violating one costs more than any feature gains.

- **Never commit API keys.** Credentials come from environment variables only. `.env` is git-ignored.
- **Use the data only for this assignment.** No external data sources, no enrichment from elsewhere.
- **Crawl at most 2 requests per second.** `robots.txt` sets `Crawl-delay: 1`; run at 1 req/s.
- **The site must be served over HTTP.** Opening files from disk does not load volume prices. Never read the catalog with `file://` or a direct filesystem path.
- **Pricing is calculated by deterministic code, never by the model.** No price, total, discount or figure may originate from, or be restated by, a language model.
- **You must be able to explain and change any part of this code in the interview.** Do not commit code you cannot defend line by line.
- **It must run on a new version of the site without code changes.** The demo round supplies an updated site and asks for a re-ingest.

## Scope discipline

The brief plans **about 6 hours of focused work** and states that *"good judgment about scope is part of what we look at."* The deadline is 5 calendar days.

Work is therefore split into two tiers, defined in the proposal:

- **Tier 1 — the six-hour core.** Ingestion, pricing engine, search, assistant, API, refresh, evaluation, README and customer summary. This is a complete submission on its own. **Never trade a Tier 1 item for a Tier 2 one.**
- **Tier 2 — chosen extras.** Hybrid semantic tiebreak, multi-item baskets, the diff report as a demo artifact, the htmx UI, a self-built mutated site, LLM-vs-rule comparison, metrics.

Rules that follow:

- Do not start Tier 2 work while any Tier 1 task is unfinished.
- Every Tier 2 item must be independently droppable, with no Tier 1 dependency on it.
- If you add something not in the proposal, say so and justify it in one sentence. Do not silently expand scope.

## Workflow

Planning and implementation are separate steps. Do not skip the boundary.

```
1. Analyse      devx_FDE_A3_Product_Discovery/docs/pre/ANALYZE_01.md   (done)
2. Propose      openspec/changes/archive/...            (done — the PRD, now archived)
3. Apply        /opsx-apply                            (done — six archived changes, 239 tasks)
4. Verify       tests + eval + clean-run               (done — 1252 tests, eval 24/24, v2 21/21)
5. Submit       repo link + README + customer summary + eval results   (ready)
```

Every step is bracketed by a **memory recall before** and a **memory write after** — see "Memory tooling" below. A phase that skipped its recall risks repeating a settled decision; one that skipped its write leaves the next phase blind.

- Planning artifacts live in `openspec/changes/archive/2026-10-26-add-paperlane-product-discovery/` and the other archived changes. Do not edit them while implementing; if reality contradicts a spec, stop and raise it.
- Implementation lives in `devx_FDE_A3_Product_Discovery/`. `paperlane/` and the brief PDF are **read-only inputs** — never modify the site to make a test pass.
- Each task in `tasks.md` states its own verification. A task is not done because the code exists; it is done because its stated verification was run and passed.

### Repository state

The project is a git repository with remote `origin` configured and history pushed. `.gitignore` exists at the repository root and in `devx_FDE_A3_Product_Discovery/`, covering `.env`, `*.duckdb.wal`, `*.duckdb.tmp`, `*.previous.duckdb`, `__pycache__` and `.venv`.

`devx_FDE_A3_Product_Discovery/devx_FDE_A3_Brief.md` is a committed text extraction of the brief; the PDF beside it remains authoritative. The planning artefacts — `ANALYZE_01.md`, `ANALYZE_POST.md`, `FIXED.md` and `MVC_PLAN.md` — live under `devx_FDE_A3_Product_Discovery/docs/pre/` and `docs/post/`.

Before every commit, confirm `git status` shows no `.env`, no credential file, and no `.duckdb.wal`. The brief's rule is absolute: never commit API keys.

## Code conventions

- **Money is integer satang.** No floats in the money path. All rounding goes through one explicit half-up helper.
- **Pricing is pure.** No I/O, no network, no clock, no model inside the pricing layer.
- **Provenance on every catalog row:** source URL and retrieval timestamp.
- **Degrade, never crash.** An unparseable page becomes a review row. An unreachable model becomes a rule-based answer. A missing detail becomes a clarification. Only genuine client error produces an error response.
- **Absent is not negative.** An attribute that does not apply to a product is not-applicable, and a constraint on it must not exclude the product.
- **Determinism over cleverness.** Any ranking needs a stable final tiebreak. Repeated identical requests must produce identical results.

## Verification expectations

- No task is complete without running its stated verification.
- A recorded expectation must be **recomputed from source data**, never transcribed. A wrong expectation is worse than no test, because it causes correct code to be "fixed".
- Failing evaluation cases stay in the results. The brief asks for *"cases where your system fails"*; a clean sweep is less credible than a documented failure.
- Tests must run with no network access and no model configured.

## Memory tooling — local-memory and hindsight

Two memory tools are available and **must be used at every phase boundary**, before and after implementation work. They are not optional bookkeeping; they are how context survives across sessions and how a phase is proven to have been reasoned about rather than rushed.

### The rule

**Before** starting a phase or task: **recall**. Read what is already known so you do not re-derive a fact, repeat a mistake, or contradict a decision already recorded.

**After** finishing a phase or task: **write**. Record the decisions taken, the facts established, and the mistakes made — while the detail is still exact.

A phase boundary means any of: starting or completing a `tasks.md` group, a Tier 1 → Tier 2 transition, a refresh or snapshot rebuild, an evaluation run, or a change to the PRD. Within a long group, checkpoint at each task that produces a durable fact.

### local-memory — project decisions and facts

Repository-scoped (`DEVXLABS`). Verified tool names and argument shapes:

| Purpose | Tool | Required arguments |
|---|---|---|
| Recall before a phase | `local-memory.memory-read` | none (lists the timeline) or `{query}` |
| Read one entry in full | `local-memory.memory-read` | `{id}` or `{code}`, e.g. `MEM-001` |
| Record a decision or fact | `local-memory.memory-write` | `{content, type}` — `content` ≥ 10 chars |
| Remove a wrong entry | `local-memory.memory-delete` | `{ids}` or `{code}` |
| Task state | `local-memory.task-read` / `task-write` | `task-write` CREATE needs `phase` + `title` (≥ 3 chars) + `description` |

`type` must be one of: **`decision` · `code_fact` · `mistake` · `pattern` · `task_archive`**. There is no free-form type — a write with an invalid `type` fails with a NOT NULL or enum error.

Choose the type by what the entry *is*, not by what it is about:

- `decision` — a choice with an alternative that was rejected, and why. ("Chose rebuild-and-swap over a single-writer store because…")
- `code_fact` — a verified property of the code or data that a later task would otherwise have to re-derive. ("`PL-CP-A4-80` list price is 129.00; 122.55 is its 10+ tier.")
- `mistake` — something that was wrong and how it was caught. This is the highest-value type for the interview, and the one most likely to be skipped.
- `pattern` — a recurring shape worth reusing. ("Every monetary figure is recomputed from source before being asserted.")

### hindsight — durable recall across sessions

Cross-session memory, not repository-scoped. Verified tool names:

| Purpose | Tool | Required arguments |
|---|---|---|
| Recall before a phase | `hindsight.recall` | `{query}` |
| Record after a phase | `hindsight.retain` | `{content}` |
| Check active directives | `hindsight.list_directives` | none |
| Add a standing directive | `hindsight.create_directive` | `{name, …}` |

`recall` returns ranked results from *all* prior work, not just this repository — treat it as a wider net than `local-memory`, and expect it to surface unrelated projects. `local-memory` is the narrower, authoritative one for this repo.

### What to record at each boundary

**Before** a phase — a short recall, then state in one line what was found and whether it changes the plan:

```
hindsight.recall({query: "<phase name> paperlane pricing"})
local-memory.memory-read({query: "<topic>"})
```

**After** a phase — at minimum:

1. Any **decision** taken that was not already in `design.md`, with the alternative rejected.
2. Any **verified fact** that cost effort to establish and would be expensive to rediscover — especially anything measured from the site.
3. Any **mistake**, including near-misses and wrong first attempts, with how it was caught.
4. The **verification result** — what was run, and whether it passed. A task recorded as done without its stated verification is a false record, which is worse than no record.

### What must never be recorded

- **Credentials, keys, tokens, or endpoint URLs with embedded auth.** Both stores persist beyond this repository; a key written to memory is a key leaked. Record *that* a credential comes from an environment variable, never its value.
- Unbounded user or conversation text — store the interpretation, not the raw transcript.
- Speculation presented as fact. If something is unverified, record it as unverified and say what would verify it. `BUG.md` Part 1 shows the convention: every trap carries a status, and `OPEN` is a legitimate status.

### Failure handling

If either tool is unavailable or errors, **say so and continue the phase**. Do not block implementation on memory tooling, and do not silently skip the write — a missing entry must be visible, because the next session will trust the absence. Note the failure in the phase summary so it can be retried.

## When you are unsure

- Ambiguity in the brief: ask, rather than assume. The brief explicitly welcomes clarifying questions.
- Ambiguity in the code: prefer the option that is easier to explain out loud in an interview.
- A conflict between a spec and the site: the site wins on facts, the spec wins on intent. Record the conflict rather than silently choosing.
