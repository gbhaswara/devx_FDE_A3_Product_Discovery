# ANALYZE_POST.md — the system as built

`../pre/ANALYZE_01.md` is the analysis that preceded the build: what the site is, which traps it contains, what the plan would be. This document is the other half. It is the end-to-end design **as the code actually implements it**, read back from `devx_FDE_A3_Product_Discovery/src/paperlane/`, and it covers the four layers the brief scores plus the workflow that produced them.

Every claim below is traceable to a named function or constant. Where a number is quoted it was measured, and where a decision had a rejected alternative the alternative is named — the reasoning is part of the design, not commentary on it.

Authority order for anything that disagrees: the code, then `ARCHITECTURE.md`, then this file.

---

## 0. The one constraint that shapes every layer

> **No price, total, discount or figure may originate from, or be restated by, a language model.**

This is not enforced by asking the model nicely. It is enforced by removing the channel:

```python
# criteria.py — the only object that crosses from interpretation into search
@dataclass(frozen=True)
class Criteria:
    category, size_code, weight_gsm_min/max, weight_gsm,
    colour_name, finish, sides, colour_mode,
    quantity, budget_per_unit, budget_basis
```

There is **no field for a price, a SKU, a total, or a reply**. `ALLOWED_CRITERIA_KEYS` in `interpret.py` mirrors that set, so a model that returns `{"price": "250.00"}` has the value discarded by the allow-list before it can reach anything. The model contributes *requirements*; deterministic code decides what they select, what they cost, and what the reply says.

The consequence, stated plainly: **"no invented products" and "no invented prices" are structural properties, not behavioural ones.** They do not depend on prompt wording, on model version, or on the model being correct. The two guards in `assistant.py` (`check_no_invented_products`, `check_figures_match`) exist as a second line for the *prose* — but the first line is that there was never anywhere for a number to enter.

That single decision is why the rest of the design can be split the way it is: interpretation is the only fallible component, so it is the only component that needs a fallback, a disclosure, and a measured failure rate.

---

## 1. Data — from 36 HTML pages to one queryable catalog

### 1.1 The shape of the problem

The reference site is static, small, and **inconsistent rather than complex** (`../pre/ANALYZE_01.md` §1.2). Measured facts:

| Fact | Value |
|---|---|
| Product pages | 36 |
| Leaf SKUs | **72** — 30 single-SKU pages + 42 flyer variant rows |
| Volume-pricing documents | 59, each belonging to a SKU that advertises one; **0 orphans** |
| Markup shapes | 4 — `variant-table` (6), `table` (10), `dl` (10), `prose` (10) |
| Weight input forms | 4 — grammage, `g/m²`, pounds+grammage, pounds alone |
| Out of stock | 2 |
| On sale | 1 |
| Discontinued | 0 in v1 |
| Full crawl | 103 requests ≈ 103 s at 1 req/s |
| Tier rows | 105 |

The single most expensive fact is **36 pages ≠ 36 SKUs**. Six flyer pages are variant tables whose every row is its own purchasable SKU with its own price and its own tier document. A crawler that treats a flyer page as one product loses **36 of 72 SKUs** — half the catalog, silently, with every total still arithmetically consistent for what remained. There is a test that pins 72.

### 1.2 The crawl — `crawl.py`

Discovery is by **following links**, never by a hard-coded URL list: `index.html` → 4 category pages (+3 pager pages) → 36 product pages → 59 pricing documents. A renamed page or a new category still works, which is what makes "the same code runs on the updated site" true rather than hopeful.

Politeness is a property of the client, not a convention:

```python
USER_AGENT = "PaperLaneCatalogBot/0.1 (assignment crawl; 1 req/s)"
# sequential, 1 req/s — the site permits 2 (robots.txt Crawl-delay: 1)
```

Sequential rather than concurrent, because a concurrent crawler at "1 req/s" is a promise about the *client*, and the requirement is about the *site*.

**Provenance is on every fetch, not reconstructed later.** `FetchedPage` carries `source_url` and `crawled_at` (UTC) from the moment the bytes arrive, and both are stored on every catalog row. A row whose origin cannot be named is a row nobody can defend in the demo.

