# TEST.md — testing and evaluation strategy

How correctness is established for the A3 submission. Requirements are in the ten main specs under `openspec/specs/`; each task in the archived changes' `tasks.md` names its own verification.

## The problem this strategy solves

The brief's scoring emphasis is *"right products and totals to the satang on unseen requests, including edge cases"* and *"we care more about evidence that your system works, and honesty about where it does not, than about polish."*

Two failure modes matter more than any others, and they need different defences:

1. **A correct-looking wrong answer.** Right price, wrong products — or right products, wrong price. Nothing crashes, so only a recorded expectation catches it.
2. **A wrong expectation.** A test that asserts the wrong number will cause correct code to be "fixed" until it matches the error. This is worse than having no test, and it is the failure I actually hit while writing `ANALYZE_01.md`: two totals were transcribed wrongly and were only caught by recomputing them from source.

So the strategy has two rules that are not negotiable:

- **Every expected total is recomputed from catalog data with exact arithmetic, never transcribed.** A test fixture that cannot be regenerated is a liability.
- **Failing cases stay in the results.** The brief asks for cases where the system fails.

## Test layers

Five layers, each answering a different question. They are deliberately separate, because a failure in one should not be attributable to another.

| Layer | Question it answers | Runs without network | Runs without model |
|---|---|---|---|
| 1. Unit | Does this function compute what the specification says? | yes | yes |
| 2. Extraction | Does this markup produce these fields? | yes (fixtures) | yes |
| 3. Integration | Does the whole path produce this quote? | yes (fixtures) | yes for `/quote` |
| 4. Refresh verification | Does a declared mutation of the site get reported correctly? | loopback only | yes |
| 5. Evaluation | Does the system answer these 28 real requests correctly? | no (needs model for `/chat` cases) | partially |

Of the 28 recorded cases, **24 run against v1** and **4 run against v2** — cases 21 (discontinued), 22 (injected instruction), 23 (`28 lb`) and 24 (`32 lb`). v1 has zero discontinued items (T4), no prompt injection, and no `28 lb` or `32 lb` product (T7); the mutated v2 catalog that `./run.sh verify-refresh` builds has all four, so those cases now **run and pass** there rather than being marked inapplicable.

