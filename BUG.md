# BUG.md — known issues, traps, and failure modes

This file began as the **register of failure modes we already knew about** — traps found in the data, risks accepted in the design, and defects found and corrected in our own analysis. It now also carries **observed defects** (Part 2b), reproduced against the running service and registered *before* being fixed.

Its purpose is the demo and interview: the brief scores *"honesty about where it does not work"*, and the live-engineering round is a debugging exercise. This is where the known-unknowns are written down before they are found the hard way.

Status values: **OPEN** — not yet addressed · **MITIGATED** — design prevents it · **VERIFIED** — checked against the real site · **CLOSED** — the gap or the unexercised path has been closed · **FIXED** — found and corrected, with a guard in the suite.

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

## Part 2b — Defects found in the shipped code

Found after `add-conversation-memory` shipped, by probing the running service rather than by reading the module. A12–A14 are in conversation memory. A15 is separate: it was found later, while answering "how is the UI deployed?", and it is in the page rather than in the assistant. A16 was found by building the catalog column and noticing a product's unit read "No volume pricing for this item." Registered before being fixed, per the rule at the end of this file — except A15, which says so in its own entry. **A12–A19 are FIXED** — A13 required answering a question D3 left open, which is recorded in its entry. A17 and A18 were reported from use after the submission was complete; both were reproduced against the running service before anything was changed. A19 was exposed by the re-ingest that fixed A16: the freshness tests failed against a snapshot that was minutes old, and the cause was the writer storing local time as if it were UTC.

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

**Status: FIXED.** The broader predicate is now the only one:
`is_continuation` gates on `_states_something(previous)`, and a new
`conversation.continuation_basis(conversation)` replaces the narrow test at all
four call sites, so the question "is there anything to continue" is asked in one
place. Cases 9 and 10 were added to `eval/conversation-cases.json` and **proven
falsifiable**: restoring the old predicate makes exactly those two fail and the
run exit 1. `tests/test_conversation.py::TestContinuationFromACommercialOnlyTurn`,
`tests/test_conversation_api.py::TestCommercialOnlyFirstTurn` and
`tests/test_ask_cli.py::TestConversation::test_a_commercial_only_first_turn_is_continued`
pin it at the unit, HTTP and CLI layers.

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

**Status: FIXED, by amending D3's implementation rather than D3.** D3 says such a turn is answered **fresh** — it must not re-answer the previous question — and that still holds. What it never said, and what the code did, is that the retained criteria are *discarded*. `MergeResult` now carries `empty`, and `record_turn` keeps the conversation's criteria on an empty turn while still appending the turn, so the history and the turn count include it. A turn that names a subject still replaces the criteria, so the rule that protects against a wrong carry is untouched.

Answered the question D3 left open: an empty turn is fresh *for the reply*, and transparent *for the state*. The alternative reading — discard, as originally implemented — makes one unparseable sentence end the customer's ability to refine, which is the failure mode memory exists to prevent.

**Guard in place:** `eval/conversation-cases.json` case 11 asserts both halves (turn 2 answered from an empty request, turn 3 still carrying the subject); `tests/test_conversation.py::TestAnEmptyTurnDoesNotForget` and `tests/test_conversation_api.py::TestAnEmptyTurnDoesNotForget` pin the store rule and the wiring. Proven falsifiable: restoring the old `record_turn` fails case 11 and exits 1.

### A14 — `turn_index` saturates at 21 and stops distinguishing turns

A 25-turn conversation writes `turn_index` values `… 19, 20, 21, 21, 21`. Every turn past the cap reports turn 21, in the record and in the API's `conversation.turn`.

**Root cause.** `Conversation.turn_index` is `len(self.turns) + 1`, and `put` trims `turns` to the last `MAX_TURNS` (20): once 20 turns are retained, the index is pinned at 21 forever. `records.py` states that turns are "distinguished by `turn_index`"; past the cap they are not.

Low severity — no answer is affected, and the cap is deliberate — but it is a wrong number in an observability field, which is the class of defect this file exists to catch.