Crucially, the site must be served over HTTP. Opening files from disk does not execute the volume-pricing fetch path, so the numbers would be quietly wrong in a way no test would catch. `docs/ingestion.md` states this as a hard precondition, and the run instructions serve the site first.

### 1.3 Extraction — `extract.py`, the ladder with a review floor

Four shapes are handled by **structure, not URL**:

```python
_detect_shape(html):
    "Options and prices"          -> variant-table
    <table class='specs'>          -> table
    <dl class='specs'>             -> dl
    "weighs N" with no spec block  -> prose
    otherwise                      -> unknown
```

The order matters and is deliberate. Shape detection by markup means a **new page in an existing shape is handled with no code change** — which is exactly the demo round's test.

The ladder descends: variant table → `<table>` → `<dl>` → prose regexes → (structured model extraction) → and finally **`ReviewRow`**. The floor is the load-bearing part:

> The ladder never raises for a page-level problem. Every failure becomes a `ReviewRow` with the URL, a reason, and a raw excerpt, and ingestion continues.

This is what turns *"the site changed"* from an exception into a **visible row in the review set**. An unknown shape does not drop a product; it files it where a human will see it. Compare the alternative — a single shape-specific parser — which is faster right up until the demo round adds a fifth shape, at which point it silently loses products.

The four shapes also use **different labels for the same concept**, and this is where a naive normaliser loses data without erroring. `docs/ingestion.md` has the full matrix; the two silent ones:

- **`Colour` is a different field in `table` and `variant-table`.** In `table` it is the paper shade (`White`); in `variant-table` it is the print mode (`Full colour (CMYK)`). Same label, two columns, decided at ingest by which shape the page used.
- **`dl` splits size into two fields** — `Paper size` = `A5` plus `Dimensions` = `148 × 210 mm` — while `table` concatenates them into one string (`A4 (210 × 297 mm)`). A normaliser that assumes one field per concept either loses the dimensions on every `dl` page or, worse, stores `A5` as display text and never derives a `size_code`.

Raw label and raw value are retained on every product alongside the canonical field, so a mapping mistake is **inspectable** rather than merely wrong.

### 1.4 Normalisation — `normalize.py`

Normalisation is where "the same thing written two ways" becomes one value. Three cases carry the risk.

**Weight, four forms.** `parse_weight` handles grammage, `g/m²` (U+00B2), `lb (gsm)` cross-checked, and `lb` alone converted from a fixed table: `20 lb → 75`, `24 → 90`, `28 → 105`, `32 → 120`. An unlisted pound value **raises** `WeightError` rather than extrapolating — a weight the catalog never stated is not inferable, and a guess there changes which products qualify. (v1 contains only the first two conversions; 28 and 32 lb exist only in the mutated v2 catalog, which is why those eval cases run there.)

**Size, three spellings.** Decimal, vulgar-fraction (`8½`) and unicode-multiplication (`8.5 × 11`) spellings of one size all produce one `size_code`. `parse_size` also recognises that `Paper size` gives the code directly while the dimensions corroborate it, and an unmappable size raises `SizeError` — reported, never silently unset.

**Pack size vs unit word.** `pack_sheets` is the authoritative quantity basis; `unit_word` is display text and is **never filtered on or compared against**. `pl-cl-a4-80-pyl.html` says `195.00 THB / ream` in its price box while its own table says `Pack contents: 500 sheets`. The words are unreliable and the count is not, so the words are decorative by construction. There is a test asserting no filter reads the unit word.

### 1.5 The store — `catalog.py`, rebuild-and-swap

The catalog is a **DuckDB file**. Each ingest builds a complete new file, validates it, and atomically replaces the serving one:

```python
build_snapshot(staged)     # fresh file, never mutated in place
swap_into_place(staged):   # existing -> *.previous   (for diff)
    os.replace(staged, target)   # atomic on one filesystem
```

Three properties fall out for free, each of which would otherwise need its own mechanism:

