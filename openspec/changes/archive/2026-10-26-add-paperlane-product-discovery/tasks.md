# Tasks

Ordering follows design.md Decision 12: the deterministic core lands and is proven before the assistant, and Tier 2 items are independently droppable. Every group lands its own tests and documentation; group 10 is integration checking only.

## 1. Scaffold and dependencies

- [x] 1.1 Create the package layout under `devx_FDE_A3_Product_Discovery/` (`src/paperlane/`, `tests/`, `eval/`, `data/`) and verify every directory in design.md §"Repo layout" exists
- [x] 1.2 Add `pyproject.toml` with `duckdb`, `fastapi`, `uvicorn`, `httpx`, `selectolax`, `pydantic`, `pytest` and verify `uv sync` completes with no compilation step
- [x] 1.3 Add `run.sh` dispatching `ingest | serve | test | eval | diff` and verify `./run.sh` with no argument lists the subcommands and exits non-zero
- [x] 1.4 Add a `.gitignore` covering `.env`, `*.duckdb.wal`, and `__pycache__` and verify `git status` reports no credential or build artefacts in a fresh repo

## 2. Pricing engine (Tier 1 — highest-value work)

- [x] 2.1 Implement integer-satang money with an explicit half-up rounding helper and verify a test asserts half-up on an exact-half value and that no float appears in the money type
- [x] 2.2 Implement weight normalisation for all four published forms plus the agreed pound table and verify tests cover grammage, grams-per-square-metre, pounds-with-grammage, pounds-alone, and that an unlisted pound value raises
- [x] 2.3 Implement unit-price selection (highest qualifying tier, list-price fallback when no tier is met, sale overrides both) and verify tests cover the tier-met case, the below-lowest-tier case, and the sale-overrides-tier case
- [x] 2.4 Implement order assembly (subtotal, delivery evaluated once against the pre-tax subtotal, tax on subtotal plus delivery, total) and verify tests reproduce the hand-computed totals in `ANALYZE_01.md` §5 — the small-order case (A5 copy 3 reams, 391.62), the above-threshold case (A4 copy 50 reams, 6211.35), the no-tier-met case (A4 copy 1 ream, 298.53) and the mixed basket (3221.02)
- [x] 2.5 Implement budget comparison at the requested quantity with an inclusive upper bound and an explicit basis statement, and verify tests show the same product passing at a higher quantity and failing at a lower one
- [x] 2.6 Verify pricing is pure: a test asserts identical output across repeated calls and asserts a full quote is produced with no model client configured
- [x] 2.7 Document the pricing rules and their precedence in `docs/pricing.md` and verify every rule cites the requirement it satisfies

## 3. Catalog ingestion (Tier 1)

- [x] 3.1 Implement the rate-limited HTTP crawler with provenance capture and verify an ingest against the locally served site completes in roughly 105 requests without exceeding the permitted rate
- [x] 3.2 Implement discovery of both single-SKU pages and variant rows and verify the run yields 72 leaf SKUs from 36 product pages
- [x] 3.3 Implement the four-shape extraction ladder recording the shape used per page and verify one fixture per shape produces the same normalised fields
- [x] 3.4 Implement the review floor for unrecognised markup and verify an injected unknown-shape fixture lands in review with a reason and excerpt, and that the run does not raise
- [x] 3.5 Implement field-name normalisation across shapes, retaining raw label and value, and verify `Size`/`Paper size`/prose and `Colour`/`Shade` all map to one field each
- [x] 3.6 Implement size normalisation to a size code with numeric dimensions, covering decimal, vulgar-fraction and unicode-multiplication forms, and verify all three spellings of one size produce one code and an unmappable size is reported rather than left unset
- [x] 3.7 Implement weight capture including weight stated only in prose and verify all 36 pages yield a weight, including the pages with no labelled weight field
- [x] 3.8 Implement not-applicable semantics for printing attributes and verify a filter on those attributes does not exclude the plain-paper products
- [x] 3.9 Implement pack-size capture with the unit word retained as display text only and verify no filter or comparison depends on the unit word
- [x] 3.10 Implement sale, stock, restock-date and discontinued capture and verify the reference site yields exactly one sale item, two out-of-stock items and zero discontinued
- [x] 3.11 Implement the category-card versus product-page availability cross-check and verify an injected disagreement is flagged without either value being overwritten
- [x] 3.12 Implement the DuckDB snapshot writer with provenance on every row and verify the count of retrieved volume-pricing documents equals the count of SKUs advertising volume pricing, with no document for an absent SKU
- [x] 3.13 Add extraction tests using saved fixtures for all four shapes plus the unknown-shape case and verify the suite runs with no network access
- [x] 3.14 Document the four markup shapes and the normalisation rules in `docs/ingestion.md` and verify the documented fixture-to-field mapping matches the tests