**Guard:** a test asserting that 25 turns produce strictly increasing `turn_index`.

**Status: FIXED.** `Conversation` carries `turns_seen`, incremented by
`record_turn` and persisted by the JSONL store, and `turn_index` is
`max(turns_seen, len(turns)) + 1` — the retained list is a floor, not the source,
so a conversation read from a file written before the counter existed still
numbers correctly. `tests/test_conversation.py::TestTurnNumbering` pins the
counter past the cap, its strict monotonicity, and its survival across a restart;
`tests/test_conversation_api.py::TestRecords::test_the_recorded_turn_number_keeps_advancing`
pins the number that reaches the record. Verified against the running service:
25 turns now write `1…25` where they wrote `… 20, 21, 21, 21`.

### A15 — The page loaded its only script from a CDN, so an offline host got a silently dead form

```html
<script src="https://unpkg.com/htmx.org@1.9.12" integrity="sha384-ujb1…"></script>
<form hx-post="/ask" hx-target="#result" hx-swap="innerHTML">   <!-- no method, no action -->
```

On a host with no route to `unpkg.com` the script never loads. A `<form>` with
no `method` and no `action` defaults to `GET` of the current URL, so pressing
**Ask** reloads the page and clears the input. There is no error, no console
message a user would act on, and no server request to notice in a log.

**Why it survived the whole build.** The interesting part is not the CDN, it is
that nothing could see the failure. The suite, the evaluation and the CLI are
all deliberately offline — they run under `unshare -rn` — but no test loaded the
page's assets, so "offline" was verified for the assistant and never for the one
interactive surface. Every `curl`-based check kept passing, because the JSON API
does not need htmx. The failure was only reachable by asking a different
question: *how would someone deploy this?* The README answered that in one line
(`./run.sh serve`) and mentioned neither `--host`, binding, a proxy, nor the
script's origin.

**Fix.** htmx 1.9.12 is vendored at `src/paperlane/static/htmx.min.js` and served
same-origin by `GET /static/htmx.min.js`; the page references that path. The
vendored bytes are provably the ones the CDN was serving: their SHA-384
(`ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2`) is the same
value the page carried as its Subresource Integrity hash, and
`src/paperlane/static/VENDOR.md` records it with the licence. A missing asset
returns 500 with a remedy rather than an empty 200 that leaves the browser with a
script doing nothing.

**Guard:** `tests/test_ui_offline.py`, 9 tests — no external host in the markup,
the same-origin script tag, the form is still htmx-only (the premise of the whole
argument), the route returns the exact bytes with a JavaScript content type, the
cache header is not `immutable`, the route is absent from the OpenAPI paths, the
page's `src` resolves to the same hash, and `VENDOR.md` describes the shipped
file. **Falsification:** restoring the CDN tag fails three of them. Packaging was
checked too — `uv build` puts `static/htmx.min.js` in the wheel, and an
installed-wheel copy serves all 48,101 bytes.

**Status: FIXED.** Registered retroactively: found and fixed in one pass while
writing the deployment section, so unlike A12–A14 it was not written down before
the change. Recorded anyway, because an unregistered defect is indistinguishable
from one that never existed, and because the *reason it was invisible* is the
transferable part.

### A16 — `unit_word` holds a sentence about volume pricing instead of a unit

```json
{"sku": "PL-CS-A4-160-AST", "pack_sheets": 100,
 "unit_word": "No volume pricing for this item."}
```

Four SKUs carry that string — `PL-CS-A4-160-AST`, `PL-CS-A4-250-BLK`,
`PL-PH-A4-230-MT`, `PL-CL-LTR-24-BRT`. It reaches `/api/products` unchanged.

**Root cause.** `extract._unit_word` takes `box.css_first(".muted")` from the
price box, and only falls back to the text after a slash when there is no
`.muted` at all. These four product pages have no unit element in the price box:

```html
<div class="pricebox"><div>Price: <span class="big">159.00 THB</span> / pack</div>
<p><span class="stock-in">In stock</span></p>
<p class="muted">No volume pricing for this item.</p>...</div>
```

