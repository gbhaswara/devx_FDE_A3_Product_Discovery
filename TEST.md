# TEST.md — testing and evaluation strategy

How correctness is established for the A3 submission. Requirements are in `openspec/changes/add-paperlane-product-discovery/specs/`; each task in `tasks.md` names its own verification.

## The problem this strategy solves

The brief's scoring emphasis is *"right products and totals to the satang on unseen requests, including edge cases"* and *"we care more about evidence that your system works, and honesty about where it does not, than about polish."*

Two failure modes matter more than any others, and they need different defences:

1. **A correct-looking wrong answer.** Right price, wrong products — or right products, wrong price. Nothing crashes, so only a recorded expectation catches it.
2. **A wrong expectation.** A test that asserts the wrong number will cause correct code to be "fixed" until it matches the error. This is worse than having no test, and it is the failure I actually hit while writing `ANALYZE_01.md`: two totals were transcribed wrongly and were only caught by recomputing them from source.

So the strategy has two rules that are not negotiable:

- **Every expected total is recomputed from catalog data with exact arithmetic, never transcribed.** A test fixture that cannot be regenerated is a liability.
- **Failing cases stay in the results.** The brief asks for cases where the system fails.

## Test layers

Four layers, each answering a different question. They are deliberately separate, because a failure in one should not be attributable to another.

| Layer | Question it answers | Runs without network | Runs without model |
|---|---|---|---|
| 1. Unit | Does this function compute what the specification says? | yes | yes |
| 2. Extraction | Does this markup produce these fields? | yes (fixtures) | yes |
| 3. Integration | Does the whole path produce this quote? | yes (fixtures) | yes for `/quote` |
| 4. Evaluation | Does the system answer these 28 real requests correctly? | no (needs model for `/chat` cases) | partially |

Of the 28 recorded cases, **24 run against v1** and **4 are v2-only** — cases 21 (discontinued), 22 (injected instruction), 23 (`28 lb`) and 24 (`32 lb`). Those four are marked not-applicable until the mutated v2 site exists: v1 has zero discontinued items (T4), no prompt injection, and no `28 lb` or `32 lb` product (T7). The brief asks for at least 10 cases; 24 executable is well clear, and the four deferred ones are recorded as deferred rather than silently dropped or counted as passing.

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

### Layer 4 — Evaluation harness

28 recorded requests against the running system. This is the layer the brief explicitly asks for.

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
| Four-outcome enum, error contract | | | ● | ● |
| Untrusted text | | ● | ● | ● |

## Deliberately not tested

| Not tested | Why |
|---|---|
| The site's own HTML validity | Not our code. A malformed page becomes a review row. |
| Model output quality | The model is not in the correctness path. Its fallback rate is measured instead. |
| Load and concurrency beyond read-only serving | Single local user. One test asserts concurrent reads succeed against a consistent snapshot. |
| Live network availability during unit tests | Tests must pass offline. Network is exercised only by a real ingest. |
| Browser rendering | The reply is plain text by design (see `DESIGN.md`). |

## Running the tests

```
./run.sh test     # unit + extraction + integration; offline, no model required
./run.sh eval     # 28 recorded cases against a loaded snapshot
```

The unit and integration layers must pass with the network disconnected and no credentials present. If a test needs either, it belongs in the evaluation layer instead.

## Regression policy

- A bug found during the demo round becomes a test before it becomes a fix.
- A changed expectation is only legitimate if it was recomputed from source. If the recomputation and the old expectation disagree, one of them is a finding — establish which before changing anything.
- The extraction fixtures are copies of real pages. When the site changes shape, add a fixture; do not edit an existing one to match.