## 4. Product search (Tier 1)

- [x] 4.1 Implement hard-constraint filtering over the catalog and verify a test asserts items contradicting a stated requirement are excluded
- [x] 4.2 Implement not-applicable attribute semantics in filtering and verify a printing constraint still returns the plain-paper products
- [x] 4.3 Implement the alias layer for size names, size dimensions, pound-weight names and printing notation and verify paired tests assert two phrasings of one requirement select the same items
- [x] 4.4 Implement context-based disambiguation of the colour term and verify a test asserts paper shade and print colour mode are selected by the accompanying noun, and that missing context yields a clarification rather than a choice
- [x] 4.5 Implement deterministic soft ranking with a defined total order and a stable final tiebreak and verify a test asserts identical order across repeated runs and that a tied pair orders consistently
- [x] 4.6 Implement `match_reasons` as a by-product of filtering and verify a test asserts one record per satisfied requirement with requested and actual values, and that a quantity-dependent requirement records the quantity and tier used
- [x] 4.7 Implement unavailable-item marking in results and verify a test asserts out-of-stock and discontinued items are returned with their state rather than omitted or offered
- [x] 4.8 Implement no-match reporting and ordered alternative relaxation with the relaxed requirement named and verify tests cover a genuinely unmatched request and that each alternative states what was relaxed
- [x] 4.9 Document the filter semantics and ranking order in `docs/search.md` and verify the documented order matches the implementation's tiebreak chain

## 5. Sales assistant (Tier 1)

- [x] 5.1 Implement criteria models with validation against catalog vocabulary and verify invalid interpretation does not reach pricing and produces a clarification
- [x] 5.2 Implement the model client with response sanitisation, a sufficient output-token budget, and no reliance on structured-output flags, and verify a recorded-fixture test covers the stray-terminator and empty-content cases
- [x] 5.3 Implement rule-based interpretation for the common request shapes and verify tests cover the shapes the recorded evaluation set uses
- [x] 5.4 Implement fallback selection between model and rules with disclosure of the path used and verify a test asserts a request with no model configured still returns a usable outcome and reports rule-based interpretation
- [x] 5.5 Implement the reply contract (matches, per-product justification, full breakdown with the applied discount identified) and verify a test asserts all required fields are present and that the identified discount matches the pricing layer
- [x] 5.6 Implement the clarify decision rule (ask only when the detail is needed, absent, uninferable and answer-changing; at most two at once) and verify tests cover the missing-quantity case and the case where a detail must not be asked
- [x] 5.7 Implement the refusal paths for out-of-stock and discontinued items and verify tests assert each is refused with its distinguishing information and not quoted
- [x] 5.8 Implement the no-invented-products assertion and verify a test injects a reply referencing an absent product and asserts it is removed and logged rather than returned
- [x] 5.9 Implement the stated-figures-match-computed-figures check and verify a test injects a mismatched total and asserts the discrepancy is detected and recorded
- [x] 5.10 Implement reply prose that names products as the catalog names them and uses the product's own unit and verify a test asserts no internal identifier is used as the primary description
- [x] 5.11 Document the assistant's decision rules in `docs/assistant.md` and verify each rule names the outcome it produces

## 6. Quote API (Tier 1)