Inapplicability is therefore a fact about a *named catalog*, not a permanent verdict on a case: each case declares `requires_catalog`, and a run declares which catalog it scored. Seven cases are pinned to v1 (their expected product *sets* enumerate v1's exact offering, which v2 genuinely extends); rewriting those from v2's own output would make the expectation circular. The full picture is in `eval/results.md`.

### Layer 1 — Unit tests

Pure functions with hand-verified expectations. This is where the money is proven.

**Money and rounding**
- Half-up on an exact half value (the case where default rounding differs)
- Accumulation of many small amounts is exact
- No float appears in the money path

**Weight normalisation**
- All four published forms produce the right grammage
- `20 lb` → 75, `24 lb` → 90, `28 lb` → 105, `32 lb` → 120
- An unlisted pound value raises rather than extrapolating
- The two pages that state both forms agree with the conversion table — these are golden assertions taken from the source itself

**Size normalisation**
- Decimal, vulgar-fraction (`8½`) and unicode-multiplication spellings of one size produce one code
- An unmappable size is reported, not left unset

**Unit price selection** — three named tests, because these are the three lines that go wrong:

| Test | Asserts |
|---|---|
| tier met | the highest qualifying tier's price is used |
| no tier met | the list price is used; the function does not return nothing at qty 1–4 |
| sale item | the sale price overrides both list and every tier |

**Order assembly** — three named tests:

| Test | Asserts |
|---|---|
| small order | delivery is charged, and VAT is computed on subtotal **plus** delivery |
| above threshold | delivery is zero |
| mixed order | neither line crosses the threshold alone, the order does; delivery is charged once, not per line |

**Budget comparison**
- The same product passes at a higher quantity and fails at a lower one
- A price exactly equal to the budget is treated as within budget
- The basis used is stated when the customer did not specify one

**Purity**
- Repeated identical calls return identical results
- A complete quote is produced with no model client configured

### Layer 2 — Extraction tests

Saved HTML fixtures, one per markup shape, plus the failure case. No network.

- Each of the four shapes yields the same normalised fields
- The shape used is recorded per page
- An unknown shape lands in review with a reason and excerpt, and does not raise
- `Size` / `Paper size` / prose all map to one field; `Colour` / `Shade` map to their correct, different fields
- A page with weight only in prose still yields a weight
- Printing attributes are not-applicable for plain paper
- The unit word is not used by any filter or comparison

### Layer 3 — Integration tests

Whole-path tests through the API, no network, no model.

- `/quote` returns complete candidates and figures with no model configured
- Each of the four outcomes produces its required fields
- Client errors: malformed body, implausible quantity, invalid criteria — each a client error, no stack trace
- Missing snapshot returns its remedy
- Unreachable model produces a normal outcome, not a server error
- `/health` names the snapshot and counts
- `/diff` with no previous snapshot reports that rather than failing
- A failed ingest leaves the serving catalog readable and unchanged

### Layer 4 — Refresh verification

`tests/test_mutate.py`, plus the `./run.sh verify-refresh` command. No network
beyond loopback.

The generator is test tooling, and its only job is to be trustworthy: if the
fixture is wrong, every assertion built on it is worthless. So these tests are
about the generator's own honesty.

- The copy is byte-identical to the source, and the source is unchanged afterwards (every file hashed)
- Two generations are byte-identical, so a failure cannot be blamed on fixture drift
- An unknown change `kind`, an unknown assertion, or a missing SKU is rejected at construction
- Each injection lands where it claims: the page exists and extracts, the card links it, the tier document is untouched where it should be
- **Every injected page is reachable by the crawler's own selectors** — an added page no category links to is never crawled, and the verification would then fail for the wrong reason
- Verification detects a missed change, a misattributed change and a spurious change, each producing a **distinct named failure**
- A parse failure must be reported as a parse failure and must **not** also be reported as withdrawn
- "Page never crawled" produces a different failure from "page crawled but misreported"
- The scratch directory is git-ignored, so derived HTML cannot be committed by accident

The four loopback-bound tests skip when loopback is unreachable (they do not
fail), so the suite still passes under `unshare -rn`. The behaviour they cover is
exercised by `./run.sh verify-refresh`, which runs in the normal environment.

### Layer 5 — Evaluation harness

28 recorded requests against the running system. This is the layer the brief explicitly asks for. All 28 run, but not all against one catalog: 24 against the committed v1 snapshot and 4 against the mutated v2 snapshot that `verify-refresh` builds. A case names the catalog its requirement needs, and a run names the catalog it scored.

**Four axes, scored separately.** The reason for separating them: a case can have perfect prices and the wrong products, and a single pass/fail would hide that.

```
retrieval   did the right SKU set come back?
match       was each stated justification accurate?
pricing     was the total right to the satang?
reply       would a salesperson send this?
```

**Coverage.** Each of these must have at least one case:

| Behaviour | Why it needs a case |
|---|---|
| budget × quantity | the brief's own example; quantity determines the verdict |
| budget flips at low quantity | proves the comparison is at the requested quantity |
| sale suppresses volume | PR3, and the sale price is nearly invisible in the markup |
| tier boundary | PR2, at both a met and an unmet boundary |
| small order: delivery + VAT | PR4/PR5, the case where VAT-on-subtotal is detectable |
| above threshold | PR4 free-delivery path |
| multi-item, threshold crossed only in aggregate | the only case that catches per-line delivery |
| prose-only page | shape 4 extraction |
| `<dl>` spec page | shape 2 extraction |
| pounds-only weight | conversion with no grammage given |
| both weight forms stated | conversion cross-check |
| out of stock → refuse | PR8, both instances |
| discontinued → refuse | PR8, v2 only |
| no match → alternatives | requires a budget below the cheapest item |
| clarifying question | ambiguous request |
| missing quantity → clarify | because the answer changes |
| printing notation | `4/4`, `cmyk`, `duplex` synonyms |
| budget including VAT | PR7 assumption stated |
| pack-size mismatch | Trap: "under 250 a pack" across 50 vs 500 sheets |
| inapplicable-attribute filter | plain paper must not be excluded by a printing constraint |
| shade vs print colour | the same word selects different fields |
| per-item tiers | two similar items do not pool quantity |
| unicode size form | `8½` vs `8.5` — one is invisible to the obvious filter |
| injection in description | untrusted text has no effect |
| 28 lb / 32 lb | v2 only — unverifiable against v1 |

**Cases that cannot run are recorded as such.** Two conversion cases depend on products that do not exist in v1. They are marked *not applicable*, with the reason, rather than omitted or counted as passing.

**Results format.** Expected against actual, per case, per axis. Failures stay in, with a cause.

```
| # | request | expected SKUs | actual SKUs | retrieval | expected total | actual total | pricing | notes |
```

### Layer 6 — Semantic tiebreak

`tests/test_embeddings.py` and `tests/test_semantic_api.py`. **No network** unless
a test is explicitly marked; the suite must pass under `unshare -rn`, where
loopback is down.

The capability's whole safety claim is that similarity reorders without changing
membership, so that is what the layer is built around.

- **The invariant across the entire recorded set**, not a spot check: for all 28 cases the returned SKU set is identical with the term enabled and disabled. The scores are adversarial — the most similar product is deliberately the one the old ranking put *last* — so any case where membership could shift has the best chance to show it
- An item failing a hard requirement is never introduced, however similar
- A qualifying but lexically distant item is never excluded
- The unconfigured key is asserted as the **exact** 3-tuple, not as an equivalent ordering — a constant `0.0` would order identically while still being a different key
- Both call sites (`search()` on matches, `_relax()` on alternatives) order by similarity, so the two paths cannot diverge
- Equal similarity still resolves totally via the SKU term; two runs return the same order
- A dead provider still answers the request, and the degradation is **reported** (`semantic: "unavailable"`), not silent
- With no provider configured the HTTP response has no `semantic` key and candidates have no `similarity` field — the previous shape, verified rather than assumed
- Receipt checks reject a malformed vector instead of scoring with it: mismatched dimension, non-finite value (via `1e400`, the path that is actually reachable), un-normalised vector, changed dimension between calls
- The client sends no `Authorization` header and has no API-key setting
- Float32 normalisation is **accepted**: measured worst case is 6.5e-7 off unit length, so a strict `norm == 1.0` check would reject every real response
- The measurement command's verdict rule (up = improvement, down = regression) is asserted directly, so the definition cannot drift toward the result

Provider-dependent tests are marked `needs_embedding` and **skip** when no
provider answers — with a stated reason, reported in the summary, never counted
as a pass. There are two distinct skip reasons: no loopback at all (offline run),
and loopback present but nothing listening.

### Layer 7 — Observability

`tests/test_records.py`, `tests/test_metrics.py`, `tests/test_observability_api.py`.
No network. The layer is built around one question: **can this metric fail?**

- **The metric is shown able to fail.** A reply's stated total is corrupted and the count must become non-zero *and* name the affected request. Without that test, "reads zero" is indistinguishable from "never runs" — the two would print identically
- The comparison goes through `recompute_totals`, asserted by **AST** inspection rather than a substring search, so a docstring explaining why `quote()` is avoided does not trip it. It must not read `quoted_total` either — comparing the engine's figure to itself agrees by construction
- **Metrics are derived, not counted.** One record line is deleted and the metric must move to match. The module's AST is checked for a module-level tally incremented across calls; `THRESHOLDS` is a constant dict and is not one
- Every rate returns `null` on an empty basis, and the payload carries `record_count`, `window`, `has_data` and a note
- `zero_result_rate` excludes `clarified` and `refused` from **both** numerator and denominator; `fallback_rate`'s denominator is model-configured requests only, so a deployment without a model is not permanently alarming
- p95 is nearest-rank, checked against the rank formula for eight sizes, and asserted to be a value some request actually experienced
- **Two concurrent writers produce 80 well-formed lines**, not an interleaved one
- A write failure is noted and swallowed: the request still returns its normal response with the log path replaced by a directory
- **A sentinel credential set in the environment, with a model client that raises quoting it, appears nowhere in the record** — and the redaction is marked, so a reader can tell an error was scrubbed. The production pattern list and the hygiene test's list are asserted to agree, since production code may not import from tests
- Request text is absent by default; a distinctive phrase appears nowhere in the written file at all, not merely absent from a field
- All four recording endpoints emit exactly one record; `/api/products`, `/api/health` and `/api/diff` emit none
- Stage timings sum to no more than the total, each is non-negative, and a stage that did not run is `0.0` rather than absent
- The eval log and the live log are separate files, and two harness runs are told apart by `run_id` — so re-running the harness, or running the negative control, cannot change what the next read reports

## What is tested where

| Requirement area | Unit | Extraction | Integration | Evaluation |
|---|---|---|---|---|
| Money exactness, rounding | ● | | | ● |
| Tier selection, sale precedence | ● | | | ● |
| Delivery per order, VAT basis | ● | | | ● |
| Budget at requested quantity | ● | | | ● |
| Weight / size normalisation | ● | ● | | ● |
| Four markup shapes, review floor | | ● | | ● |
| Absent-attribute semantics | | ● | ● | ● |
| Alias and notation handling | ● | | | ● |
| Ranking determinism | ● | | | ● |
| `match_reasons` accuracy | ● | | | ● |
| Clarify / no-match / refuse | | | ● | ● |
| No invented products | | | ● | ● |
| Stated figures match computed | | | ● | ● |
| Snapshot swap and diff | | | ● | ● |
| Diff change kinds, all six | | | ● | |
| Parse failure vs withdrawal | | ● | ● | |
| Discontinued item refusal | | ● | ● | ● |
| Untrusted text / injected instruction | | ● | ● | ● |
| Pound conversions for 28/32 lb | ● | ● | | ● |
| Budget and delivery boundaries | ● | ● | | ● |
| Four-outcome enum, error contract | | | ● | ● |
| Untrusted text | | ● | ● | ● |
| Mutated-site refresh verification | | | ● | |
| Observability: records, metrics, no credentials | ● | | ● | ● |

## Deliberately not tested

| Not tested | Why |
|---|---|
| The site's own HTML validity | Not our code. A malformed page becomes a review row. |
| Model output quality | The model is not in the correctness path. Its fallback rate is measured instead. |
| Load and concurrency beyond read-only serving | Single local user. One test asserts concurrent reads succeed against a consistent snapshot. |
| Live network availability during unit tests | Tests must pass offline. Network is exercised only by a real ingest, and loopback-only by `verify-refresh` (whose loopback tests skip when loopback is down). |
| Browser rendering | The reply is plain text by design (see `DESIGN.md`). |

## Running the tests

```
./run.sh test             # 937 tests: unit + extraction + integration + observability; offline, no model
./run.sh eval             # 28 recorded cases against the committed snapshot
./run.sh metrics          # the five operational measures, derived from request records
./run.sh metrics --eval   # the same measures over the most recent evaluation run
./run.sh verify-refresh   # mutate a copy of the site, refresh against it, verify (~55s)
```

The unit and integration layers must pass with the network disconnected and no credentials present. If a test needs either, it belongs in the evaluation layer instead.

## Regression policy

- A bug found during the demo round becomes a test before it becomes a fix.
- A changed expectation is only legitimate if it was recomputed from source. If the recomputation and the old expectation disagree, one of them is a finding — establish which before changing anything.
- The extraction fixtures are copies of real pages. When the site changes shape, add a fixture; do not edit an existing one to match.
