# BUG.md — known issues, traps, and failure modes

This file began as the **register of failure modes we already knew about** — traps found in the data, risks accepted in the design, and defects found and corrected in our own analysis. It now also carries **observed defects** (Part 2b), reproduced against the running service and registered *before* being fixed.

Its purpose is the demo and interview: the brief scores *"honesty about where it does not work"*, and the live-engineering round is a debugging exercise. This is where the known-unknowns are written down before they are found the hard way.

Status values: **OPEN** — not yet addressed · **MITIGATED** — design prevents it · **VERIFIED** — checked against the real site · **FIXED** — found and corrected during analysis.

---

## Part 1 — Traps in the source data

These are properties of the PaperLane site that will silently produce a wrong answer rather than an error. Verified against `paperlane/` during analysis; see `ANALYZE_01.md` §2 and §12.

### T1 — Budget compared at list price instead of at the requested quantity · MITIGATED

The single most consequential line in the project.

```
PL-PR-LTR-GL-130-40   list 265.00
  qty  1  -> 265.00   FAILS "under 250"
  qty  5  -> 249.10   PASSES
  qty 20  -> 233.20   PASSES
```

The brief's own example request puts the budget before the quantity: *"under 250 a pack, 20 packs."* A comparison against the list price gets the example wrong.

**Guard:** unit test at a quantity below the lowest tier; evaluation case at qty 1 and qty 20 on the same product and budget.

### T2 — Sale suppresses volume pricing, and the sale price is easy to miss · MITIGATED

```
<td><del>฿299.00</del> ฿259.00<span class='sale'>Sale</span></td>
<td><span data-sku='PL-PR-LTR-GL-170-40' data-sale='1'>Not available on sale items</span></td>
```

One item, one page. A parser reading the first currency amount picks up the struck-through 299.00 and quotes the wrong (higher) price. A parser that applies tiers to it would invent a discount that does not exist.

**Guard:** both amounts captured; sale precedence tested; evaluation case at qty 20 for the sale item.

### T3 — Out-of-stock items are quotable if you only read price · MITIGATED

Two items, both with perfectly valid prices: `PL-PR-A4-GL-170-44`, `PL-CL-A4-100-IVY`. Nothing about the price reveals unavailability.

**Guard:** stock state is a filter, not a display field; PR8 refusal tested for both.

**Now also exercised as a transition.** The v1 catalog is a *state*, never a change: an item is out of stock and always was. `./run.sh verify-refresh` marks `PL-CP-A5-80` out of stock with a restock date, so the diff reports an availability change against a real prior snapshot rather than only the state being readable. Evaluation cases 6 and 7 are pinned to v1 precisely because that transition changes their correct answer.

### T4 — `discontinued` is in the brief but absent from the site · CLOSED

PR8 names discontinued items; v1 has **zero**. The code path had no live data.

**Guard, now in place:** `./run.sh verify-refresh` marks `PL-CS-A4-200-WH` discontinued in the mutated site, and the resulting snapshot is a second catalog the evaluation set runs against. Evaluation case 21 matches that item and refuses it with its reason, against real markup rather than a synthetic fixture. The parse path (`extract`) and the refusal path (`assistant`) are both exercised end to end.

### T5 — Pack size makes "under 250 a pack" ambiguous · MITIGATED

Packs are 50, 100, 250 or 500 sheets. A price is per pack, so a budget per pack compares differently across pack sizes.

**Guard:** `pack_sheets` stored as a fact; the ambiguity is surfaced to the user rather than resolved silently.

### T6 — The flyer SKU suffix encodes the printing spec · MITIGATED

`-40` / `-44` / `-10` / `-11` encode single/double-sided × colour mode. Two SKUs on one page differ only by suffix, and one of them is B&W while the other is full colour.

**Guard:** never infer attributes from the SKU; parse the table columns.

### T7 — The brief specifies four pound conversions; the site contains two · CLOSED

```
20 lb = 75 gsm   PRESENT     24 lb = 90 gsm   PRESENT
28 lb = 105 gsm  ABSENT      32 lb = 120 gsm  ABSENT
```

No `28 lb`, no `32 lb`, no `105 gsm`, no `120 gsm` anywhere in v1. Two rows of the conversion table had no live data.