- [x] 6.1 Implement the structured quoting endpoint and verify it returns candidates and figures with no model client available
- [x] 6.2 Implement the conversational endpoint returning reply, interpretation, candidates and metadata and verify a test asserts the interpreted requirements are present in the response
- [x] 6.3 Implement the four-outcome status enum with its per-outcome required fields and verify tests cover one response of each outcome and assert the required fields are populated
- [x] 6.4 Implement the client-error contract for malformed bodies, implausible quantities and invalid criteria and verify tests assert a client error identifying the problem and that no stack trace is exposed
- [x] 6.5 Implement the missing-snapshot response with its remedy and verify a test asserts the stated remedy is present
- [x] 6.6 Implement model-unavailable degradation at the endpoint level and verify a test with an unreachable model asserts a normal outcome rather than a server error
- [x] 6.7 Implement the catalog inspection, health and snapshot-comparison endpoints and verify tests assert the health report names the snapshot and counts, and that comparison with no prior snapshot reports that rather than failing
- [x] 6.8 Document every endpoint with request and response examples in `docs/api.md` and verify each documented example is exercised by a test

## 7. Catalog refresh and diff (Tier 1)

- [x] 7.1 Implement build-then-swap snapshot replacement and verify a test asserts a failed ingest leaves the previously serving catalog readable and unchanged
- [x] 7.2 Implement read-only per-request connections and verify a test asserts reads succeed against a consistent snapshot across concurrent requests
- [x] 7.3 Implement the diff report covering added, withdrawn, price-changed with before and after, availability-changed and parse-failed and verify a test against a mutated fixture reports each kind
- [x] 7.4 Implement explicit no-change reporting and verify a test asserts an identical re-ingest reports no change rather than an empty success
- [x] 7.5 Implement review-set persistence across refreshes and verify a test asserts an unresolved item is still reported on the following ingest
- [x] 7.6 Verify the committed-snapshot path: start the service with a stored snapshot and no crawl, confirm it serves, then rebuild from source and confirm the rebuilt snapshot matches on product and price counts
- [x] 7.7 Document the refresh procedure in `docs/refresh.md` and verify the documented commands run as written from a clean shell

## 8. Evaluation harness (Tier 1)

- [x] 8.1 Build the recorded case set with expected products and exact expected totals and verify each expected total is recomputed from catalog data by exact arithmetic rather than transcribed
- [x] 8.2 Ensure the set covers the required behaviours and verify by inspection that each of the listed difficult behaviours has at least one case
- [x] 8.3 Implement the runner producing expected-versus-actual per case and verify one command produces the results with no manual steps
- [x] 8.4 Implement four-axis scoring reported independently and verify the results distinguish a case with correct prices but wrong products
- [x] 8.5 Implement retention of failing cases and not-applicable recording and verify a deliberately failing case stays in the results with its cause, and a case depending on absent data is marked not applicable rather than passing
- [x] 8.6 Implement the interpretation-strategy comparison and verify both strategies are applied to the same requests with outcomes reported side by side
- [x] 8.7 Verify the runner completes with no model available, reporting the structured cases as run and the remainder as not run
- [x] 8.8 Record the results in `eval/results.md` and verify the file contains both passing and failing cases with their expected and actual values

## 9. Submission documentation (Tier 1)

- [x] 9.1 Write `README.md` with the five named sections including known limitations and what would be done with another week, and verify the run instructions are five commands or fewer executed from a clean shell
- [x] 9.2 Populate known limitations with the concrete entries identified in analysis, including the unverified weight conversions and the single-turn scope, and verify each limitation is stated as a limitation rather than a strength
- [x] 9.3 Write `CUSTOMER_SUMMARY.md` as one page for the business owner covering what was built, how well it works, what it cannot do, and what to do next, and verify it contains no implementation jargon
- [x] 9.4 Add the paragraph on AI-tool usage to `README.md` and verify it states which tools were used and for what
- [x] 9.5 State the two-tier scope framing in both `README.md` and `CUSTOMER_SUMMARY.md` and verify each names which items are the core and which are extras
- [x] 9.6 Verify no credential appears anywhere in the repository and confirm the README documents environment-variable configuration only

## 10. Tier 2 extras (each independently droppable)

- [x] 10.1 Add multi-item basket quoting and verify a test asserts delivery is charged once against the combined pre-tax subtotal and that a mixed order crossing the threshold only in aggregate pays no delivery
- [x] 10.2 Add the single-page interface and verify every outcome renders, including clarification, no-match and refusal, driven by the same endpoints as the evaluation harness
- [x] 10.3 Add the diff report as a demo artefact and verify it renders each change kind against a mutated site
  - Diff report: `GET /api/diff`, `./run.sh diff`, `diff_snapshots()` with all six change kinds.
  - **Closed by `add-mutated-site-refresh-harness`**: `./run.sh verify-refresh` ingests a mutated copy of the site and the diff reports all six kinds — 6 added, 1 withdrawn, 1 price changed, 2 availability changed, 1 tier changed, 1 parse failed — each verified against a manifest declared in advance. See `docs/refresh-verification.md`.
