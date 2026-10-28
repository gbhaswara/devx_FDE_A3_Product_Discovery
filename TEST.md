# TEST.md — testing and evaluation strategy

How correctness is established for the A3 submission. Requirements are in the eleven main specs under `openspec/specs/`; each task in the archived changes' `tasks.md` names its own verification.

## The problem this strategy solves

The brief's scoring emphasis is *"right products and totals to the satang on unseen requests, including edge cases"* and *"we care more about evidence that your system works, and honesty about where it does not, than about polish."*

Two failure modes matter more than any others, and they need different defences:

1. **A correct-looking wrong answer.** Right price, wrong products — or right products, wrong price. Nothing crashes, so only a recorded expectation catches it.
2. **A wrong expectation.** A test that asserts the wrong number will cause correct code to be "fixed" until it matches the error. This is worse than having no test, and it is the failure I actually hit while writing `devx_FDE_A3_Product_Discovery/docs/pre/ANALYZE_01.md`: two totals were transcribed wrongly and were only caught by recomputing them from source.

So the strategy has two rules that are not negotiable:

- **Every expected total is recomputed from catalog data with exact arithmetic, never transcribed.** A test fixture that cannot be regenerated is a liability.
- **Failing cases stay in the results.** The brief asks for cases where the system fails.

## Test layers

Eight layers, each answering a different question. They are deliberately separate, because a failure in one should not be attributable to another.

| Layer | Question it answers | Runs without network | Runs without model |
|---|---|---|---|
| 1. Unit | Does this function compute what the specification says? | yes | yes |
| 2. Extraction | Does this markup produce these fields? | yes (fixtures) | yes |
| 3. Integration | Does the whole path produce this quote? | yes (fixtures) | yes for `/quote` |
| 4. Refresh verification | Does a declared mutation of the site get reported correctly? | loopback only | yes |
| 5. Evaluation | Does the system answer these 28 real requests correctly? | no (needs model for `/chat` cases) | partially |
| 6. Semantic tiebreak | Does similarity reorder without changing which products qualify? | no (needs an embedding provider) | yes |
| 7. Observability | Can each recorded measure be shown to move when it should? | yes | yes |
| 8. Conversation memory | Is a turn merged, disclosed and numbered the way the rule says? | yes | yes |

Of the 28 recorded cases, **24 run against v1** and **4 run against v2** — cases 21 (discontinued), 22 (injected instruction), 23 (`28 lb`) and 24 (`32 lb`). v1 has zero discontinued items (T4), no prompt injection, and no `28 lb` or `32 lb` product (T7); the mutated v2 catalog that `./run.sh verify-refresh` builds has all four, so those cases now **run and pass** there rather than being marked inapplicable.

