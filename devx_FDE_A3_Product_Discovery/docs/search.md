# Search

How a customer's stated requirements become a ranked, justified set of catalog
items — and how the system says "nothing matched" instead of showing something
close.

Code: `src/paperlane/criteria.py`, `search.py`, `aliases.py`.
Tests: `tests/test_search.py`, `test_aliases.py`.

---

## The order of operations

```
Criteria  →  filter (hard)  →  rank (total order)  →  justify (by-product)
                  │                                        │
                  └── nothing survives ──→ relax one constraint ──→ alternatives
```

Filtering happens before ranking, and ranking never removes anything. That
separation is what keeps a soft preference from quietly becoming a constraint.

---

## Hard constraints

Every requirement the customer states as a need is a filter. An item that
contradicts one is gone — not ranked low, not shown with a caveat.

| Criteria field | Matches against | Semantics |
|---|---|---|
| `category` | `products.category` | exact |
| `size_code` | `products.size_code` | exact, on the **code** never display text |
| `weight_gsm` | `products.weight_gsm` | exact |
| `weight_gsm_min` / `_max` | `products.weight_gsm` | floor / ceiling |
| `colour_name` | `products.colour_name` | whole-word subset |
| `finish` | `products.finish` | substring |
| `sides` | `products.sides` | exact, **only when applicable** |
| `colour_mode` | `products.colour_mode` | whole-word subset, **only when applicable** |
| `budget_per_unit` | unit price at the requested quantity | `<=`, inclusive |

### Why matching uses the size code

`8.5 × 11 in` and `8½ × 11 in` appear on the *same two flyer pages* — the `<h1>`
uses one spelling and the body prose the other. A filter written as
`"8.5" in text` passes or fails depending on which occurrence it happens to
read. Both spellings normalise to `LTR` at ingest, so the filter compares codes
and the question never arises.

---

## Not-applicable is not a mismatch

This is the subtlest rule in the layer, and it has two halves.

A plain-paper product has `sides = NULL` and `colour_mode = NULL`. Those
attributes **do not apply** to it. So:

1. **A printing constraint does not exclude it.** Ask for double-sided and
   `PL-CP-A4-80` stays eligible, because "double-sided" is not a claim it
   contradicts — it is a claim that was never about it.
2. **It is never described as matching it.** The justification for
   `PL-CP-A4-80` contains no `sides` entry. The reply does not say "matches
   double-sided printing" about plain paper.

The implementation is one predicate:

```python
def _printing_applies(product) -> bool:
    return product.get("sides") is not None or product.get("colour_mode") is not None
```

A constraint on `sides` or `colour_mode` is only enforced when that returns
`True`. Everything else about the item is still filtered normally.

By contrast, **`colour_name` (paper shade) applies to everything**, so a shade
constraint *does* exclude a flyer that states no shade — a flyer has no paper
shade to match.

| Request | Plain paper (no sides) | Single-sided flyer | Double-sided flyer |
|---|---|---|---|
| `sides="double"` | passes, not claimed | **excluded** | passes, claimed |
| `colour_name="white"` | passes | **excluded** (no shade) | **excluded** (no shade) |

---

## Ambiguity is resolved by context, or asked about

"Colour" means two unrelated things in this catalog:

| Noun nearby | Attribute | Field |
|---|---|---|
| paper, sheet, stock, shade, card, ream, pad | paper **shade** | `colour_name` |
| print, printing, printed, flyer, ink, CMYK | **print colour mode** | `colour_mode` |

`resolve_colour()` returns `(shade, mode, ambiguous)`:

* a **named shade** (`ivory`, `pastel blue`, `cream`) → shade, never ambiguous
* a **print noun** with "colour" → `Full colour (CMYK)`
* a **paper noun** with "colour" and no shade named → ambiguous
* **"colour" alone** → ambiguous

When `ambiguous` is true, `Criteria.colour_ambiguous` is set and the assistant
asks which was meant. It does not pick one, because the two senses select
disjoint item sets — guessing wrong returns a completely different quote.