1. **A failed ingest cannot damage a working catalog.** The serving file is only ever replaced, never written.
2. **Readers are unaffected by a swap.** `os.replace` is atomic, so a reader sees the old file or the new one, never a half-written one. Reads use a separate read-only connection per request.
3. **Single-writer is a non-issue.** DuckDB permits one writer; the design removes the constraint rather than working around it with locks.

The `previous` file is what makes `./run.sh diff` possible without any history table: attach old and new read-only, full outer join, group into five change kinds — `added`, `withdrawn`, `price_changed`, `availability_changed`, `tier_changed`.

**Two cross-checks run at the end of every ingest. Neither corrects anything; both flag.** Availability is rendered on both the category card and the product page; when they disagree, *both values are kept* and a review row records the disagreement — neither source overwrites the other. And the tier-document count must equal the number of SKUs advertising volume pricing (`59 = 59` on v1), so a SKU whose document fails to fetch produces a review row rather than a silent zero.

The design principle underneath all of §1: **absent is not negative, and unparsed is not absent.** A value the site did not state is not the same as a value the site stated as "no", and neither is the same as a parse that failed. Keeping those apart is what lets a price be trusted.

---

## 2. Search — filter hard, rank totally, justify by construction

`search.py`. The order of operations is the whole design:

```
Criteria → filter (hard) → rank (total order) → justify (by-product)
              │
              └── nothing survives ──→ relax ONE constraint ──→ alternatives
```

**Filtering happens before ranking, and ranking never removes anything.** That separation is what stops a soft preference from quietly becoming a constraint — the failure mode where a customer's "prefer cheaper" silently deletes the product they actually needed.

### 2.1 Hard constraints, and the not-applicable rule

Every requirement the customer states as a need is a filter. An item that contradicts one is **gone** — not ranked low, not shown with a caveat.

The subtle rule is **not-applicable is not a mismatch**. A printing constraint (`sides`, `colour_mode`) is only meaningful for printed goods:

```python
def _printing_applies(product) -> bool:
    return product.get("sides") is not None or product.get("colour_mode") is not None
```

A constraint on `sides` is enforced **only when that returns True**. So `sides="double"` on a request for plain copy paper does not exclude the plain paper, because "double-sided" is not a claim plain paper contradicts — it is a claim that was never about it. And it is **never described as matching it** either: the justification for the plain paper contains no `sides` entry. Both halves are asserted.

`colour_name` (paper shade) is the opposite: it applies to everything, so a shade constraint *does* exclude a flyer that states no shade. A flyer has no paper shade to match.

The naive implementation of this returns **the wrong product set with the right prices** — which no total-based assertion catches. It is fixed once, at the query layer, because that is the only place it can be fixed once.

### 2.2 Aliases — explicit, never fuzzy

`aliases.py` maps everyday phrasings onto catalog vocabulary. The requirement is **paired**: two phrasings of one requirement must select the same items. `tests/test_aliases.py` therefore asserts *equality between two resolutions* far more often than it asserts a literal — `letter`, `US Letter`, `8.5 x 11`, `8½ x 11`, `210 x 297 mm` all land on `A4`/`LTR` by the same route.

Two deliberate non-mappings:

- `B5` **raises** `SizeError`. It is a real paper size this catalog does not stock, so the assistant reports the gap instead of silently returning A4 as though it matched.
- `26 lb` resolves to **nothing**, because 26 is not in the agreed conversion table and no conversion is defensible.

There is **no fuzzy matching anywhere**. A fuzzy match that returns the wrong product is worse than returning nothing, because the customer cannot tell it is wrong. The same reasoning rejects ranking by an opaque relevance score.

### 2.3 Ambiguity is resolved by context or asked about

"Colour" means two unrelated things. `resolve_colour()` returns `(shade, mode, ambiguous)`, decided by the nearby noun: paper/sheet/shade/card/ream → shade; print/flyer/ink/CMYK → print mode; bare "colour" or a paper noun with no shade named → **ambiguous**, which sets `Criteria.colour_ambiguous` and produces a clarifying question. The two senses select **disjoint item sets**, so guessing wrong returns a completely different quote. Guessing is not a cheap mistake here.