- [x] 10.4 Build a mutated copy of the site covering added and withdrawn items, price and tier changes, an unknown markup shape, both missing weight conversions, an exact budget boundary, an exact delivery threshold, and an embedded instruction, and verify a refresh against it reports every injected change
  - **Closed by `add-mutated-site-refresh-harness`**: `src/paperlane/mutate.py` injects all twelve changes, `src/paperlane/refresh.py` serves and ingests the copy, and `verify()` checks the report against the manifest in both directions. Every injected change is reported under the correct kind.
- [x] 10.5 Add the hybrid semantic tiebreak and verify it only reorders results that already satisfy every hard constraint, with a test asserting it cannot introduce or exclude an item
  - **Closed by `add-semantic-tiebreak`**: similarity is a ranking term, never a filter — it scores only candidates that already passed `_evaluate()`, so there is no code path from a score to membership. Measured: the invariant holds across all 28 recorded cases with adversarial scores. Sorts *after* price (before price it regressed 6 of 28). See `docs/semantic-ranking.md`.
- [x] 10.6 Add structured logging and the five metrics and verify each metric is derivable from the records and that the disagreement metric reads zero on the evaluation run
  - **Closed by `add-observability`**: `src/paperlane/records.py` writes one JSONL line per handled request, `src/paperlane/metrics.py` derives all five measures on every read with no counter incremented during handling, and `GET /api/metrics` / `./run.sh metrics` expose them. Disagreement reads 0 over 17 checked replies on a real `./run.sh eval` run. See `docs/observability.md`.
- [x] 10.7 Verify credentials and unbounded conversation text are absent from the logs and records
  - **Closed by `add-observability`**: redaction lives in `RequestRecord.__post_init__` (configured key values, then credential-shaped patterns), motivated by a real leak where a client's exception message carried its own key through `fallback_reason`. Request text is absent by default — the record carries `request_chars` and a 16-character digest; capture is opt-in via `PAPERLANE_RECORD_TEXT`. `tests/test_hygiene.py::TestProducedRecordsCarryNoCredential` and `tests/test_observability_api.py::TestNoRequestTextByDefault` assert both. Recorded as defect A11 in `BUG.md` (`ANALYZE_01.md` §9a specified raw text; the spec won).

## 11. Integration verification

- [x] 11.1 Run the full test suite from a clean shell and verify it passes with no network access and no model configured
  - Verified: 590 tests pass under `unshare -rn` (network namespace with no interfaces) and with `PAPERLANE_LLM_*` unset. Confirmed the namespace really had no network by failing to reach the model endpoint from inside it.
- [x] 11.2 Run ingest, then serve, then the evaluation set end to end and verify the recorded results reproduce
  - Verified: ingest (103 requests, 72 SKUs, 59 tier docs, 0 review items) → serve (`GET /` 200, `/api/health` 72 products / 105 tiers) → `POST /api/ask` on the brief's own example returned 4,237.20 → `./run.sh eval` reproduced 24/24 passing.
- [x] 11.3 Re-ingest an unchanged site and verify the diff reports no change
  - Verified: second ingest reported `no_change: true` with all six change lists empty.
- [x] 11.4 Re-ingest the mutated site and verify every injected change is reported and no page disappears without appearing in review
  - **Closed by `add-mutated-site-refresh-harness`**: the verification asserts all twelve changes appear under their declared kind, and that `PL-CP-A4-88-ODD` (unparseable markup) is reported as a parse failure and **not** as a withdrawal — the check that a page cannot disappear silently. The real site re-ingest still yields 72 SKUs and 0 review items.
- [x] 11.5 Verify the five-command README path from a clean checkout reproduces a working service
  - Verified against a pristine copy (no `.venv`, no `*.previous.duckdb`, only the committed snapshot): `uv sync` → 590 tests pass → `serve` returns 200 with 72 products → `eval` 24/24 → `diff`.
  - `diff` reports `comparable: false` there, which is correct: a fresh checkout has no baseline until it has refreshed once. The README now says so.