**Guard, now in place:** `./run.sh verify-refresh` adds `PL-CP-LTR-28` (105 gsm) and `PL-CP-LTR-32` (120 gsm) to the mutated site. Evaluation cases 23 and 24 run against that catalog and pass: each pound request converts, matches, and quotes. All four conversion rows are now demonstrated against real markup, not just unit-tested.

### T8 — Weight is written four ways, and 10 of 36 pages state it only in prose · MITIGATED

```
structured field, "N gsm"       16 pages
structured field, "lb + gsm"     2 pages   (20 lb bond (75 gsm), 24 lb (90 gsm))
structured field, "lb only"      2 pages   (20 lb bond, 24 lb)
flyer table, per-row gsm         6 pages
prose only, "weighs N gsm."      9 pages
prose only, "weighs 90 g/m²."    1 page    (superscript 2)
```

A parser reading labelled fields returns **NULL for 10 of 36 pages**. No page lacks a weight, so this failure looks like "unknown weight" rather than "parse miss".

**Guard:** four input forms handled; extraction test asserts all 36 pages yield a weight; the two pages stating both forms are golden conversion assertions.

### T9 — "Colour" means two different things · MITIGATED

```
colour_name (paper shade)  White, Cream, Pastel pink, Pastel yellow, Bright red,
                           Black, Assorted brights, Assorted pastels
colour_mode (print)        Full colour (CMYK) x36, Black and white x6
```

*"colour paper"* and *"colour flyers"* are different filters. The field name also changes by markup shape: `<table>` calls it `Colour`, `<dl>` calls it `Shade`, and the flyer table calls it `Colour` but means print colour.

Routing the word wrongly returns a full, plausible, wrong result set — right price, wrong products, invisible to any total-based assertion.

**Guard:** two separate fields; routing by noun; missing context becomes a `clarify`; evaluation cases for both meanings.

### T10 — The same size is written two ways, and one is unicode · MITIGATED

```html
<h1>Letter-size Flyers (8.5 × 11 in) – Gloss</h1>     <- page heading
<p>...on US Letter, 8½ × 11 inches paper with a...    <- body prose, SAME page
```

Two spellings appear across the catalog: `8.5 × 11` (9 occurrences, 7 pages) and `8½ × 11` (2 occurrences). Both flyer Letter pages contain **both**, so a single page can disagree with itself.

Two traps in one:

- The multiplication sign is **U+00D7 (×)**, not ASCII `x`. A filter written as `size LIKE '%8.5 x 11%'` matches nothing.
- `8½` is **U+00BD (VULGAR FRACTION ONE HALF)**, not `8.5`. A filter on the decimal form silently misses the prose form on the very pages the brief's example is about.

**Guard:** normalise to a size code at ingest; never filter on display text; a page that fails to normalise is reported rather than stored as an unmatchable NULL.

### T11 — Absent attributes silently exclude whole categories · MITIGATED

`sides` and `colour_mode` are populated only on the 6 flyer pages. All 30 paper products have no printing concept.

```
WHERE sides = 'single'                    -> returns 0 paper products
WHERE (sides IS NULL OR sides = 'single') -> paper products pass through
```

This is the highest-risk *silent* bug in the system: nothing errors, the results look reasonable, and the product set is wrong.

**Guard:** not-applicable semantics at the query layer; evaluation case asserting a printing constraint does not exclude plain paper.

### T12 — The pack basis is stated in three different places, and the unit word is unreliable · MITIGATED

Two sibling products in the same family, both 500 sheets:

```
pl-cl-a4-80-pbl   pricebox: "Ream of 500 sheets"        <- basis in the unit line
pl-cl-a4-80-pyl   pricebox: "Price: 195.00 THB / ream"  <- basis is a bare word
                  spec:     Pack contents: 500 sheets   <- quantity in a spec field
```

The price box states the quantity basis in at least three shapes across the site — `Ream of 500 sheets`, `per pack of N sheets`, and `N THB / ream` with the count only in a spec field. A parser that reads the unit word from the price box gets a number for some products and a bare word for others.

**Guard:** `pack_sheets` is the fact and is read from wherever it actually appears; `unit_word` is display text and no filter or comparison uses it.

### T13 — Tiers are per leaf SKU, not per product page · MITIGATED