### 2.4 Ranking — deterministic and total

```python
RANKING_ORDER = (
    "availability_penalty",   # available before unavailable
    "budget_margin",          # cheapest first, when no preference distinguishes
    "similarity",             # CONDITIONAL: only when a provider is configured
    "sku",                    # stable, total tiebreak
)
```

The **`sku` term is what makes the order total**. Two items can never tie, so the sort does not depend on input order, dictionary iteration order, or the Python version. Verified three ways: repeated runs identical, reversed input identical, equal-price items still order consistently. A test asserts `RANKING_ORDER` **equals the tuple in the sort key**, so the documented chain and the code cannot drift.

The similarity term is **conditional**, and it sorts *after* price so cheapest-first is never displaced. With no provider configured — the default, and the only state the offline suite runs in — the key is the exact three-element tuple `RANKING_ORDER_WITHOUT_SIMILARITY`, asserted as an **exact tuple** rather than an equivalent ordering, because a constant `0.0` would order identically while still being a different key. The position was measured, not chosen: before price it regressed 6 of 28 cases; after price it reorders 3 of 28 with zero regressions and zero improvements. That is a tiebreak, and it is documented as one rather than sold as quality.

### 2.5 Justification is a by-product, not a second computation

`MatchReason` records are created **inside `_evaluate()` as each constraint passes**. They are not composed afterwards, and no model contributes to them. Two consequences:

- A reason exists **only for a constraint the item genuinely satisfied**, so plain paper never carries a `sides` reason.
- A quantity-dependent requirement records **the quantity and the tier used**, because the same item has a different answer at a different quantity.

The reasons serialise straight into the reply (`as_dict()`), so the prose the customer reads is generated from the same records the filter produced. **There is no second computation to disagree with the first** — which is the failure mode that would otherwise be invisible until a customer quoted a price the system never computed.

### 2.6 No match, and relaxation

When nothing satisfies every requirement, the result is reported as **no match** — not a loosely-related set presented as though it matched. Alternatives are offered **separately**, each labelled with the constraint that was dropped:

```python
RELAXATION_ORDER = ("budget", "finish", "weight", "sides", "colour", "size")
```

Cheapest-to-lose first: a customer usually has room on budget and almost never on size. The three situations are structurally distinct and cannot be confused:

| Situation | `matches` | `alternatives` | `relaxed` |
|---|---|---|---|
| everything satisfied | ranked items | `()` | `None` |
| nothing satisfied, close items exist | `()` | ranked items | named |
| nothing satisfied, nothing close | `()` | `()` | `None` |

Unavailable items are a fourth case: **filtered, then separated**, never silently omitted (the customer would not know the product exists) and never silently offered (they would get a quote for something they cannot buy). `SearchResult.unavailable` carries `stock_status` and `back_in_stock_date`, so the refusal can say *when*.

---

## 3. Agents — interpretation is the only fallible part

`assistant.py` + `interpret.py`. The boundary is drawn once:

```
request text
    │
    ├─ model client ──┐        (criteria ONLY — no prices, no SKUs, no prose)
    │                 ├─→ Criteria → validate → search → quote
    └─ rule parser ───┘                                    │
                                                           ↓
                                                  reply rendered here
```

The model's **entire contribution is criteria**. The reply is rendered from deterministic values in `assistant.py`. That is the §0 constraint restated as a data-flow property.

### 3.1 Two paths, disclosed

`interpret(text, client)` returns an `Interpretation` carrying `path`:

| `path` | Meaning |
|---|---|
| `model` | the model answered and the rules added nothing |
| `mixed` | both contributed; model values won where present |
| `rules` | the model was unavailable, unconfigured, or returned nothing usable |

The disclosure is not cosmetic. A salesperson needs to know whether requirements were read by a model or by a rule, because **they fail differently**: the rules are predictable and narrow, the model is flexible and occasionally wrong.

