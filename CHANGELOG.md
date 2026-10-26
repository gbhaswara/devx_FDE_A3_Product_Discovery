# CHANGELOG.md

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file records the project's own history. The planning entries are **artefacts of reasoning, not shipped code** — they are listed so the reasoning trail is auditable in the interview. The 0.5.0 entry below them is shipped code, and every claim in it is backed by a command whose output is recorded in `eval/results.md`.

Current status: **0.6.0 — Tier 1 complete, plus two of three Tier 2 changes.** 83 of 86 tasks closed in the Tier 1 change; the 3 open items belong to the remaining Tier 2 change and are named in §"Not yet started". 765 tests pass offline, the 24 v1-runnable evaluation cases pass (and 21 against the mutated second catalog), and the negative control fails as designed. See `openspec/changes/add-paperlane-product-discovery/tasks.md` (archived) and `openspec/changes/add-semantic-tiebreak/tasks.md`.

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


### 1.0.0 — Tier 2 extras · partial

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