Inapplicability is therefore a fact about a *named catalog*, not a permanent verdict on a case: each case declares `requires_catalog`, and a run declares which catalog it scored. Seven cases are pinned to v1 (their expected product *sets* enumerate v1's exact offering, which v2 genuinely extends); rewriting those from v2's own output would make the expectation circular. The full picture is in `eval/results.md`.

```bash
./run.sh verify-refresh --keep
./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb   # 21/21
./run.sh eval                                                          # 24/24
```

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
- The page depends on no external host: the script it names is served from this
  origin, and the bytes match the vendored build's recorded SHA-384
  (`test_ui_offline.py` — it also asserts the form is still htmx-only, which is
  what makes a missing script a silent no-op rather than a server round-trip)
- The catalog column lists every product exactly once, escapes crawled text,
  prices each row at the same figure `/api/quote/lines` returns for one unit,
  and resolves every one of the 72 names back to its own product through the
  interpreter — the property the click-to-prefill behaviour rests on. With no
  snapshot it renders the remedy instead of failing (`test_ui_catalog.py`)
- The page is two equal tracks, and the catalog is a `<details>` per category
  with every group closed on arrival — the shape that puts all four categories
  on screen instead of hiding three below an inner scrollbar. The panel has no
  `max-height` or `overflow-y`, and a click inside a collapsed group still
  fills the search box, because the handler is delegated to `document`

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

28 recorded requests against the running system. This is the layer the brief explicitly asks for. All 28 run, but not all against one catalog: 24 against the committed v1 snapshot and 4 against the mutated v2 snapshot that `verify-refresh` builds. A case names the catalog its requirement needs, and a run names the catalog it scored. Two commands produce the two numbers: `./run.sh eval` scores 24/24 on v1, and `./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb` (after `./run.sh verify-refresh --keep`) scores 21/21 on v2.

**Five axes, scored separately.** The reason for separating them: a case can have perfect prices and the wrong products, and a single pass/fail would hide that. `interpretation` was added first in the order because it is the earliest thing that can go wrong — a request read as the wrong size produces a valid quote for something nobody asked for, which the other four axes cannot see.

```
interpretation   was the request read as the customer meant it?
retrieval        did the right SKU set come back?
match            was each stated justification accurate?
pricing          was the total right to the satang?
reply            would a salesperson send this?
```

`interpretation` scores a case's derived criteria against a **declared subset** of the fields the request states, plus a declared set of fields it must **not** invent. "Under 250 a pack" becoming "80 gsm or lighter" is the second kind. The expectation is deliberately never a transcription of `criteria.describe()` — that would be the engine agreeing with itself — and a test asserts every case's declared set is smaller than what the engine derives, so the axis can always disagree independently. A case recording no criteria reports `n/a`.

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

**A held-out set exists, and it fails.** `eval/held-out-cases.json` is 11 requests in phrasings that appear nowhere in `cases.json`, written after the rules path was finished and **not** used to develop it. Expectations were derived by filtering the catalog directly and applying the documented ranking chain, never by reading the engine's response. Three of eleven fail, all one root cause: an unmappable noun is dropped rather than honoured, so the answer silently widens — "the pink A4 coloured paper" widens from one product to all seven A4 coloured papers, "pastel grey A4 paper" returns all 33 A4 papers when no grey is stocked, and "30 lb letter paper" returns all 19 letter papers. A test asserts at least one held-out failure **remains**, because a held-out set that passes completely is evidence about its author. It is a separate file, not cases 29+, and a default `./run.sh eval` does not load it.

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

### Layer 8 — Conversation memory

`tests/test_conversation.py`, `tests/test_conversation_api.py`,
`tests/test_conversation_eval.py`, plus `tests/test_single_turn_unchanged.py`. No
network, no model.

A conversation is the one place where the reply for one request depends on an
earlier request, so the layer is built around the two ways that can go wrong: a
turn that should have continued and did not, and a turn that should not have
inherited something and did.

- **The merge rule, field by field.** The current turn's value wins where it
  stated one; the conversation's is used where it did not. A subject — category or
  size — replaces the criteria; a refinement does not
- **Weight is not a subject.** *Make it 100 gsm* adjusts the paper under
  discussion rather than naming a new one — the first version of the rule got this
  wrong and discarded the size, which is recorded in `docs/conversation-memory.md`
- **A bare number is a quantity only in a refinement.** *A4 80gsm* must not become
  quantity 80, and a bare number in a turn that also states a budget resolves to
  *not stated* rather than quoting 130 reams
- **A bare number that is also a catalog grammage is still the quantity**
  (`BUG.md` A17). *100* is a stocked weight, so interpretation files it as one; in
  a refinement the merge reclaims it and the earlier weight is carried instead.
  Without that, one turn changed both the quantity and the paper, and the wrong
  weight outlived the turn that caused it — returning to a quantity that had
  quoted before came back as no-match
- **The reply discloses what it remembered**, name for name, and a fresh request
  says nothing about earlier turns
- **Nothing that is not remembered is called remembered.** A restated field is not
  a carried field
- **No request text is stored**, asserted by iterating every string the store holds
  — inspection of the guarantee, not of the schema
- **The turn number always advances** past the retained-turn cap (`BUG.md` A14):
  25 turns number 1…25, and the CLI reports turn 22 at 22
- **Refinements outlive the retained history.** The store keeps the last
  `MAX_TURNS` turns, but the merged criteria are kept outside that list, so the
  21st refinement is as exact as the 2nd — pinned at 20 refinements with
  `max_turns=3`. The cap bounds history, not the number of changes a customer can
  make
- **A first turn that states only a quantity, or only a budget, is still a
  continuation basis** (`BUG.md` A12), so the next turn extends it
- **A turn that understood nothing is answered fresh but does not erase the
  conversation** (`BUG.md` A13): the turn is answered from an empty request and is
  still recorded, and the next turn continues from the last thing actually asked
- **The single-turn path is byte-identical to before the feature existed.**
  `tests/test_single_turn_unchanged.py` pins a SHA-256 of every case's
  `{outcome, text}`, recorded from the commit before conversation memory
  (`d4a67db`). A digest failure is not "update the digest" — it is "which reply
  changed, and why"

The harness is shown able to fail: `eval/conversation-negative-control.json` is
five conversations each wrong in exactly one way — a quantity not carried, a new
subject wrongly inheriting, a missing disclosure, a restated field called
remembered, a wrong outcome — and the run exits 1 with all five rejected. The
four `BUG.md` regressions (A12, A13, A14, A17) were each proven falsifiable by
reverting the fix and watching the corresponding case fail, then restoring it.

The pricing axis of a conversation case compares a fresh turn against the
standalone run of the same request, and both go through the same code, so it is
**not** falsifiable from a case file and is not claimed to be; a `quoted` outcome
carrying a total is checked structurally instead.

## Test module inventory

29 modules, gathered by `--collect-only`. Counts are tests, not lines. The layer column names a module's **primary** layer; several span more than one (for example `test_api.py` exercises the conversation wiring as well as the quote path).

| Module | Tests | Layer |
|---|---|---|
| `test_aliases.py` | 106 | 1 |
| `test_api.py` | 76 | 3 |
| `test_ask_cli.py` | 32 | 3 |
| `test_assistant.py` | 86 | 3 |
| `test_catalog.py` | 51 | 3 |
| `test_conversation.py` | 67 | 8 |
| `test_conversation_api.py` | 38 | 8 |
| `test_conversation_eval.py` | 19 | 8 |
| `test_crawl.py` | 13 | 2 |
| `test_embeddings.py` | 66 | 6 |
| `test_evaluate.py` | 71 | 5 |
| `test_extract.py` | 57 | 2 |
| `test_hygiene.py` | 13 | 7 |
| `test_ingest.py` | 22 | 2 |
| `test_metrics.py` | 59 | 7 |
| `test_model.py` | 42 | 3 |
| `test_money.py` | 25 | 1 |
| `test_mutate.py` | 77 | 4 |
| `test_normalize.py` | 37 | 1 |
| `test_observability_api.py` | 37 | 7 |
| `test_pricing.py` | 55 | 1 |
| `test_records.py` | 73 | 7 |
| `test_search.py` | 45 | 1 |
| `test_semantic_api.py` | 15 | 6 |
| `test_single_turn_unchanged.py` | 3 | 8 |
| `test_snapshot_cli.py` | 5 | 3 |
| `test_snapshot_path.py` | 26 | 7 |
| `test_ui_catalog.py` | 26 | 3 |
| `test_ui_offline.py` | 9 | 3 |
| **Total** | **1251** | |

Online: 1251 collected, 3 skip (provider-dependent) — 1248 passed.
Offline (`unshare -rn`): 1251 collected, 8 skip — 1243 passed; the same three plus
the five loopback tests that legitimately cannot run without a network interface.

One further skip is state-dependent, not environmental: `test_evaluate.py` skips
its second-catalog case until `./run.sh verify-refresh --keep` has produced
`.refresh-verification/mutated.duckdb`. With that artefact present that skip
becomes a pass. The figures above are for a clean tree, which is what a fresh
clone sees — the artefact directory is git-ignored.

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
| Request read as meant (interpretation) | | | ● | ● |
| Held-out requests, unseen phrasing | | | | ● |
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
| Catalog freshness and snapshot path | ● | | ● | |
| Conversation merge rule, field by field | ● | | ● | ● |
| Disclosure of what was remembered | ● | | ● | ● |
| Turn numbering past the retained cap | ● | | ● | |
| Single-turn replies unchanged (digest) | ● | | | |
| Conversation negative control rejected | ● | | | |

## Deliberately not tested

| Not tested | Why |
|---|---|
| The site's own HTML validity | Not our code. A malformed page becomes a review row. |
| Model output quality | The model is not in the correctness path. Its fallback rate is measured instead. |
| Load and concurrency beyond read-only serving | Single local user. One test asserts concurrent reads succeed against a consistent snapshot. |
| Live network availability during unit tests | Tests must pass offline. Network is exercised only by a real ingest, and loopback-only by `verify-refresh` (whose loopback tests skip when loopback is down). |
| Browser rendering | The reply is plain text by design (see `DESIGN.md`). |
| A conversation's pricing axis from a case file | A fresh turn is compared against the standalone run of the same request, and both call the same pricing code, so the axis cannot disagree with itself. It is checked structurally instead — `quoted` must carry a total. Claiming a case file proves it would be false. |

## Running the tests

```
./run.sh test             # 1240 tests: unit + extraction + integration + observability + conversation; offline, no model
./run.sh eval             # 28 recorded cases against the committed snapshot (24/24)
./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb   # 21/21, after verify-refresh --keep
./run.sh eval --cases eval/held-out-cases.json   # 11 held-out requests, 8 pass 3 fail by design
./run.sh eval --cases eval/conversation-cases.json   # 12 conversations, 27 turns
./run.sh metrics          # the five operational measures, derived from request records
./run.sh metrics --eval   # the same measures over the most recent evaluation run
./run.sh verify-refresh   # mutate a copy of the site, refresh against it, verify (~55s)
```

The unit and integration layers must pass with the network disconnected and no credentials present. If a test needs either, it belongs in the evaluation layer instead.

Two layers are scored by their own harness rather than by pytest: the 28-case evaluation (`./run.sh eval`, 24 run against v1, 4 against v2) and the conversation set (`./run.sh eval --cases eval/conversation-cases.json`, 12 conversations / 27 turns, with a single-turn replay digest across the 22 comparable cases). Both have a negative control that exits 1. A third set is scored by the same harness but is deliberately **not** a regression set: `eval/held-out-cases.json` (11 requests, unseen phrasing, 3 known failures retained), run with `./run.sh eval --cases eval/held-out-cases.json`.

## Regression policy

- A bug found during the demo round becomes a test before it becomes a fix.
- A changed expectation is only legitimate if it was recomputed from source. If the recomputation and the old expectation disagree, one of them is a finding — establish which before changing anything.
- The extraction fixtures are copies of real pages. When the site changes shape, add a fixture; do not edit an existing one to match.

Three bugs found by probing the running service after the conversation-memory feature shipped are recorded in `BUG.md` Part 2b and follow this policy: A12 (a first turn that states only a quantity or only a budget), A13 (a turn that understood nothing erased the conversation), A14 (the turn number saturated at the retained cap). Each was registered before being fixed, each arrived with a test **and** a falsification check — the fix was reverted, the new test and eval case were confirmed to fail, and the fix restored. All three are FIXED, and Part 2b has no open entries.