And the fallback is **not a degraded path**. `interpret_rules()` covers the common request shapes completely and needs no network; every test in `tests/test_assistant.py` runs through it. The system answers with no model configured at all — that is asserted, not hoped for. This is only defensible because quoting never needed the model in the first place.

### 3.2 Model values are re-resolved, never trusted

Measured against the live endpoint, the model returns **correct meanings in the wrong vocabulary**: `"size": "letter"` (catalog stores `LTR`), `"category": "flyers"` (`Flyer printing`), `"sides": "one-sided"` (`single`), `"colour": "colour"` (ambiguous → becomes a question).

Every model value therefore goes through **the same alias resolvers the rules use**. Passing `"LETTER"` straight into `Criteria.size_code` produced a value that failed validation, which discarded an otherwise perfect interpretation — a failure that looks like "the model understood nothing" when the model in fact understood everything.

The related trap is the key vocabulary. Asked for `weight_gsm` the model returns `gsm`; for `quantity`, `packs`. `normalise_model_keys()` translates before the allow-list runs. Without it the allow-list discarded every value, so the "model" path **silently degenerated to rules while still claiming a model had been consulted** — the worst kind of failure, because it looks like it worked.

### 3.3 The four outcomes, because prose cannot be asserted

Every response declares exactly one outcome, and the enum is what makes the brief's must-haves **testable**:

| Outcome | Meaning | Required fields |
|---|---|---|
| `quoted` | candidates satisfy all hard constraints | `reply`, `candidates[]`, `figures` |
| `clarified` | a needed detail is missing and would change the answer | `reply`, `questions[]` |
| `no_match` | constraints are complete but nothing satisfies them | `reply` |
| `refused` | the suitable item is out of stock or discontinued | `reply`, `refused[]` |

"Clarifying questions when ambiguous" and "a clear no exact match" are assertions on `outcome`, not judgements about prose. That is why the reply layer can be scored separately (below).

Decision rules R1–R7 map deterministically onto those four outcomes. The one worth reading closely is **R3 — missing quantity that changes the price**, because it is the assignment's central trap surfacing as a question:

> A question is asked only when the detail is **needed**, **absent**, **uninferable** and **answer-changing**. All four must hold.

Quantity is *not* asked when no budget was stated, because quantity 1 is then a fine default; and it is not asked when no tier could ever bring a price under the budget — because the question would not change the answer. At most two questions (`MAX_QUESTIONS`), because more reads as an interrogation.

`refused` is deliberately explicit that **no price is given**: *"I have not quoted it, because I can only price items you can actually order."* A refusal that quotes anyway is worse than a wrong match, because the customer can act on it.

### 3.4 The three guards

Run on every `quoted` reply before it is returned:

| Guard | Catches | On failure |
|---|---|---|
| `check_no_invented_products` | a `PL-XX-…` token not in the snapshot | **removed** and reported in `reply.errors` |
| `check_figures_match` | a monetary amount not in the allowed set | reported in `reply.errors` |
| `check_no_internal_ids` | a product described *only* by its SKU | flagged in `reply.warnings` |

`check_figures_match` catches the class of bug where prose drifts from arithmetic after an edit — the amount in the sentence and the amount in the breakdown come from the same object, but the guard proves it on every reply rather than trusting that.

Errors and warnings are both surfaced in `AssistantReply.as_dict()`, so a caller can **refuse to send a reply with errors** rather than trusting it.

### 3.5 The model client: five measured failures

Every one was observed on the configured endpoint, and each has a named remedy with a regression test in `tests/test_model.py`. They are recorded because each is silent — it looks like "the model had nothing to say" rather than "the client is misconfigured":

| # | Failure | Remedy |
|---|---|---|
| F1 | stray `data: [DONE]` on the **envelope** breaks `response.json()` | strip from `response.text` before `json.loads`, not from the content |
| F2 | reasoning eats the output budget; HTTP 200 with `content: null` | `DEFAULT_MAX_TOKENS = 2000`; `null` is **unavailable**, never an empty answer |
| F3 | `response_format` / `reasoning_effort` make it worse | neither is sent; JSON recovered by `extract_json_object()` |
| F4 | format instruction in the system prompt → prose replies | `USER_SUFFIX` appended to the **user** message |
| F5 | model answers in its own key vocabulary | `normalise_model_keys()` before the allow-list |

