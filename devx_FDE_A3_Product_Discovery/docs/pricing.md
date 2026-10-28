# Pricing rules

How every monetary figure in this system is decided, and which requirement each
rule satisfies. The code is `src/paperlane/pricing.py` and `src/paperlane/money.py`;
the tests are `tests/test_pricing.py` and `tests/test_money.py`.

The customer's rules PR1–PR8 are the agreed specification. They are reproduced
here in the order they are applied, because the *order* is where the bugs live.

---

## PR1 — Prices exclude VAT and are per pack

**Requirement:** `pricing-engine` → "Money is exact and never floating point"
**Code:** `money.py` — `Money`, `to_satang`, `round_half_up`

All catalog prices are ex-VAT and quoted per pack. Pack size varies by product
(50, 100, 250 or 500 sheets), which is why `pack_sheets` is stored separately
from price: "under 250 a pack" is unanswerable without it.

Money is integer satang. `Money.satang` is an `int`; there is no float anywhere
in the money path, and `to_satang` raises on a float argument rather than
converting it. The reason is concrete: `Decimal(233.20) != Decimal("233.20")`,
so a single float in the chain silently changes a total. The site's JSON is
parsed with `parse_float=Decimal` for the same reason.

---

## PR2 — Volume pricing is per item, highest met tier

**Requirement:** `pricing-engine` → "Unit price is selected at the requested quantity",
"Volume tiers are evaluated per item, not per product family"
**Code:** `pricing.unit_price`, `pricing.applied_tier`

Tiers are keyed by **leaf SKU**, not by product page. Two variants on one page
(`-40` single-sided, `-44` double-sided) have separate tier documents, so ten of
each does not reach a 20+ tier.

Selection order inside a SKU: the tier with the largest `min_qty` that is
`<= quantity`.

### The quantity is the item's, not the line's

`quote` sums the quantity **per SKU** before choosing the tier, so a caller that
asks for 10 + 10 of one SKU is priced at the 20+ tier, exactly as if it had asked
for 20 on one line. The caller's line structure is preserved — one output line
per requested line — because the order's shape is theirs; only the tier lookup is
shared. Pricing each line from its own quantity charged 4,042.00 for a basket
that costs 3,784.00 as a single line, and charged it in the customer's
disadvantage (`BUG.md` A26).

### The line that goes wrong

```python
best = facts.list_price     # NOT None
```

Most SKUs' lowest tier is 5+ or 10+. At quantity 1 no tier matches at all, so a
`min()`-over-tiers implementation returns `None` and the caller crashes on
`NoneType * int`. This was a real defect found during analysis (`BUG.md` A8) and
is now a named test: `TestNoTierMet::test_does_not_return_none`.

---

## PR3 — A sale price replaces list and tiers

**Requirement:** `pricing-engine` → "Sale price takes precedence over all volume pricing"
**Code:** `pricing.unit_price` (first branch)

If `sale_price` is set it is returned immediately, before tiers are consulted.
The two cannot be combined. One item in v1 is on sale:
`PL-PR-LTR-GL-170-40`, 299.00 → 259.00, and the site's own tier document says
"Not available on sale items".

The sale price is easy to miss in the markup, because the cell contains the
struck-through list price first:

```html
<td><del>฿299.00</del> ฿259.00<span class='sale'>Sale</span></td>
```

A parser that takes the first currency amount on the row quotes 299.00 — the
higher, wrong price.

---

## PR4 — Delivery is free from 3,000, otherwise 150 per **order**

**Requirement:** `pricing-engine` → "Delivery is charged once per order"
**Code:** `pricing.quote`

```
subtotal >= 3000.00  ->  0.00
subtotal  < 3000.00  ->  150.00, once for the whole order
```

Delivery is evaluated against the **summed pre-tax subtotal**, never per line.
The distinction only shows up on a mixed order whose lines are each below the
threshold but whose total clears it:

| | subtotal | delivery | VAT | total |
|---|---|---|---|---|
| correct (per order) | 3010.30 | 0.00 | 210.72 | **3221.02** |
| bug (per line) | 3010.30 | 300.00 | 231.72 | 3542.02 |

That is 321.00 too high, and no single-item test can see it.

The boundary is **inclusive** — `delivery.html` says "from THB 3,000 or more".
It is reachable in v1: `PL-CP-A4-80-ECO` at 25 × 120.00 = 3000.00 exactly, so a
`>` instead of `>=` charges 150.00 on real data.

---

