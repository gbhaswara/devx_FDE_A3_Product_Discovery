# Design

## Context

See `proposal.md` — Why. The constraints that shape the approach:

- The committed site is `devx_FDE_A3_Product_Discovery/paperlane/`: 36 product pages across 4 markup shapes, 7 category pages, 59 tier documents, one home page, `delivery.html`, `robots.txt`, `assets/tiers.js`. It is a **fixture**, read-only, and the crawler's entry point is hard-coded to `index.html` relative to a base URL.
- `_detect_shape()` classifies by markup structure and returns `SHAPE_UNKNOWN` when nothing matches. `SHAPE_UNKNOWN` already produces a `ReviewRow` rather than an exception — the review floor exists and is reachable, it has just never been reached by a real page.
- `_discover_category_urls()` finds categories by scanning the home page for `category/` links and excludes anything containing `page-`. `_product_links()` finds products by scanning `div.card` for an `h3 a` whose href contains `product/`, and follows `div.pager a` links containing `page-`. **The generator must satisfy these selectors or the mutated site will yield zero products and the demonstration will prove nothing.**
- `run_ingest(base_url, rate)` takes the base URL as an argument, so pointing it at a mutated copy requires no code change.
- `diff_snapshots(old, new)` takes two paths and returns six lists plus `comparable`/`no_change`. It compares `products` (sku, list price, sale price, stock status) and `price_tiers` (sku, min_qty, unit price). It is **not** aware of any manifest.
- The evaluation harness loads cases from JSON and marks a case inapplicable via fields on the case itself. There is no notion of "inapplicable against which catalog".

## Goals / Non-Goals

**Goals:**

- A generated site whose every injected change is declared, applied deterministically, and independently verifiable.
- A verification that fails when the diff misses a change, misattributes one, or invents one.
- Making the four currently-unexercised behaviours reachable against live markup.
- One command a reviewer can run.

**Non-Goals:**

- Changing the diff algorithm, the extraction ladder, or the crawler. If verification exposes a defect, fixing it is in scope, but the fixture is not a pretext for a rewrite.
- Committing the generated site. It is derived output; the generator and the manifest schema are the source.
- Modelling a *different merchant's* site. This mutates the known site, so the comparison stays meaningful.
- Exhaustively fuzzing markup shapes. One deliberate unknown shape is the requirement; a fuzz corpus is not.

## Decisions

### D1 — Mutate a copy of the committed site, rather than author a new site

**Chosen:** copy `paperlane/` into a temp directory, apply targeted text/structure edits, serve the copy.

**Why:** the diff's correctness is only meaningful relative to a baseline that is otherwise identical. A hand-authored site would differ from the baseline in unknown ways, so a reported change could be an artefact of authorship rather than of the injection. Copying also guarantees the four known markup shapes are present and correct, so the only *unparseable* page is the one deliberately made unparseable — which is exactly the distinction the review floor must demonstrate.

**Alternative rejected:** authoring a small synthetic site (faster, fewer files) — it would not exercise the real selectors, and the diff would be comparing two unrelated catalogs.

### D2 — Declare the mutation in a manifest before applying it, and verify against the manifest

**Chosen:** the generator emits a manifest listing each intended change as `{kind, sku, before, after}`; the verification compares the diff report to the manifest in both directions.

**Why:** this is the difference between a demonstration and a screensaver. Without a declared expectation, "the report showed some changes" is unfalsifiable. Bidirectional comparison also catches the failure mode that matters most: a diff that reports changes nobody injected, which would indicate it is comparing the wrong rows or double-counting.

**Alternative rejected:** asserting against the mutated site's HTML. That re-derives the expectation from the same source that produced it, so a generator bug would be invisible.

### D3 — One injection per change kind, and each targeted at a distinct SKU

**Chosen:** each change kind gets its own SKU, so no SKU is subject to two changes at once.

**Why:** the requirement that a change is not reported under the wrong kind is only testable if kinds are separable. If one SKU had both a price change and a tier change, a diff that reported both correctly and one that reported only the price would both "pass" a naive check.

**Cost:** slightly more injected items than strictly necessary. Worth it for attribution being testable.

### D4 — The unknown-shape page is a *new* page, and the item it would have added is declared absent

