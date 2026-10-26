# Tasks

## 1. Mutation generator

- [ ] 1.1 Add a generator module that copies the committed `paperlane/` site into a target directory and verify a test asserts the copy is byte-identical to the source before any injection, and that the source directory is unchanged afterwards (compare a hash of every file)
- [ ] 1.2 Define the manifest schema as a dataclass or typed dict with `kind`, `sku`, `before`, `after` and a required `assertion` field, and verify a test asserts an unknown `kind` is rejected and that every manifest entry names one of the six diff change kinds or the parse-failure kind
- [ ] 1.3 Implement the added-item injection (new product page in one of the four known shapes, plus a card linking it from a category page) and verify a test asserts the generated page is reachable by walking the same selectors `_discover_category_urls` and `_product_links` use
- [ ] 1.4 Implement the withdrawn-item injection (remove one product page and its category card) and verify a test asserts the page is gone and no card still links to it
- [ ] 1.5 Implement the price-change injection on its own SKU and verify a test asserts the page's list price differs from the source by the declared amount and that the SKU's tier document is untouched
- [ ] 1.6 Implement the tier-change injection on a different SKU and verify a test asserts the tier document differs as declared and that the SKU's list price is untouched — the two tasks share a test asserting the two SKUs are distinct, so attribution stays separable
- [ ] 1.7 Implement the availability-change injection (in stock → out of stock with a restock date, and a separate item → discontinued) and verify a test asserts the page carries the new state and that the discontinued item is reported as discontinued by search rather than omitted
- [ ] 1.8 Implement the unknown-markup-shape injection as a new product page matching none of the four shapes, linked from a category, and verify a test asserts `_detect_shape()` returns `SHAPE_UNKNOWN` for it and that it produces a review row
- [ ] 1.9 Implement the embedded-instruction injection as a new product page whose description field carries an instruction addressed to an automated reader, written as plausible merchant copy, and verify a test asserts extraction succeeds with no special-case code path and that the instruction text lands in a data field rather than changing any criteria
- [ ] 1.10 Implement the 28 lb / 32 lb injections as products at 105 gsm and 120 gsm and verify a test asserts both resolve through `resolve_weight` and are findable by a pound-denominated request
- [ ] 1.11 Add the exact-budget-boundary and exact-delivery-threshold items (a product priced so a stated budget is met exactly, and a basket whose pre-tax subtotal is exactly the delivery threshold) and verify tests assert the budget comparison is inclusive and that delivery is zero at the threshold and charged one satang below it
- [ ] 1.12 Verify determinism: generate the same mutation twice into two directories and assert every file matches, so a verification failure cannot be attributed to fixture non-determinism

## 2. Manifest and verification

- [ ] 2.1 Implement manifest emission to JSON alongside the generated site and verify a test asserts the manifest round-trips and that its entry count equals the number of injections the generator reports performing
- [ ] 2.2 Implement the verification that compares a diff report against a manifest in both directions — every manifest entry appears in the expected list, and no list contains an item the manifest does not declare — and verify tests cover a missed change, a misattributed change, and a spurious change each producing a distinct, named failure
- [ ] 2.3 Implement the parse-failure versus withdrawal distinction check and verify a test asserts that an item whose page failed to parse is reported as a parse failure and is **not** also reported as withdrawn
- [ ] 2.4 Add the crawl-count check that distinguishes "page not reported" from "page never crawled" and verify a test asserts a page absent from the crawl produces a different failure than a page crawled but misreported

## 3. Ingestion and diff against the mutated site

- [ ] 3.1 Add the command that generates the mutated site, serves it, ingests it against the committed snapshot as baseline, and runs the verification, and verify running it end to end on the real site reports every injected change detected and exits zero
- [ ] 3.2 Verify the command exits non-zero and names the discrepancy when an injected change is suppressed — demonstrated by running it with one manifest entry deliberately removed and observing the failure
- [ ] 3.3 Verify the generated site is written to a git-ignored location and that `git status` is clean after a run, so a reviewer cannot accidentally commit derived HTML

## 4. Second-catalog evaluation

- [ ] 4.1 Extend the case format so inapplicability names the catalog it applies to, and verify a test asserts the existing 28 cases still load and that the four currently-inapplicable cases parse under the new field
- [ ] 4.2 Make the harness score a case normally when run against a catalog satisfying its requirement, and verify a test asserts a case that is inapplicable against v1 runs and passes against the mutated catalog
- [ ] 4.3 Record which catalog a run was produced against in the results, and verify a test asserts two runs against different catalogs are distinguishable in the output
- [ ] 4.4 Re-record `eval/results.md` for the v1 catalog unchanged (proving the extension did not disturb the committed run) and add a separate section recording the mutated-catalog run, and verify the four formerly-inapplicable cases are shown running rather than marked not applicable

## 5. Documentation

- [ ] 5.1 Write `docs/refresh-verification.md` covering what is injected, why each injection exists, what the verification proves and does not prove, and how to run it, and verify every command in it runs as written from a clean checkout
- [ ] 5.2 Update `README.md` to add the new command to the run instructions and to replace the "not built" entry for the mutated site with what is now demonstrated, and verify the five-command path still holds and the new command appears with its expected runtime
- [ ] 5.3 Update `BUG.md` and `TEST.md` to record the parse-failure and shrinkage paths as now exercised against live markup rather than only synthetically, and verify no claim of "unit-tested only" remains for those behaviours
- [ ] 5.4 Update `ANALYZE_01.md` §7 where it records the four cases as permanently inapplicable, and verify the section names the catalog in which each now runs