```
PL-PR-A4-GL-100-40   5+ 202.10   20+ 189.20
PL-PR-A4-GL-100-44   5+ 281.06   20+ 263.12
```

10 packs of each does **not** reach a 20+ tier. "The same flyer product" is the intuitive-but-wrong reading of PR2's "per item".

**Guard:** tiers keyed by SKU; evaluation case with two similar items at quantities that would pool.

### T14 — The list price is not the number a careless parse finds · VERIFIED

`PL-CP-A4-80` lists at **129.00**, with tiers 10+ 122.55 and 50+ 116.10. A parser that takes the *first* currency amount on the page, or that scrapes the tier document instead of the page, records 122.55 as the list price.

This is the trap that produced the worst defect in our own analysis (A9 below): the list price was recorded as 122.55, which is the 10+ tier. Every total derived from it was wrong, and every one *looked* right.

Two related facts worth stating, because both were checked across all 72 SKUs:

- **Every tier in v1 strictly lowers the price** — no tier equals or exceeds its list price. So a test may assert a lower price *in this data*, but must still not assume it in general.
- **All tier sequences are monotonically decreasing** — no later tier is more expensive than an earlier one.

**Guard:** read the list price from the page's price box, never from the tier document; read tiers from the tier document, never from the page. A fixture asserts `PL-CP-A4-80` yields list 129.00 *and* tiers 10+/50+, which catches the substitution.

### T15 — The budget boundary is unreachable, but the delivery boundary is not · CLOSED

- **Budget boundary — unreachable in v1.** No v1 unit price is exactly 250.00 or 300.00 at any real quantity, so `<` versus `<=` on a maximum price cannot be distinguished from the v1 data. (It is reachable in the mutated catalog; see the guard below.)
- **Delivery boundary — reachable.** `PL-CP-A4-80-ECO` lists at 125.00 with a 10+ tier of 120.00, so **25 packs × 120.00 = 3,000.00 exactly**. PR4 says free delivery at "3,000 or more", so this order must pay **no** delivery. A `>` instead of `>=` charges 150.00 here.

**Guard:** an evaluation case on 25 packs of `PL-CP-A4-80-ECO` asserting delivery is zero, and the mutated site now makes **both** boundaries reachable:

- `PL-CP-A4-80-EXACT` lists at exactly **250.00**, so a budget of "250 a pack" is met exactly and an exclusive `<` excludes it wrongly. Asserted in `TestBoundaryItems::test_budget_bound_is_inclusive`.
- `PL-CP-A4-80-THRIFT` lists at **1500.00**, so two units subtotal exactly 3000.00 and pay no delivery, while one satang below is charged. Asserted in `TestBoundaryItems::test_delivery_is_zero_exactly_at_the_threshold` and `..._one_satang_below_the_threshold`.

Status: **CLOSED**. Both boundaries are now exercised against real extracted prices rather than synthetic `Money` values.

---

## Part 2 — Defects found in our own analysis · FIXED

Recorded because the interview asks about failures, and because the pattern matters: every one of these was a plausible number that would have become a wrong expectation.

| # | Defect | How found | Fix |
|---|---|---|---|
| A1 | Evaluation case intended to test "no match" used a budget of 200, which **15 products satisfy** | recomputing the candidate set | budget lowered below the cheapest catalog item (72.00) |
| A2 | A worked example labelled **`PL-PR-A4-MT-100-44`** (full colour, double-sided) as "B&W single-sided" | checking the SKU's actual table row | SKU named explicitly with its true attributes; the suffix→attribute mapping was then verified across all 42 variants (T6) |
| A3 | An "A5 copy paper" case carried a total belonging to a **flyer** — the 119.00 traced to `PL-PR-A4-MT-100-10`, not to `PL-CP-A5-80` (72.00) | tracing the figure to its source SKU | corrected to the copy-paper SKU and its real total (237.54) |
| A4 | A multi-item case asserted "one delivery line" but **computed no total** | reviewing the case table | exact expected total added, so the per-line bug is detectable |
| A5 | Claimed "one page has no weight"; actually **10 pages** state weight only in prose | counting all 36 pages | trap rewritten with the real distribution |
| A6 | A VAT-before-delivery error was stated as 4.50; it is **10.50** | recomputing the delta | corrected |
| A7 | A per-line delivery bug was stated to produce 259.02 VAT, then "corrected" to 260.02; the real figure is **231.72** | recomputing the basket after A9 fixed the list price | corrected; the `321.00` total delta it was derived from was right, the VAT breakdown was not |
| A8 | A recompute script crashed with `TypeError: NoneType * int` on qty 1 | running it | exposed the real no-tier-met bug → became named test #2 in `TEST.md` |
| A9 | `PL-CP-A4-80`'s **list price was recorded as 122.55** — which is actually its *10+ tier* price; the list is **129.00** | recomputing every quoted total from the page's price box rather than from the tier document | all affected totals recomputed; trap T14 rewritten to describe the substitution |