The two are stored in separate columns and **neither is inferred from the
other**. On a flyer page, `Colour` in the table is the print mode; on a
plain-paper page, `Colour` in the table is the shade. Same word, different
column, decided at ingest by which shape the page used.

---

## Aliases: everyday phrasings onto catalog vocabulary

The requirement is *paired*: two phrasings of one requirement must select the
same items. `tests/test_aliases.py` therefore mostly asserts equality between
two resolutions rather than a literal.

### Size

| Phrasing | Resolves to |
|---|---|
| `A4`, `a4` | `A4` |
| `letter`, `US Letter`, `letter size` | `LTR` |
| `8.5 x 11`, `8.5 by 11`, `8½ x 11`, `8.5 × 11 in` | `LTR` |
| `legal`, `8.5 x 14` | `LGL` |
| `210 x 297 mm` | `A4` |
| `B5` | **raises** `SizeError` |

`B5` is a real paper size this catalog does not stock. It raises so the
assistant can report the gap, rather than silently returning A4 items as though
they matched.

### Weight

| Phrasing | Resolves to |
|---|---|
| `100 gsm` | exact 100 |
| `90 g/m²`, `90 g/m2`, `90 grams per square metre` | exact 90 |
| `20 lb` | exact 75, from the agreed table |
| `at least 100 gsm` | floor 100 |
| `under 130 gsm` | ceiling 130 |
| `26 lb` | **nothing** — not in the table, so no conversion is defensible |

### Printing notation

The site's own gloss: *"single-sided full colour is often written 4/0,
double-sided full colour 4/4."*

| Phrasing | Sides | Colour mode |
|---|---|---|
| `4/0` | single | Full colour (CMYK) |
| `4/4` | double | Full colour (CMYK) |
| `1/0` | single | Black and white |
| `1/1` | double | Black and white |
| `double sided`, `two-sided`, `duplex` | double | — |
| `single sided`, `one side`, `simplex` | single | — |
| `b&w`, `mono`, `greyscale` | — | Black and white |

`resolve_printing("4/4") == resolve_printing("double-sided full colour")` — that
equality is the requirement, and it is asserted directly.

### Finish and category

`gloss` / `glossy` / `high-gloss` → `Gloss`; `matte` / `matt` → `Matte`;
`uncoated` / `plain` → `Uncoated`.

Category aliases are matched **longest first**, so `flyer printing` beats the
shorter `printing`.

---

## Soft preferences rank, never exclude

`Criteria` carries `prefer_cheapest` and `prefer_in_stock`. These influence
order only. An item is never removed because a preference is unmet — that would
silently turn a preference into a constraint.

---

## Ranking is deterministic and total

```python
RANKING_ORDER = (
    "availability_penalty",   # available before unavailable
    "budget_margin",          # cheapest first, when no preference distinguishes
    "similarity",             # CONDITIONAL: only when a provider is configured
    "sku",                    # stable, total tiebreak
)
```

which the implementation expresses as the sort key:

```python
def _rank_key(candidate, *, use_similarity=False):
    if use_similarity and candidate.similarity is not None:
        return (
            _availability_penalty(candidate),
            candidate.unit_price.satang,
            -candidate.similarity,
            candidate.sku,
        )
    return (
        _availability_penalty(candidate),   # in_stock 0, out 1, discontinued 2
        candidate.unit_price.satang,        # cheapest first
        candidate.sku,                      # stable, total tiebreak
    )
```

**The `sku` element is what makes the order total.** Two items can never tie, so
the sort does not depend on input order, dictionary iteration order, or the
version of Python. Verified:

* repeated runs produce identical order (5 runs)
* reversing the input list produces identical order
* two items at the same price still order consistently (`AAA` before `ZZZ`)

A test asserts `RANKING_ORDER` equals the tuple in the sort key, so the
documented chain and the code cannot drift apart. The similarity term is
conditional, and a second constant `RANKING_ORDER_WITHOUT_SIMILARITY` pins the
unconfigured key — which is asserted as an *exact tuple*, not as an equivalent
ordering, so "behaves exactly as before" is a testable claim rather than a
coincidence.

### The conditional similarity term