F2 deserves the emphasis: treating `content: null` as an empty answer would look like *"the model found no requirements"* — a silent, wrong answer that degrades to a clarification. It is treated as unavailability instead.

---

## 4. Pricing — pure code, integer satang, no model, no I/O

`pricing.py` + `money.py`. This layer is the reason the rest of the design can take the risks it takes. It has no I/O, no network, no clock, and no model client — **the pricing functions are pure**, which makes them exhaustively testable and makes "quotes work with no model" true by construction.

### 4.1 Money is integer satang, and rounding is explicit

```python
SATANG_PER_BAHT = 100
def round_half_up(value: Decimal) -> Decimal: ...   # the ONE rounding helper
```

All money is stored and computed as **integer satang**. Default rounding in Python is half-even, and the tax computation produces exact halves in realistic cases — a silent half-even result would disagree with the customer's expectation and be extremely hard to spot. So nothing relies on default float behaviour or a built-in rounding mode. There is a test that asserts half-up on an exact half value, which is precisely the case where the two differ.

Alternative rejected: floats with rounding at presentation time. Accumulated error is invisible until it produces a wrong total, and it makes exact test expectations fragile.

### 4.2 The pipeline, and the three lines that go wrong

```
unit_price(facts, qty):
    if sale_price:  return sale_price            # PR3: sale beats list AND every tier
    best = list_price                            # ← must be list, not None
    for tier sorted by min_qty:
        if qty >= tier.min_qty: best = tier.unit_price   # PR2: highest met tier
    return best

quote(lines):
    subtotal = Σ unit_price(sku, qty) × qty      # PR4
    delivery = 0 if subtotal >= 3000.00 else 150.00    # per ORDER, not per line
    vat      = round_half_up((subtotal + delivery) × 7 / 100)   # PR5
    total    = subtotal + delivery + vat
```

Each of the three error-prone lines has a **named test**, because each is invisible on the obvious example:

| Line | Failure if wrong | Detection |
|---|---|---|
| `best = list_price` | items whose lowest tier is 5+ or 10+ return **nothing** at qty 1–4 | unit test below the lowest tier |
| delivery on the summed subtotal | a mixed order pays delivery **twice** | multi-item case where neither line clears the threshold alone |
| VAT on `subtotal + delivery` | total **understated** by a fixed amount | small-order case where VAT-on-subtotal-only is distinguishable |

`sale_price` returning first is PR3, and it is nearly invisible in the markup — one item in the whole catalog (`PL-PR-LTR-GL-170-40`, 299.00 → 259.00), with volume pricing suppressed. A sale item and a volume discount are never combined.

The delivery threshold is `>=`, not `>`, and the difference is reachable on real data: `PL-CP-A4-80-ECO` at 25 × 120.00 is exactly 3,000.00, so a strict `>` charges 150.00 on a real order. The VAT-basis error understates the total by exactly 7% of the delivery fee (10.50 on a 150.00 fee), which is why the small-order case detects it.

`applied_tier()` exists so the reply can state provenance — `"20+ tier (list 265.00)"` — which is what makes a quote **forwardable rather than suspicious**. The phrase in the reply and the number in the breakdown come from the same object, so they cannot disagree.

### 4.3 The budget comparison — the assignment's central trap

PR6 says compare the budget with the unit price **at the requested quantity**:

```python
check_budget(facts, quantity, budget) -> unit_price(facts, quantity) <= budget
```

For `PL-PR-LTR-GL-130-40` (list 265.00, 20+ tier 233.20):

| Quantity | Unit price | vs "under 250 a pack" |
|---|---|---|
| 1 | 265.00 | **fails** |
| 20 | 233.20 | **passes** |

The brief's own example — *"under 250 a pack, 20 packs"* — puts the budget **before** the quantity, and the verdict **flips** between them. Comparing against the list price gets the brief's own example product wrong. A test asserts both halves: that the naive comparison returns `False` and the correct one returns `True`.