**A9 is the most dangerous defect in this file**, because it is the one that would have silently corrupted the evaluation set.

The wrong list price propagated into a published worked example (1 ream `122.55` → total `291.63`) and into a multi-item basket (20 reams at `122.55` → `3653.52`). Both totals were internally consistent — the arithmetic was right, the input was wrong — so no amount of checking the sum would have found it. It surfaced only by re-deriving the list price from the product page and noticing the page said `129.00` while the tier document said `122.55`.

The correct figures:

```
PL-CP-A4-80    list 129.00, tiers 10+ 122.55 / 50+ 116.10
   1 ream    sub  129.00  deliv 150.00  VAT  19.53  TOTAL   298.53
  10 reams   sub 1225.50  deliv 150.00  VAT  96.29  TOTAL  1471.79
  50 reams   sub 5805.00  deliv   0.00  VAT 406.35  TOTAL  6211.35
```

This is exactly the failure mode `TEST.md` opens with: **a wrong expectation is worse than no test**, because it causes correct code to be "fixed" until it matches the error. Had this reached `eval/`, a correct pricing engine would have been reported as failing.

**A8 is the instructive one.** The script failed because it initialised the best price to nothing and then looked for a tier, but most SKUs' lowest tier is 5+ or 10+, so at qty 1 no tier matches. That is a real defect in the pricing function, not a scripting slip — and it was found by accident. It is now an explicit test.

### A10 — The semantic tiebreak regressed six recorded cases, and its timeout was too short to work

Found during `add-semantic-tiebreak`, by measuring rather than by reading. Two separate defects in one feature, both of the "looks fine, is not" kind.

**The ranking position was wrong.** The design placed similarity *before* price, reasoning that price rarely ties so the term would otherwise be decorative. Measured against the recorded set: **13 of 28 cases reordered, 9 first results changed, 0 improvements, 6 regressions.** Case 26 (`A4 copy paper`) dropped `PL-CP-A4-70` — the cheapest qualifying item — from first to fourth. That directly contradicts the system's own stated rule and the spec scenario *"similarity does not override a stated preference for cheaper"*, so it was a spec violation, not a judgement call.

Moved after price and re-measured: 3 of 28 reorder, 0 first results change, 0 improvements, 0 regressions. The three reorderings are price ties among equally-valid items.

| Position | Reordered | First changed | Improvements | Regressions |
|---|---|---|---|---|
| Before price | 13 / 28 | 9 | 0 | 6 |
| After price | 3 / 28 | 0 | 0 | 0 |

**The timeout was measured warm-only.** The design specified 2s, on the reasoning that an embedding call is a local matrix multiply. A cold model load costs **2.0s** for one text and **2.8s** for all 72; warm calls cost 0.02s and 0.64s. So the 2s timeout failed the *first request after every restart* — the feature degraded on first use and looked broken, which is precisely the failure mode the degradation reporting exists to surface, triggered by the default path rather than an outage. Now 10s.

Both are recorded in `design.md`, `docs/semantic-ranking.md` and `CHANGELOG.md`. The general lesson is the same as A9's: a number that came from one measurement regime was applied to another, and only re-measuring found it.

### A11 — `ANALYZE_01.md` §9a specified logging raw request text, which the observability spec forbids

Found during `add-observability`, by reading the two sources side by side rather than by running anything. **This one was resolved in favour of the spec, so the analysis is what is wrong.**

`ANALYZE_01.md` §9a specified the request record as carrying `raw_message` — the customer's text, verbatim, on every request. The `observability` spec has a requirement headed *"Recorded conversation content is limited"* whose scenarios say the full text is not persisted by default, that routine operation must not accumulate customer conversations, and that capture requires an explicit opt-in with a bounded record.