## PR5 — VAT is 7% of (subtotal + delivery), half-up to 2 decimals

**Requirement:** `pricing-engine` → "Tax is charged on subtotal plus delivery"
**Code:** `pricing.quote`, `money.percent_of`, `money.round_half_up`

```
vat   = round_half_up((subtotal + delivery) * 7 / 100)
total = subtotal + delivery + vat
```

VAT is charged on the delivery charge too. Charging it on the subtotal alone
understates the total by exactly 7% of the delivery fee — 10.50 on a 150.00
fee — and is only detectable on an order small enough to pay delivery.

Rounding is **half-up**, not Python's default half-to-even: `0.125` rounds to
`0.13`, where `round(0.125, 2)` gives `0.12`. Rounding happens exactly once, at
the end, in `round_half_up`.

---

## PR6 — Compare the budget with the unit price at the requested quantity

**Requirement:** `pricing-engine` → "Budget comparison uses the unit price at the
requested quantity, before tax"
**Code:** `pricing.check_budget`

This is the assignment's central trap, and the brief's own example contains it:

> "We need letter-size flyers, one side, colour, under 250 a pack, 20 packs."

The budget comes before the quantity, and whether it is met depends on the
quantity:

| SKU | qty | unit price | vs "under 250" |
|---|---|---|---|
| `PL-PR-LTR-GL-130-40` | 1 | 265.00 | **fails** |
| | 5 | 249.10 | passes |
| | 20 | 233.20 | passes |

Comparing the budget against the **list price** (265.00) gets the brief's own
example wrong. The bound is inclusive: PR6 says "maximum price per pack", so a
unit price exactly equal to the budget is within budget.

### The unit the budget is stated in

A budget may be stated per pack, per ream or per sheet, and the price is always
quoted per pack. The comparison converts by the pack's sheet count — a ream is
500 sheets, so a 178.00 pack of 100 is **890.00 a ream** and fails a 250.00
per-ream ceiling, while 129.00 for a pack of 500 is **0.26 a sheet** and passes a
1.00 per-sheet ceiling (`BUG.md` A24). Same shape as the VAT basis: a unit word
that is parsed, echoed in the reply, and therefore applied.

The verdict is computed on integers — `price × sheets_per_stated_unit` against
`budget × pack_sheets` — because a per-sheet price rounded to the satang is not
precise enough to decide a boundary. `pricing.budget_ok` is the one place that
decides it; `comparable_unit_price` returns the figure the reply prints.

---

## PR7 — Budgets exclude VAT unless stated; say which assumption was used

**Requirement:** `pricing-engine` → "Budget comparison uses the unit price at the
requested quantity, before tax"
**Code:** `interpret._budget_basis`, `pricing.comparable_unit_price`,
`pricing.BudgetCheck.basis`

The basis is **parsed from what the customer said, then applied**.

- `interpret._budget_basis` assembles it from two independent questions — the
  unit word (*pack*, *ream*, *sheet*) and the VAT qualifier (*"including VAT"*,
  *"inclusive of VAT"*, *"incl. VAT"*). They were once one ordered list of
  alternatives, which meant *"a pack including VAT"* matched the unit word first
  and the qualifier was silently dropped (BUG.md A20).
- `pricing.comparable_unit_price` returns the price the budget is compared
  **against**: the ex-VAT unit price by default (PR6), or the VAT-inclusive one
  when the stated basis says so. One function, so the engine, the search filter
  and the clarification rule cannot disagree about what "within budget" means
  (BUG.md A21).

`BudgetCheck` carries the same `basis` string and `describe()` always includes
it, so the reply always states the assumption it used. `unit_price` on the result
is the number actually compared — 233.20 for an ex-VAT basis, 249.52 for an
inclusive one on the same pack at 20, 890.00 for a per-ream basis on a pack of
100.

The default when the customer states nothing is `"per pack, before VAT"`, which
is PR7's assumption and PR6's rule.

### The basis is a closed set

`pricing.BUDGET_BASES` holds the six strings the engine can actually apply —
*per pack / per ream / per sheet*, each *before* or *including VAT*. It is the
whole vocabulary, because `interpret._budget_basis` produces those forms and
nothing else, and it is one set rather than a second copy of the rule.

A basis outside it is never printed. The model may choose among the six and no
more: `merge_model_and_rules` keeps the rules' basis for anything else and
records a `budget_basis:` note, and `interpret.validate` normalises the field for
every entry point that reaches it, so the assumption the reply states is always
one the arithmetic used (`BUG.md` A25). `POST /api/quote` refuses an unknown
basis with a `422` naming the field, in the same way it refuses an unknown size.