The bound is **inclusive** (`<=`, not `<`) because PR6 says "maximum price per pack" — `250.00` exactly is within budget, and both `250.00` and `71.99`-against-`72.00` are tested.

`BudgetCheck.basis` carries `"per pack, before VAT"` explicitly, because PR7 requires the reply to **state which assumption was applied** when the customer did not say. A budget verdict without its basis is not actionable.

### 4.4 One pricing path, every caller

The API has two entry points for exactly this reason:

| Endpoint | Calls the model |
|---|---|
| `POST /api/ask` | yes (with rule fallback) |
| `POST /api/quote` | **no** |
| `POST /api/quote/lines` | **no** |

`/quote` accepts structured criteria and never touches the model; `/ask` accepts free text and does. **Both share the one `quote()` implementation**, as do the assistant, the CLI, and the evaluation harness. So when a case fails, the entry point used tells you **which layer is at fault** — interpretation or pricing — and a pricing bug cannot be hidden behind an interpretation success. It also means the pricing tests and most of the evaluation set run with no model and no network.

---

## 5. Why the plan goes in this order

`../pre/ANALYZE_01.md` §8 planned a three-day build against a six-hour brief; the brief scores *"good judgment about scope"* explicitly, so the ordering is itself a design decision and it was defended in the proposal before any code existed.

### 5.1 Pricing before agent

> If the agent slips, a correct, tested, CLI-drivable engine still stands.

This is the single most consequential ordering choice. It follows directly from §0: the model is not in the correctness path, so the correctness path must be *finished first*. A weaker ordering would have built the agent first — it is the visible, demoable part — and the deterministic core would then be the fallback, which is exactly backwards from the guarantee the brief scores.

Practically, it also means **every interpretation failure is contained**. When `interpret()` returns nothing usable, the reply is still a correct clarification or a correct quote from the rules. The system is never *unable to answer*; it is at worst *unable to interpret*, which is a much smaller failure with a disclosed name.

### 5.2 Core before extras, Tier 1 gates Tier 2

The build is split into two explicit tiers (`tasks.md` groups 1–9 are Tier 1; group 10 is Tier 2), with one rule:

> **Never trade a Tier 1 item for a Tier 2 one.** Do not start Tier 2 while any Tier 1 task is unfinished.

Tier 1 is the six-hour core and is a **complete submission on its own**: ingestion, pricing, search, assistant, API, refresh, evaluation, README, customer summary. Tier 2 is four separable extras — semantic tiebreak, mutated-site refresh harness, observability, conversation memory — each **independently droppable with no Tier 1 dependency on it**.

Every Tier 2 addition is therefore post-hoc and reversible. That is what makes the semantic tiebreak defensible as a *tiebreak*: it was added to a system that already worked, it was measured (3 of 28 reordered, zero regressions), and if it had regressed anything it would have been dropped without touching Tier 1.

### 5.3 Inside Tier 1, the order is forced by dependency

```
1  scaffold
2  pricing engine        ← highest-value work, and nothing depends on the model
3  catalog ingestion      ← requires pricing types (Money, PriceFacts) to store into
4  product search         ← requires the catalog to filter
5  sales assistant        ← requires search + interpretation
6  quote API              ← requires all of the above
7  refresh and diff       ← requires a catalog, and is what proves the crawl reproducible
8  evaluation harness     ← requires the whole path, and measures it
9  submission docs        ← written last because they document what exists
10 Tier 2 extras
11 integration verification
```

Pricing sits at step 2, ahead of ingestion, because it is the only layer whose **specification is complete before any data exists** — the rules come from the brief (PR1–PR8), not from the site. Building it first means it is written against the spec and tested with hand-computed fixtures, and only then exercised against real data. Building it after ingestion would tempt it toward "whatever the data happens to contain".

Evaluation at step 8, not earlier, because **a harness that runs before the path exists measures nothing**. Its placement is what makes it an honest measurement rather than a target.

### 5.4 Why the evaluation is built to fail

The harness (`evaluate.py`) is the artifact the brief explicitly asks for, and three properties matter more than the score:

1. **Expected totals are recomputed, never transcribed.** `cases.json` records only SKUs and quantities; `recompute_totals()` derives every figure from the committed catalog by integer arithmetic **in a code path that does not call `quote()`** — asserted by AST inspection (`test_recompute_does_not_call_the_pricing_engine`). If the harness called `quote()` to check `quote()`, a pricing bug would agree with itself and the run would report a clean sweep forever.
2. **Four axes are scored separately** — `("retrieval", "match", "pricing", "reply")` — so a correct total cannot mask a wrong product set. A test pins "right price, wrong product" as a real recorded case.
3. **Failing cases stay in the results.** The brief asks for *"cases where your system fails"*; a clean sweep is less credible than a documented failure.

This is the same principle as §1.3's review floor and §2.5's by-product justification: **the system's honesty is built into its structure, not its claims.** A test that cannot fail, a metric that cannot move, and a ladder that drops pages all look identical to working — until the day they matter.

---

## 6. What was added after the plan, and why it is safe

Four Tier 2 changes were shipped after Tier 1, and the archive holds each as its own OpenSpec change with its own specs. The pattern is identical in all four: **each is droppable, each is measured, each has a negative control.**

| Change | What it adds | How it stays safe |
|---|---|---|
| `add-semantic-tiebreak` | conditional similarity term in the rank key | membership invariant asserted across all 28 cases; unconfigured key pinned as an exact tuple |
| `add-mutated-site-refresh-harness` | builds its own mutated v2 site, verifies 12 injected changes | the generator's own honesty is tested first (byte-identical copy, deterministic, unknown kind rejected) |
| `add-observability` | request records, five derived measures | every metric is shown **able to fail**; metrics derived, never counted — asserted by AST |
| `add-conversation-memory` | carry requirements across turns | merge over typed `Criteria` only; the model never sees the transcript; single-turn path pinned by digest |

The conversation layer is worth naming specifically, because it is the one place where a reply depends on an earlier request — the one place the §0 guarantee could weaken. It does not, because **the merge happens after interpretation, over typed `Criteria`, and only the current turn's text ever reaches an interpreter.** Every constraint in a merged result is traceable to a turn that stated it. The alternative — letting the model see the transcript — would handle more sentences correctly and would make every wrong answer unfalsifiable. That trade was made in favour of traceability.

And because conversation memory touched the single-turn path, there is a **SHA-256 digest of every case's `{outcome, text}` recorded from the commit before the feature existed** (`tests/test_single_turn_unchanged.py`). If that test ever fails, the question is not "update the digest" — it is *"which reply changed, and why"*.

Three defects found after that feature shipped (A12, A13, A14 in `BUG.md`) followed the register's own rule: **a bug becomes a test before it becomes a fix**. Each was registered before being fixed, each arrived with a test *and* a falsification check — the fix was reverted, the new test and eval case were confirmed to fail, and the fix restored. A guard that has never been seen to fail is a guess.

---

## 7. The system in one paragraph

A sequential 1 req/s crawler reads 103 requests from an HTTP-served site and hands each page to an extraction ladder that recognises four markup shapes by structure and files anything it cannot parse as a review row rather than dropping it. Normalisation turns four weight spellings, three size spellings and a decorative unit word into one canonical vocabulary, and a DuckDB snapshot is rebuilt and atomically swapped so a failed ingest cannot damage a working catalog. Search filters on hard constraints with not-applicable semantics, ranks by a total order that ends in the SKU so two runs can never disagree, and emits its justifications as a by-product of filtering. Interpretation converts free text into typed criteria on either a model path or a rule path, discloses which, and can produce no price, no SKU and no prose. Pricing is pure integer-satang code with one half-up rounding helper, comparing a budget at the requested quantity because that is the only place the verdict is correct. Every response is one of four declared outcomes, three guards check every quoted reply, and a harness scores four axes separately with expectations recomputed from source rather than transcribed. The order of construction — pricing before agent, core before extras, evaluation last — is what makes the guarantees structural rather than claimed.