**Chosen:** add a product page with markup matching none of the four shapes, linked from a category, and declare in the manifest that it must appear as a parse failure.

**Why:** the review floor's job is to make a *silently shrinking* catalog impossible. Injecting an unparseable page as a brand-new item proves the page is surfaced. It does **not** prove shrinkage is distinguishable from withdrawal — for that, the manifest must also assert that the SKU does **not** appear in `withdrawn`. Both assertions are needed, and they are separate scenarios in the spec.

### D5 — Discontinued, injected-instruction, and 28/32 lb data are injected as real pages

**Chosen:** the mutated catalog contains a discontinued item, a page whose body carries an instruction addressed to an automated reader, and products at 105 gsm (28 lb) and 120 gsm (32 lb).

**Why:** these four are precisely the cases the evaluation set records as inapplicable. Injecting them converts a documented limitation into a demonstrated behaviour, which is the only way to retire those `not_applicable` entries honestly.

**Note on the injection page:** the embedded instruction must be *plausible product-page text*, not a caricature. It is placed where a real merchant might put it (a description or note field) so that "treated as data" is a real claim. The extractor must not need a special case for it — if it does, the defence is not a defence.

### D6 — Applicability becomes per-catalog on the case, not global

**Chosen:** a case's inapplicability names the catalog it applies to; running against a catalog that satisfies it scores the case normally.

**Why:** the current model conflates "this behaviour is broken" with "this data does not exist here". Naming the catalog keeps the recorded run honest (it still reports those cases as inapplicable against v1) while allowing a second run to exercise them.

**Consequence:** results must identify the catalog they were produced against, or the two runs become indistinguishable in `results.md`. That is why the spec has a scenario for it.

### D7 — Verification runs offline and in a temp directory

**Chosen:** the demonstration serves the mutated copy on a local port and uses the existing rate-limited crawler; generated files go to a git-ignored directory.

**Why:** it must run in the same offline environment as the test suite (no external network), and it must not leave 40 modified HTML files in the working tree where they would either be committed by accident or confuse the next `ingest`.

## Risks / Trade-offs

- **The generator drifts from the real site's markup, so the mutated site stops being a faithful stand-in** → the generator copies rather than re-authors; only the injected fragments are new text, and those reuse the existing shapes' structure except for the one deliberately-unknown page.
- **A change is injected but the crawler never reaches the page** (e.g. an added product not linked from any category), so the diff reports nothing and the verification "correctly" fails for the wrong reason → every added item must be linked from a category page, and the manifest records the linking requirement; the verification distinguishes "not reported" from "not crawled" by checking the crawl count.
- **The diff reports a change for an unrelated item** because copying perturbed something → the verification is bidirectional, so this fails loudly rather than passing quietly.
- **Rate limiting makes the demonstration slow** (a full crawl is 103 requests at 1 req/s ≈ 2 min, and this needs two crawls) → acceptable for a demo; the command reports progress, and the test-suite version uses a small subset rather than the full site.
- **The injected instruction is too obviously a test** → the demonstration would prove less than claimed; the design puts it in a plausible field, and the README states exactly what was and was not proven.
- **Two catalogs make `results.md` ambiguous** → the results record the catalog identity; the committed results file stays the v1 run, with the mutated run recorded separately.

## Migration Plan

No migration: this adds tooling and a fixture, and changes no serving behaviour. Rollback is deleting the generator and the new command; nothing in the runtime path depends on it.

**Sequencing constraint discovered during planning:** `openspec/specs/` is currently empty because `add-paperlane-product-discovery` has not been archived. `openspec validate` accepts this change, but warns that **archive would refuse the MODIFIED deltas** for `catalog-refresh` and `evaluation-harness`, since those target specs do not yet exist under `openspec/specs/`. The ordering is therefore: archive `add-paperlane-product-discovery` first (it is Tier 1 complete), then archive this change. The same applies to the other two changes in this phase. This is a process ordering issue, not a defect in the deltas.

## Open Questions

- Whether the demonstration should run as part of `./run.sh test` or as its own command. Resolved as: its own command (`run.sh verify-refresh`), because it crawls a site and takes minutes; the test suite must stay fast and offline. A reduced version with a handful of pages can join the suite later if it proves stable.