---

## PR8 — Out-of-stock and discontinued items are not quoted as available

**Requirement:** `pricing-engine` → "Only catalog values may enter a quote"
**Code:** enforced in `search.py` (stock state is a filter); also checked in
`api.multi_line_quote`, which prices known SKUs directly and does not go through
the search layer (BUG.md A22)

Pricing itself is indifferent to stock: these items have perfectly valid prices.
Availability is therefore a **search-layer** concern, and the refusal is a
distinct outcome (`refused`), not an error.

Both entry points enforce it. `/api/ask` and `/api/quote` reach it through
`search`, which splits matches into `matches` (available) and `unavailable`. The
multi-line endpoint prices known SKUs through `pricing.quote()` and never
consults the catalog, so it checks stock itself and refuses the **whole basket**
when any line is unavailable — quoting the rest and dropping the line would
return a total the customer reads as complete.

Two items in v1 are out of stock — `PL-PR-A4-GL-170-44` and `PL-CL-A4-100-IVY` —
and both carry a restock date. Zero are discontinued in v1, so that path is
implemented from the rule and first exercised against the mutated site.

---

## What may enter a quote

**Requirement:** `pricing-engine` → "Only catalog values may enter a quote",
"Pricing is a pure function of catalog data"

Every figure traces to a stored list, sale or tier price, or to a value computed
from those by the rules above. The model is not in this path at all: it emits
search criteria only, and `assistant.py` discards any price it returns.

`quote()` takes catalog facts as arguments and returns a value. It performs no
I/O, reads no clock, and holds no state, so the same inputs always produce the
same output — which is what makes the evaluation set reproducible.

---

## Worked totals

All recomputed from the live catalog with `Decimal` and explicit half-up
(`pre/ANALYZE_01.md` §5, re-verified in §12). These are the figures the tests assert.

| SKU | qty | unit | subtotal | delivery | VAT | total |
|---|---|---|---|---|---|---|
| `PL-CP-A5-80` | 1 | 72.00 | 72.00 | 150.00 | 15.54 | **237.54** |
| `PL-CP-A5-80` | 3 | 72.00 | 216.00 | 150.00 | 25.62 | **391.62** |
| `PL-CP-A4-80` | 1 | 129.00 | 129.00 | 150.00 | 19.53 | **298.53** |
| `PL-CP-A4-80` | 10 | 122.55 | 1225.50 | 150.00 | 96.29 | **1471.79** |
| `PL-CP-A4-80` | 50 | 116.10 | 5805.00 | 0.00 | 406.35 | **6211.35** |
| `PL-PR-A5-MT-100-10` | 1 | 79.00 | 79.00 | 150.00 | 16.03 | **245.03** |
| `PL-PR-A5-MT-100-10` | 3 | 79.00 | 237.00 | 150.00 | 27.09 | **414.09** |
| `PL-PR-A5-MT-100-10` | 20 | 69.52 | 1390.40 | 150.00 | 107.83 | **1648.23** |
| `PL-PR-LTR-GL-130-40` | 20 | 233.20 | 4664.00 | 0.00 | 326.48 | **4990.48** |
| `PL-PR-LTR-GL-170-40` | 20 | 259.00 (sale) | 5180.00 | 0.00 | 362.60 | **5542.60** |
| `PL-CP-A4-80-ECO` | 25 | 120.00 | 3000.00 | 0.00 | 210.00 | **3210.00** |
| 20 × `PL-CP-A4-80` + 5 × `PL-PR-A4-MT-100-10` | — | — | 3010.30 | 0.00 | 210.72 | **3221.02** |

The last row is the mixed basket: neither line clears 3,000 alone.

---

## Known limits of this layer

- **`PL-CP-A4-80`'s list price is 129.00, not 122.55.** 122.55 is its 10+ tier.
  Reading the tier document where the page should have been read is the defect
  that corrupted an earlier draft of these numbers (`BUG.md` A9). The rule that
  follows: read the **list price from the page's price box**, and **tiers from
  the tier document**.
- **No v1 unit price is exactly 250.00 or 300.00**, so the budget boundary is
  only testable on synthetic values. The delivery boundary *is* reachable
  (see `PL-CP-A4-80-ECO` above).
- **`28 lb` and `32 lb`** conversions are implemented from the brief's table but
  no v1 product uses them; they are first exercised against the mutated site.