With no embedding provider configured — the default, and the only state the
offline test suite runs in — the key is the three-element tuple above and no
network call is attempted. With one configured, `similarity` decides ties *among
items priced equally*; it sorts after price so cheapest-first is never displaced.

The position is a measured decision: before price, it regressed 6 of 28 recorded
cases and moved the expected first result in 9. After price it reorders 3 of 28
with zero regressions and zero improvements — a pure tiebreak. Full numbers,
method and caveats are in [`semantic-ranking.md`](semantic-ranking.md).

### Why cheapest-first is not just a convenience

The brief's scoring includes "right products and totals". When several items
satisfy every stated requirement and nothing distinguishes them, returning the
cheapest is the only defensible default — any other order would need a reason
the customer did not give.

---

## Justification is a by-product of filtering

`MatchReason` records are created **inside** `_evaluate()` as each constraint
passes. They are not composed afterwards, and no model contributes to them.

```python
MatchReason(
    attribute="budget per unit",
    requested="250.00",
    actual="233.20",
    detail="at quantity 20, 20+ tier applied, per pack, before VAT",
)
```

Consequences that matter:

* A reason exists **only** for a constraint the item genuinely satisfied, so
  plain paper never carries a `sides` reason.
* A quantity-dependent requirement records **the quantity and the tier used**,
  because the same item has a different answer at a different quantity.
* The reasons serialise directly into the reply (`as_dict()`), so the prose the
  customer reads is generated from the same records the filter produced. There
  is no second computation to disagree with the first.

---

## Unavailable items

Out-of-stock and discontinued items are **filtered and returned, then
separated**:

```python
available   = tuple(c for c in matches if c.available)
unavailable = tuple(c for c in matches if not c.available)
```

They are never silently omitted (the customer would not know the product
exists) and never silently offered (they would get a quote for something they
cannot buy). `SearchResult.unavailable` carries `stock_status` and
`back_in_stock_date`, so the refusal can say *when*.

Ranking already sorts unavailable items last, so they cannot displace a
purchasable match.

---

## No match, and relaxation

When nothing satisfies every requirement, the result is reported as a **no
match** — not a loosely-related set presented as though it matched.

Alternatives are offered **separately**, each labelled with the requirement that
was relaxed:

```python
RELAXATION_ORDER = ("budget", "finish", "weight", "sides", "colour", "size")
```

Cheapest-to-lose first: a customer usually has room on budget and almost never
on size. `SearchResult.relaxed` names the dropped constraint, so the reply can
say *"nothing matched at 200 gsm; here are A5 options if the weight can move"*
rather than implying a match.

The three outcomes are structurally distinct and cannot be confused:

| Situation | `matches` | `alternatives` | `relaxed` |
|---|---|---|---|
| everything satisfied | ranked items | `()` | `None` |
| nothing satisfied, close items exist | `()` | ranked items | named |
| nothing satisfied, nothing close | `()` | `()` | `None` |

---

## The budget trap, in the search layer

`budget_per_unit` is compared against `unit_price(facts, quantity)` — the price
**at the requested quantity**, selected by the pricing engine.

For `PL-PR-LTR-GL-130-40` (list 265.00, 20+ tier 233.20):

| Quantity | Unit price | vs "under 250" |
|---|---|---|
| 1 | 265.00 | **fails** |
| 20 | 233.20 | passes |

Comparing against the **list price** would reject the brief's own example
product at the quantity the customer asked for. A test asserts both halves:
that the naive comparison returns `False` and the correct one returns `True`.

The bound is **inclusive** — `<=`, not `<` — because PR6 says "maximum price per
pack". A unit price exactly equal to the budget is within budget, and there is a
test for `250.00` exactly and for `71.99` against a `72.00` item.

---

## What this layer does not do

* **No prices are invented.** Every figure comes from `pricing.unit_price()`.
* **No model.** `search.py` imports no network client; a complete result with
  justifications is produced from catalog rows and the request.
* **No fuzzy matching.** Every alias is explicit. A fuzzy match that returns the
  wrong product is worse than returning nothing, because the customer cannot
  tell it is wrong.
* **No ranking by relevance score.** The order is a total order on three
  concrete values, so it is reproducible and explainable.