These cannot both hold. **The spec wins**, and not because specs beat notes in the abstract: `AGENTS.md` ranks the OpenSpec change above `ANALYZE_01.md` as a source of truth, and the analysis was written as a plan for a change that was then specified more carefully. The spec is the later and more considered artefact.

What shipped instead: `request_chars` (a length) and `request_digest` (16 hex characters of a SHA-256). The digest preserves the one thing the text was genuinely needed for — grouping repeated identical requests — and nothing else. Text capture exists as `PAPERLANE_RECORD_TEXT`, off by default and truncated at `PAPERLANE_RECORD_TEXT_MAX` (default 200) when on.

**The digest is explicitly not anonymisation.** A 16-character hash of a short string is brute-forceable by anyone holding a candidate list, and it is documented as a grouping aid in the record schema, `docs/observability.md` and the README. Calling it anonymisation would be the kind of claim that gets relied on in a privacy review and then fails it.

**The spec won on a second point too.** The main `observability` spec as first archived said a record captures *"what was asked"*, while its own retention requirement said conversation text is not retained — an internal contradiction that the `add-observability` delta resolved to "how it was interpreted". So the conflict was not only between the analysis and the spec, but inside the spec itself, and following either literally would have been wrong.

**Verification.** `tests/test_records.py::TestRequestText` asserts the text is absent by default and that the digest and length are present; `tests/test_observability_api.py::TestNoRequestTextByDefault` asserts a distinctive request phrase appears nowhere in the written log at all, not merely absent from a field.

---

## Part 2b — Defects found in the shipped code · OPEN

Found after `add-conversation-memory` shipped, by probing the running service rather than by reading the module. All three are in conversation memory. Registered before being fixed, per the rule at the end of this file.

### A12 — A first turn that states only a quantity or a budget cannot be continued

```
turn 1  "20 packs"            -> clarified   criteria {quantity: 20}
turn 2  "make it 50"          -> clarified   criteria {}
```

Both the 20 and the 50 are lost. The reply asks a fresh question as if nothing had been said.

**Root cause.** The same predicate is applied twice, and it is the wrong one. `Criteria(quantity=20).has_any_constraint()` is `False` — a quantity and a budget do not *filter* the catalog — so:

- `conversation.is_continuation` returns `False` at `if previous is None or not previous.has_any_constraint()` (conversation.py:172); and
- every caller passes `None` instead of the stored criteria by the same test: api.py:753, api.py:1037 (page route), ask_cli.py:191, conversation_eval.py:243.

`_states_something` exists precisely to be the broader predicate ("A budget or a quantity is a statement even though neither filters the catalog") and is used only for the *current* turn. The module documents the distinction and then fails to apply it.

**Why it is invisible in the recorded set.** No conversation case starts with a quantity-only or budget-only turn. A *later* budget-only turn does work — case 7 is `"A4 300gsm card, 5 packs" >> "under 200 a pack"` — because by then the retained criteria already had a category. Only a first turn is affected, and no case is one.

**Guard:** an evaluation conversation starting `"20 packs"` and one starting `"under 200 a pack"`, each continued by a turn that must carry the first; and a unit test `is_continuation(Criteria(quantity=20), Criteria(quantity=50))` is `True`.

**Status: OPEN.**

### A13 — One unparseable turn permanently forgets the conversation

```
turn 1  "A4 copy paper"   -> quoted      criteria {category: Copy paper, size: A4}
turn 2  "hello there"     -> clarified   criteria {}
turn 3  "make it 50"      -> clarified   criteria {}   carried []
```

The A4 is gone for good. The same happens with a real paraphrase: `"too expensive"`.

**Root cause.** D3 says a turn that understood nothing is a **fresh request** — it must not silently re-answer the previous question. That is about the *reply*. `merge_turn` returns `MergeResult(criteria=current)` for a fresh turn, and the caller then stores `record_turn(existing, merge)`, which sets `conversation.criteria` to the empty criteria (conversation.py:569). The intent "answer fresh" was implemented as "erase history", which D3 never says.