The only `.muted` is the volume note, so it wins — and the `/ pack` tail that
holds the real unit is never reached, because the `.muted` branch returns first.

**Why it was invisible.** `assistant._unit_phrase` prefers `pack_sheets` and only
falls back to `unit_word`, so every reply already says "pack of 100 sheets" and
never shows the bad string. The field is documented in `extract.py` as
*"deliberately unreliable … display text only"*, which is true and also the
reason nobody looked. The browse column added in this change nearly rendered it
as `A4 · 160 gsm · No volume pricing for this item.`; it uses the same
`pack_sheets` rule instead, now shared as `assistant.unit_phrase` so the page and
the reply cannot drift apart.

| Path | Shows the value? |
|---|---|
| `/api/ask`, `/api/quote` replies | no — `pack_sheets` wins |
| `/` catalog column | no — `unit_phrase`, same rule |
| `/api/products` | **yes**, verbatim |

**Status: FIXED.** `extract._unit_word` now reads the slash tail first when the
price line has no `.muted` of its own, and falls back to `.muted` otherwise. The
branch order was the bug: the four pages above have both a slash tail and a muted
note, and the note won. The fix is structural, not a check for the sentence — no
"if it starts with *No volume*" special case — so a muted unit still wins where
that is the only unit on the page (the `Ream of 500 sheets` layout), which is the
second shape the tests pin.

**Falsification.** The new test was written and run before the fix, on a real page
copied into `tests/fixtures/pl-cl-ltr-24-brt.html`:

```
FAILED tests/test_extract.py::TestPackSize::test_unit_word_ignores_the_volume_pricing_note
E   AssertionError: assert 'No volume pr...or this item.' == 'ream'
```

**Verification.** `TestPackSize` (9) passes, including the guard that a `.muted`
unit is still read when the price line has no slash. Extracting all 72 pages now
yields no `unit_word` beginning "No volume"; the four formerly broken SKUs read
`ream`, `pack`, `pack`, `pack`, and the catalog's exact-`ream` count rises from 6
to 7. The re-ingest was over HTTP at 1 req/s, not a database edit: a `/tmp` copy of
the old snapshot vs the new one differs on **4 rows, all in `unit_word`**, plus
provenance (`crawled_at`, `built_at`, run id). Counts are unchanged — 72 products,
105 tiers, 2 out of stock, 1 on sale, 0 review items.

**Guard:** `test_unit_word_ignores_the_volume_pricing_note` fails if the note is
ever stored as a unit again. `test_ui_catalog.py::test_no_unit_phrase_leaks_from_the_price_box`
still guards the display independently.

---

### A17 — A bare quantity that is also a catalog grammage changed the paper, then stuck

Reported as a five-turn conversation. Turns 1 and 2 quote; turns 3, 4 and 5 all
come back as no-match — including turn 5, which restates the quantity that had
already quoted on turn 2.

```
1  PaperLane Card A4 160gsm Assorted Pastels, 10 reams  -> quoted  160 gsm, 10
2  change it to 50                                     -> quoted  160 gsm, 50
3  change it to 100                                    -> no_match  100 gsm, 100
4  change it to 60                                     -> no_match  100 gsm, 60
5  change it to 50                                     -> no_match  100 gsm, 50
```

**Root cause.** Two rules that are each right composed into one that is wrong.

* `aliases._resolve_bare_grammage` reads a bare number as a weight when the
  number is one the catalog stocks, so that "A5 gloss 130" needs no unit. `100`
  is a stocked grammage.