It compounds with A12: after the wipe the conversation has no filterable constraint, so the next turn cannot continue even once, and the bare-number rule does not fire either (a *fresh* request requires a unit word, which is correct on its own terms).

**Guard:** a conversation case with a mid-conversation no-understanding turn asserting that the following turn still continues from the earlier subject.

**Status: OPEN.**

### A14 — `turn_index` saturates at 21 and stops distinguishing turns

A 25-turn conversation writes `turn_index` values `… 19, 20, 21, 21, 21`. Every turn past the cap reports turn 21, in the record and in the API's `conversation.turn`.

**Root cause.** `Conversation.turn_index` is `len(self.turns) + 1`, and `put` trims `turns` to the last `MAX_TURNS` (20): once 20 turns are retained, the index is pinned at 21 forever. `records.py` states that turns are "distinguished by `turn_index`"; past the cap they are not.

Low severity — no answer is affected, and the cap is deliberate — but it is a wrong number in an observability field, which is the class of defect this file exists to catch.

**Guard:** a test asserting that 25 turns produce strictly increasing `turn_index`.

**Status: OPEN.**

---

## Part 3 — Accepted risks in the design

Carried deliberately. Each is stated in the README as a known limitation.

| Risk | Impact | Why accepted |
|---|---|---|
| Three-day build against a six-hour brief | may read as scope indiscipline | Two explicit tiers, every extra separable, and the split stated in the README and customer summary. Framing reduces it; it does not remove it. |
| Single-turn by default; memory is opt-in per conversation id | a caller that never sends a `conversation_id` gets no memory, and the in-memory store loses everything on restart | Memory shipped, but it is off unless a caller names a conversation: an implicit session would be a session nobody asked for, and the id is an unauthenticated label. Bounds and the wipe-on-unparseable-turn risk are stated in `docs/conversation-memory.md`; the unparseable-turn case is defect A13, not an accepted risk. |
| Rule interpretation is narrower than the model | some paraphrases fall back to a clarification | The model path runs first; rules are the fallback; the fallback rate is measured so degradation is visible. |
| Semantic search is a tiebreak only | a purely descriptive request with no structured terms can miss | The structured path covers the request shapes the brief describes. |
| Two pound conversions unverified against real data | T7 path may be wrong on first contact | All four implemented from the agreed table; unlisted values raise; the mutated site exercises them. |
| Model behaviour may change without notice | interpretation quality drifts silently | Rule fallback, disclosed interpretation source, and a fallback-rate metric turn drift into a visible metric. |
| No auth, no rate limiting beyond the crawler | not production-hardened | Local demonstration service; the brief scores the assistant, not deployment hardening. |
| One site, one layout family | cannot onboard another supplier without work | The ladder covers four shapes plus a structured fallback; a parser profile per site is the stated next step. |

---

## Part 4 — Failure modes to watch in operation

These are the conditions that indicate the system is degrading rather than failing. Each has a metric in `openspec/.../specs/observability/spec.md`.

| Symptom | Likely cause | First check |
|---|---|---|
| Rising rule-based fallback share | model degraded, or credentials expired | model reachability in `/health` |
| Rising zero-result share | parsing defect, or a genuine catalog gap | run a known-good request through `/quote` |
| Review set grew after a refresh | the site changed markup shape | inspect the recorded excerpt for the failing page |
| Catalog shrank between snapshots | a parser silently stopped matching | `/diff` — withdrawn items without a review entry. This path is now exercised: `./run.sh verify-refresh` withdraws `PL-CP-A4-75` and the diff reports exactly one withdrawal |
| p95 latency climbing | model latency, not pricing (pricing is local) | per-stage timings in the request record |
| Stated total ≠ computed total | reply prose is paraphrasing a figure instead of inserting it | this should be structurally impossible; any occurrence is a code defect |
| A quote includes an item that does not exist | the no-invented-products assertion failed to fire | this should be structurally impossible; treat as a P0 |

The last two are listed as *impossible by construction*. If either ever occurs, the guarantee is broken and the design assumption needs revisiting — which is exactly why they are monitored rather than assumed.

---

## Reporting a new issue

Add it to Part 1 (data trap), Part 3 (accepted risk) or a new entry with an ID, the observable symptom, the trigger, the guard, and the status. A bug found during the demo round becomes a test before it becomes a fix.