* `conversation.merge_turn` reads a bare number in a refinement as the quantity —
  the rule the conversation spec states ("a bare number in a refinement is the
  quantity").

Nothing decided which rule owns the number when both apply. Turn 3 therefore set
*both*: quantity 100 from the merge, weight 100 gsm from interpretation. A
100 gsm card in assorted pastels does not exist, so the turn was a no-match — and
because the merged criteria now held the weight, it was carried into turns 4 and
5. Every later number changed the quantity only; the weight stayed wrong, which
is why returning to 50 could not recover.

`50` and `60` were never misread: neither is a catalog grammage. The defect fires
only on numbers that are both a plausible quantity and a stocked weight — 70, 75,
80, 90, 100, 130, 160, 170, 180, 200, 230, 250 — which is why the sequence only
broke at the turn that said 100.

**Why it was invisible.** Every existing test of this rule used `50`, and 50 is
not a grammage, so the ambiguity never arose. The merge test also asserted only
that the quantity was 50; it never asserted what happened to the weight. The
eval case used 50 as well. A rule tested only at a value where it cannot conflict
with another rule is not tested.

**Fix.** `aliases.bare_grammage(text)` answers the question `Criteria` cannot:
was this weight read from a bare number, or from a unit? `merge_turn` then drops
the weight when it is the same number the turn adopted as its quantity and the
text supports the bare reading. Interpretation stays per-turn and stateless
(D1); the context-sensitive decision is made where the context is, next to the
existing bare-quantity rule. An explicit "100 gsm" still corrects the weight —
the helper returns `None` the moment a unit word is present.

**Verification.**

| Level | Test |
|---|---|
| Parser | `test_aliases.py::TestBareGrammage` — 7 cases, including a unit-bearing weight, a pound weight, a bounded bare number, and a number the catalog does not stock |
| Merge | `test_conversation.py` — bare 100 is the quantity and 160 gsm is carried; explicit "100 gsm" still corrects |
| Endpoint | `test_conversation_api.py::TestABareNumberThatIsAlsoAGrammage` — the reported five turns, plus the recovered total (8,506.50) |
| Evaluation | `eval/conversation-cases.json` case 12 — the same sequence, scored on memory, retrieval, pricing and reply |

Reverting the merge change makes 4 of those tests fail; the guard for an explicit
weight keeps passing, which is the distinction the fix has to preserve. The suite
went from 1169 to 1182.

---

### A18 — The catalog column hid most of the catalog it was added to show

Reported from use, as a request: make the page 50-50 and make the left column a
drop-down, *so we can see all categories and item*.

The cause of the second half was a defect, not a missing feature. The column was
`max-height: calc(100vh - 2rem)` with `overflow-y: auto` inside a sticky panel.
At 1440×900 it showed the catalog heading, the hint, and the first category's
nine rows — and then an inner scrollbar. The other three categories, and the
counts that say how large they are, were below that scrollbar with nothing on
screen to suggest they existed. The catalog column could show one of its four
categories.

**Why it was invisible.** `test_ui_catalog.py` asserted that every product appears
exactly once in the served HTML, escaped, with the right price and the right
category count. All of that was true. Every row was in the response; most were
not on the screen. A DOM assertion cannot see a scrollbar, and the suite had no
browser, so the one property the column existed for — that the catalog is
legible — was never asserted and never looked at.

This is the A15 lesson in a different place: present in the payload, absent from
the interface. `curl` cannot tell the difference either.

**Fix.** Three changes, each the smallest that answers the report:

* The two tracks are `minmax(0, 1fr) minmax(0, 1fr)`. The zero minimum is the
  part that matters: a bare `1fr` is `minmax(auto, 1fr)`, so a long product name
  would widen its own column past the half and the split would stop being 50-50.
* A category is a native `<details>` with its count in the `<summary>`, all
  closed on arrival. No script, keyboard operable, announced as expanded or
  collapsed; the chevron is drawn with borders rather than a font glyph because
  a stack without U+25B8 rendered it as a missing-character box.
* The panel has no height of its own. `max-height`, `overflow-y`, the inner
  `.catalog-scroll` element and `position: sticky` are gone, so content cannot be
  clipped and the page scrolls instead. Sticky was also dropped because a panel
  taller than the viewport cannot be scrolled to its bottom while stuck.

**Verification.** `TestTheCatalogIsCollapsible` (5) and `TestTheSplitIsHalfAndHalf`
(2) pin the structure, the closed state, the absence of `max-height`/`overflow-y`,
the delegated click handler, the equal tracks and the ≤900 px stack. Checked in a
browser at 1440×900 and at 390×844: four categories and their counts on screen at
once; opening one shows its rows and pushes nothing out of the document; clicking
a row inside it fills the search box and sends no request. The click contract,
price parity and "every name resolves" tests were unchanged by the markup change
and still pass.

**Status: FIXED.** The 50-50 half of the report was a preference, not a defect;
it is implemented but not claimed as a bug.

---

### A19 — Every stored timestamp was local time, so a fresh catalog could never be stale

```json
{"built_at": "2026-10-27 16:30:09.402283", "age_seconds": -25098.7,
 "age_human": "just now", "stale": false}
```

That health payload was read three minutes after an ingest. The true build time
was `2026-10-27T09:30:09.402283+00:00`, which the same snapshot stored correctly
in `meta` — so the file disagreed with itself by exactly seven hours, and the
sign of the error was backwards.

**Root cause.** `crawled_at` and `started_at`/`finished_at` are `TIMESTAMP`
columns, which carry no zone. DuckDB converts an aware datetime into the
**session** timezone before storing it, so `datetime.now(timezone.utc)` written in
this environment landed as `Asia/Jakarta` wall time (UTC+7). Every reader did the
opposite: `parse_stored_timestamp` tags a zone-less value as UTC, deliberately, so
that a nine-hour-old catalog cannot look fresh in a UTC+7 timezone. Correct
intent, wrong premise — the writer had already moved the value. The age was
therefore understated by seven hours, and negative immediately after an ingest.

**Why it was invisible.** It was invisible in the exact situation the signal
exists for. The two tests that assert staleness set the threshold to 0.001 h
(3.6 s) against the committed snapshot, which was 16 hours old: wrong by seven
hours, but still comfortably positive, so `STALE` printed and both passed. The
first re-ingest during F-1 made the snapshot minutes old, the age went negative,
`humanise_age` clamped it to *just now*, and the two tests failed. They were
reporting a real defect, not wall-clock flakiness — which is also why the fix is
in the writer and not in the test.

A second representation of the same instant made the bug checkable without
waiting for a clock: `meta.built_at` is an ISO string with an explicit offset and
was always right, while `ingest_runs.finished_at` was local. Two answers to one
question, seven hours apart.

| Surface | Effect |
|---|---|
| `/api/health`, `./run.sh metrics` | age understated by the host's UTC offset; a 30 h catalog reads 23 h and is not flagged |
| immediately after any ingest | negative age, rendered "just now" — the one time the catalog is freshest reads as no information |
| `crawled_at` provenance on every row | local wall time, unlabelled, presented as the retrieval timestamp |

No price, stock state or answer was affected. The damage was to the freshness
signal, which is the claim that makes an automated refresh safe to trust.

**Fix.** `catalog.stored_timestamp` converts an aware datetime to UTC and drops
the zone before binding, at all four write sites (product `crawled_at`, tier
`crawled_at`, run `started_at`, run `finished_at`). Naive values pass through
unchanged, documented as already-UTC. The conversion is in the writer, not in a
session setting, so it does not depend on the host timezone or on every future
connection remembering to set one. `meta.built_at` still stores the aware value;
the two representations now agree.

**Falsification.** Three tests were written first and run against the old writer.
All three failed by 25200 s — the offset, not a rounding:

```
FAILED TestBuild::test_a_crawled_at_keeps_its_instant
FAILED TestBuild::test_the_two_representations_of_the_build_time_agree
FAILED TestBuild::test_a_snapshot_built_now_does_not_have_a_negative_age
E  assert -5 <= -25200.0
```

**Verification.** After the fix and a full re-ingest over HTTP at 1 req/s,
`ingest_runs.finished_at` and `meta.built_at` are the same instant and
`age_seconds` is `4.4`. Offline suite 1192 passed, 7 skipped; `./run.sh eval`
24/24; `--catalog v2` 21/21; `verify-refresh --keep` 12/12. Counts unchanged: 72
products, 105 tiers, 2 out of stock, 0 review items.

**Guard:** the three tests above. The first asserts the instant survives the
round trip through a real snapshot; the second compares the two stored
representations; the third fails on any negative age. Together they make the
local-time write fail on the next ingest rather than on the next demo.

---

## Part 2c — Gaps found by the brief audit · A20–A22 FIXED, A23–A24 OPEN

Requirements the brief states that the shipped code did not meet. A20–A22 came
from a compliance audit against `00_START_HERE_All_Briefs.md`; A23 came from the
section-by-section review of the brief's five "what we look for" areas. Both
probed the running service and the stored snapshot rather than reading the
modules — the same method as A12–A19. Each was reproduced before being written
down, with the reproduction in `/tmp/opencode/a3-gap-probe.py`. Registered
before being fixed, per the rule at the end of this file; each closed entry
carries the failing run it was seen to produce first, and the verification that
closed it.

A20 and A21 were fixed together — they are one requirement (PR7) failing at two
stages — and A22 separately. Both fixes were checked against the full suite,
`./run.sh eval`, and the single-turn digest.

### A20 — A budget's basis is read by pattern order, not by what the customer said

```
parse_budget("... under 240 a pack including VAT ...")
  -> (240.00, 'per pack, before VAT')          # wrong: the customer said including
```

**Root cause.** `interpret._BASIS_PATTERNS` is scanned in listed order and the
first match wins. The unit patterns (`per|a|each pack`) precede the VAT pattern
(`including vat`), so *"a pack including VAT"* matches `a pack` and the VAT
qualifier is never reached. PR7 requires the reply to state **which assumption
was used**; here it states the opposite of the one the customer gave.

**Why it matters.** The stated basis is the only signal the customer has that
the ceiling they gave was interpreted the way they meant. Stating `before VAT`
for an inclusive budget is worse than stating nothing: it is confidently wrong.

**Falsification.** `TestRuleInterpretation::test_a_vat_qualifier_beats_the_unit_word`
and `test_a_vat_qualifier_combines_with_the_unit_word`, both calling
`parse_budget` directly. Both failed against the old `_BASIS_PATTERNS` order:

```
FAILED TestRuleInterpretation::test_a_vat_qualifier_beats_the_unit_word
FAILED TestRuleInterpretation::test_a_vat_qualifier_combines_with_the_unit_word
```

**Fix.** The single ordered list is split into two independent questions.
`_UNIT_PATTERNS` still resolves the unit word; `_INCLUSIVE_VAT` matches the VAT
qualifier on its own; `_budget_basis` composes them (`"per pack, including VAT"`,
`"per ream, including VAT"`, else `before VAT`). A qualifier can no longer be
swallowed by the unit word, because they are no longer alternatives in one scan.

**Verification.** All four basis tests pass: the two above, an exclusive
qualifier (`"excluding VAT"` stays `before VAT`), and the original ream case.
`./run.sh eval` 24/24 unchanged.

### A21 — An inclusive-VAT budget is labelled, never applied

```
check_budget(facts, 20, 240.00, basis="per pack, including VAT")
  -> within_budget=True
     233.20 at 20 (within 240.00, per pack, including VAT)
```

The unit price is 233.20 **before** VAT; the same pack costs 249.52 including
it, which is over the 240.00 ceiling. `check_budget` carries the basis as a
label and compares ex-VAT regardless, so `search._evaluate` keeps the item and
`/api/ask` quotes it. PR6 fixes the comparison at *before VAT*; PR7 says the
customer may say otherwise, and when they do the comparison must honour it.

**Why it matters.** This is the same class as A8 — a comparison against the
wrong number — reached from the other direction. The arithmetic is exact; the
number it is exact about is the wrong number.

**Falsification.** `TestBudget::test_inclusive_basis_compares_the_gross_price`
(pricing), `test_inclusive_basis_still_passes_under_the_ceiling` (the bound stays
inclusive), and `TestBudgetAtQuantity::test_an_inclusive_budget_excludes_an_over_item`
(search). The first and third failed against the old comparison:

```
FAILED TestBudget::test_inclusive_basis_compares_the_gross_price
E  assert Money(satang=23320) == Money(satang=24952)
FAILED TestBudgetAtQuantity::test_an_inclusive_budget_excludes_an_over_item
E  assert 'PL-PR-LTR-GL-130-40' not in {'PL-PR-LTR-GL-130-40'}
```

**Fix.** `pricing.comparable_unit_price(facts, quantity, basis)` returns the price
the budget is compared against — the ex-VAT unit price, or the VAT-inclusive one
when the basis says so. `check_budget` compares that, and `search._evaluate` and
`assistant._quantity_changes_the_answer` both call the same function instead of
`unit_price`, so the filter, the reply and the clarification rule agree by
construction rather than by three copies of the same condition. `BudgetCheck`
keeps the field it compared (`check.unit_price`), so the number in the reply is
the number that was tested.

**Verification.** All the above pass, plus the original PR6 cases at an exclusive
basis (unchanged). One evaluation reply changed, as intended: case 18 (*"budget
1500 including VAT"*) now states 111.96, the VAT-inclusive figure it compared,
where it stated 104.64. The single-turn digest was retaken with that
justification recorded in `tests/test_single_turn_unchanged.py`, and case 18 is
the only one of the 28 whose reply differs. `./run.sh eval` 24/24; `./run.sh
test` 1203 passed, 3 skipped.

### A22 — The multi-line endpoint quotes an out-of-stock item as available

```
POST /api/quote/lines {"lines":[{"sku":"PL-CL-A4-100-IVY","quantity":1}]}
  -> 200 {"outcome":"quoted",
          "figures":{"subtotal":"168.00","delivery":"150.00",
                     "total":"340.26", ...}}          # no stock field
```

`PL-CL-A4-100-IVY` is out of stock, with a restock date of 20 November 2026.
`/api/ask` and `/api/quote` both refuse it correctly, because availability is
enforced in `search.py` — but `/api/quote/lines` prices known SKUs through
`pricing.quote()` directly and never consults stock state. PR8 is unconditional:
an unavailable item must not be quoted as available, on any entry point.

**Why it matters.** It is the one endpoint a cart or a sales UI would use to
build an order, so it is exactly where an unorderable line must not go unnoticed
— and it returns a total the customer could act on.

**Falsification.** `TestMultiLine::test_an_out_of_stock_line_is_refused`,
`test_a_basket_with_one_unavailable_line_prices_nothing`,
`test_the_refusal_names_every_unavailable_line`, posting the two v1 out-of-stock
SKUs and asserting the endpoint does not return a `quoted` figures block. All
three failed against the old handler, which returned 200:

```
FAILED TestMultiLine::test_an_out_of_stock_line_is_refused
E  assert 'quoted' == 'refused'
FAILED TestMultiLine::test_a_basket_with_one_unavailable_line_prices_nothing
E  assert 'quoted' == 'refused'
FAILED TestMultiLine::test_the_refusal_names_every_unavailable_line
E  assert 'quoted' == 'refused'
```

**Fix.** The endpoint checks stock itself, because it prices known SKUs and never
goes through the search layer that enforces PR8. Any unavailable line refuses the
**whole basket** — pricing the rest and dropping the line would return a total the
customer reads as complete. The refused item is built by `search.make_candidate`
and worded by the new `assistant.refusal_text`, both shared with `/api/ask`, so a
refusal has one shape and one wording wherever it is produced rather than two
that can drift. The new `api._record_refusal` records it as `refused`, not
`failed`: the request was valid and the refusal is an answer, so filing it with
the errors would inflate the failure rate the metrics exist to keep honest.

**Verification.** All four multi-line tests pass, plus the fully-available basket
still quoting. `tests/test_ui_catalog.py` was adapted — it now posts one SKU per
request, because a chunk containing an out-of-stock row refuses the whole chunk
under the new rule — and still compares every row against the endpoint.
`./run.sh test` 1207 passed, 3 skipped; `./run.sh eval` 24/24; `--catalog v2`
21/21; `verify-refresh --keep` 12/12; the audit probe `/tmp/opencode/a3-gap-probe.py`
now reports PASS on all four checks.

### A23 — A sibling variant's restock date is copied onto in-stock rows

```
GET /api/products?size=A4&category=Flyer printing
  PL-PR-A4-GL-100-40   in_stock   12 November 2026    <- wrong
  PL-PR-A4-GL-100-44   in_stock   12 November 2026    <- wrong
  PL-PR-A4-GL-130-40   in_stock   12 November 2026    <- wrong
  PL-PR-A4-GL-130-44   in_stock   12 November 2026    <- wrong
  PL-PR-A4-GL-170-40   in_stock   12 November 2026    <- wrong
```

`flyers-a4-gloss.html` marks exactly one row unavailable, `PL-PR-A4-GL-170-44`
(*"Out of stock — expected back 12 November 2026"*). Five of its six siblings are
in stock and have no date on the page, yet all five records carry that date.

**Root cause.** `extract._extract_variant_table` seeds every row from the
whole-page scan — `product.stock_status, product.back_in_stock_date = page_stock,
page_restock` — where `page_stock`/`page_restock` come from `_stock_state(html)`
run over the entire document. The per-row availability cell then overrides
`stock_status` but never clears `back_in_stock_date`, so a row that is explicitly
in stock keeps the date found in its sibling's cell.

**Why it matters.** This is the Data criterion in the brief — *"complete,
correctly typed records, including what is hidden in variants"* — failing in the
one place it is hardest to see: a value that is present, plausible, and attached
to the wrong record. `in_stock` plus a restock date is a self-contradicting
record, and it is exposed on `/api/products` and in every `/api/quote` line. The
refusal prose is unaffected today only because `assistant._refuse` runs for
unavailable items alone; the contradiction is in the data, not in the sentence.

**Falsification.** `TestVariantAvailability::test_an_in_stock_row_carries_no_restock_date`
and `test_the_out_of_stock_row_still_carries_its_own`, extracted from the real
`flyers-a4-gloss.html`. The first fails on five SKUs against the current
extractor.

### A24 — A budget stated per ream or per sheet is compared as if it were per pack

```
check_budget(PL-CS-A4-200-WH, 1, 250.00, basis="per ream, before VAT")
  -> within_budget=True
     178.00 at 1 (within 250.00, per ream, before VAT)

  that pack holds 100 sheets, so one ream of it costs 890.00 — 3.6x the ceiling
```

The opposite direction fails too: `PL-CP-A4-80` costs 0.26 a sheet, but a budget
of *"1.00 per sheet"* compares 129.00 against 1.00 and excludes it.

**Root cause.** `interpret._UNIT_PATTERNS` accepts *pack*, *ream* and *sheet*,
and `BudgetCheck.basis` reports the one it read — but `pricing.check_budget`
compares `unit_price()` (always per pack) with the budget and never converts by
the pack's sheet count. The unit word is a label, not an arithmetic input. This
is the same shape as A21: a basis that is parsed, echoed and not applied.

**Why it matters.** It is the Search criterion's *"unit and size normalisation"*
on the one path where a wrong unit changes a verdict rather than a sentence. It
happens to be harmless for copy paper, where a pack is a 500-sheet ream — which
is exactly why it went unnoticed: the common case is coincidentally correct. For
the 100-sheet and 250-sheet packs the error is 2x–5x, and it quotes items far
over the ceiling or hides items well under it.

**Falsification.** `TestBudget::test_a_per_sheet_budget_is_converted_by_pack_size`
and `test_a_per_ream_budget_is_converted_by_pack_size` in `tests/test_pricing.py`,
plus `TestBudgetAtQuantity::test_a_per_ream_budget_excludes_an_over_item` in
`tests/test_search.py`. The first two fail on the arithmetic, the third on the
membership.

**Note.** The fix must stay exact: compare `pack_price * sheets_per_stated_unit`
against `budget * pack_sheets` so both sides are integers, rather than dividing
money and rounding.

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
