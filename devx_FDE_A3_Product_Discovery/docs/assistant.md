# Assistant

How a request becomes a reply: which path interprets it, which of the four
outcomes it reaches, and what guards run before the text is returned.

Code: `src/paperlane/interpret.py`, `model.py`, `assistant.py`, `criteria.py`,
`search.py`. Tests: `tests/test_assistant.py`, `test_model.py`,
`test_aliases.py`, `test_search.py`.

---

## The boundary

```
request text
    │
    ├─ model client ──┐        (criteria ONLY — no prices, no SKUs, no prose)
    │                 ├─→ Criteria ─→ validate ─→ search ─→ quote
    └─ rule parser ───┘                              │
                                                     ↓
                                            reply rendered here
```

The model's entire contribution is **criteria**. It never sees a price, never
returns one, and never writes the reply. The reply is rendered from
deterministic values in `assistant.py`. That is a structural guarantee, not a
prompt instruction: there is no field in `Criteria` for a price to land in, and
`ALLOWED_CRITERIA_KEYS` has no price, SKU, or total key.

---

## Path selection and disclosure

`interpret(text, client)` returns an `Interpretation` carrying `path`:

| `path` | Meaning |
|---|---|
| `model` | the model answered and the rules added nothing |
| `mixed` | both contributed; model values won where present |
| `rules` | the model was unavailable, unconfigured, or returned nothing usable |

Disclosure is not cosmetic. A salesperson needs to know whether requirements
were read by a model or by a rule, because they fail differently: the rules are
predictable and narrow, the model is flexible and occasionally wrong.

**The fallback is not a degraded path.** `interpret_rules()` handles the common
request shapes completely and needs no network. Every test in
`tests/test_assistant.py` runs through it. The system answers with no model
configured at all — that is asserted, not hoped for.

### Why model values are re-resolved, never trusted

Measured against the live endpoint, this model returns correct *meanings* in the
wrong *vocabulary*:

| Model returns | Catalog stores | Resolved by |
|---|---|---|
| `"size": "letter"` | `LTR` | `resolve_size` |
| `"category": "flyers"` | `Flyer printing` | `resolve_category` |
| `"sides": "one-sided"` | `single` | `normalise_sides` |
| `"colour": "colour"` | *ambiguous* | becomes a question |

Passing `"LETTER"` straight into `Criteria.size_code` produced a value that
failed validation, which discarded an otherwise perfect interpretation. Every
model value therefore goes through the same alias resolvers the rules use.

---

## The decision rules

Each rule below names the outcome it produces. They are evaluated in order, and
the first match wins.

### R1 — A stated requirement that could not be mapped → `clarified`

**Trigger:** a size was named that the catalog does not stock (`B5`), so it could
not become a constraint.
**Why:** silently dropping it would quote A4 to a customer who asked for B5.
**Produces:** `clarified`, naming the sizes the catalog carries.

### R1b — More than one product in one request → `clarified`

**Trigger:** two clauses that each name a product — *"A4 copy paper and A4 card"* —
or one that names a product and one that describes another without naming it
(*"10 packs of the 130gsm"*).
**Why:** the rule parser reads each field from the whole string, so a compound
request merged into a phantom product (*"A4 80gsm copy paper **and** A4 gloss
flyers"* became an A4 80 gsm **gloss** copy paper, and answered `no_match` for
an item in stock) or quoted the first item and discarded the second with no
sentence saying so. `BUG.md` A29.
**Produces:** `clarified`, asking which item to price first. The merged criteria
are deliberately **not** restated in the reply — they are the phantom this rule
exists to avoid. Multi-item pricing lives at `POST /api/quote/lines`.

### R2 — Ambiguous "colour" → `clarified`

**Trigger:** "colour" with no noun disambiguating paper shade from print mode.
**Why:** the two senses select disjoint item sets; a guess returns a completely
different quote.
**Produces:** `clarified`, asking which sense was meant.

### R3 — Missing quantity that changes the price → `clarified`

**Trigger:** a budget was stated, no quantity, and at least one candidate has a
volume tier that could bring its unit price under the budget.
**Why:** the budget is checked at the requested quantity, so quantity decides
whether anything qualifies.
**Produces:** `clarified`, asking how many packs.

All four conditions must hold: the detail is **needed**, **absent**,
**uninferable** and **answer-changing**. A question failing any of them is not
asked. Quantity is *not* asked when no budget was stated, because quantity 1 is
then a fine default — and it is not asked when no tier could ever help.

At most **two** questions per reply (`MAX_QUESTIONS`). More reads as an
interrogation.

### R4 — Nothing understood at all → `clarified`

**Trigger:** `Criteria.has_any_constraint()` is false.
**Produces:** `clarified`, asking what the customer is looking for.

### R5 — Matched but unavailable → `refused`

**Trigger:** items satisfy every requirement, but none is in stock.
**Why:** they must be neither silently omitted (the customer would not know the
product exists) nor silently offered (they would get a quote they cannot buy).
**Produces:** `refused`, distinguishing:
* **out of stock** — with the restock date when the page states one
  (`PL-CL-A4-100-IVY`, back 20 November 2026)
* **discontinued** — permanently gone, no date offered

The refusal is explicit that no price is given: *"I have not quoted it, because I
can only price items you can actually order."*

The refusal depends on **status, not quantity**: the site publishes no count on
hand, so an out-of-stock item is refused whatever the requested quantity, and an
in-stock item is never refused for being a large order. See
[`ingestion.md`](ingestion.md).

### R6 — Nothing satisfies every requirement → `no_match`

**Trigger:** no item passes all hard constraints and none is merely unavailable.
**Produces:** `no_match`. If dropping one requirement yields candidates, they are
offered **separately** and labelled with the requirement relaxed
(`RELAXATION_ORDER = budget, finish, weight, sides, colour, size`). If nothing is
close, the reply says so and asks, rather than offering something unrelated.

Alternatives are never presented as matches: `matches` is empty and `relaxed`
names what was dropped.

### R7 — Everything satisfied → `quoted`

**Produces:** `quoted`, containing:
* the best match by catalog **name** and identifier
* the unit price, the unit it is sold in, and where the price came from
* one justification line per satisfied requirement
* the budget verdict, when a budget was stated
* up to three other options that also match
* a full breakdown: lines, subtotal, delivery, VAT, total
* the free-delivery threshold **and the shortfall**, when delivery is charged
* the next volume tier, when buying it would cost **less** (see below)

### Delivery is never a surprise

The threshold is named in both branches. Naming it only when delivery is already
free publishes the rule to the customer it costs nothing and withholds it from
the one paying 150.00 — and a forwarded quote carries no page banner (`BUG.md`
A27):

```
  Delivery      150.00  (free from 3,000.00 — 2,100.00 more)
```

The shortfall is one subtraction of two figures `pricing` produced, and it is
added to the figures guard's allowed set. An order that clears the threshold
says nothing about being short, because nothing is.

### A larger order that costs less is named

A volume tier is a step function: 19 packs at 202.10 is 4,108.69, and 20 packs
at 189.20 is 4,048.88. Quoting the first number silently invites the customer to
find the second themselves, so the reply states it (`BUG.md` A30):

```
20 packs would come to 4,048.88 — 59.81 less than this order.
```

The tier named is **one step up** — the smallest published `min_qty` above what
was asked for — re-priced through `pricing.quote`, and printed only when that
total is lower. A "best quantity" optimiser was rejected: it would have to
justify a quantity the customer did not ask for. The two amounts are added to
the figures guard's allowed set, because they are computed, never paraphrased.

---

## The reply contract

| Field | Source | Never |
|---|---|---|
| product name | `products.name` (catalog) | invented |
| identifier | `products.sku` | the primary description |
| unit price | `pricing.unit_price()` | computed in prose |
| justification | `MatchReason` records from filtering | composed afterwards |
| discount | `Candidate.discount_note` | guessed |
| totals | `pricing.quote()` | re-derived |

### Where the discount comes from

`discount_note` names exactly one of:

* `sale price (no volume discount on sale items)` — a sale item has no tiers
* `20+ tier (list 265.00)` — the tier applied, with the list price for contrast
* `list price` — no tier applied

The phrase in the reply and the number in the breakdown come from the same
object, so they cannot disagree.

### The unit

`pack of 500 sheets`, `pack of 100 sheets`, `pack of 50 sheets` — taken from
`pack_sheets`, never from `unit_word`. `pl-cl-a4-80-pyl.html` says
`195.00 THB / ream` in its price box while its own table says
`Pack contents: 500 sheets`; the words are unreliable and the count is not.

---

## The three guards

Run on every `quoted` reply, before it is returned.

### G1 — No invented products (5.8)

```python
check_no_invented_products(text, known_skus) -> (text, errors)
```

Every `PL-XX-…`-shaped token in the reply must exist in the current snapshot.
An unknown one is **removed and reported** in `reply.errors`, not returned.

### G2 — Stated figures match computed figures (5.9)

```python
check_figures_match(text, allowed) -> (text, errors)
```

Every monetary amount in the reply text must be in `allowed` — the set the
pricing layer produced, including the unit prices of the other options quoted.
A stray amount is a discrepancy, recorded in `reply.errors`.

This catches the class of bug where prose drifts from arithmetic after an edit.

### G3 — No internal identifier as the description (5.10)

```python
check_no_internal_ids(text, skus_in_reply) -> (text, warnings)
```

Each line mentioning a SKU must carry a name alongside it. A line that describes
a product *only* by its identifier is flagged in `reply.warnings`.

Errors and warnings are both surfaced in `AssistantReply.as_dict()`, so a caller
can refuse to send a reply with errors rather than trusting it.

---

## The model client: four measured failures

Every one of these was observed on the configured endpoint (`9router`,
`9inference`, which resolves to `deepseek-v4.1-flash`), and each has a named
remedy with a regression test in `tests/test_model.py`.

### F1 — A stray terminator, on the **envelope**

The body is `{...}data: [DONE]\n\n`. `response.json()` raises
`Extra data: line 1 column N` on an otherwise perfectly valid response.

**Remedy:** `strip_terminator()` is applied to `response.text` **before**
`json.loads`. The first implementation stripped it only from the message
content, which never fired — the failure happens one layer earlier.

### F2 — Reasoning consumes the output budget

With `max_tokens` below roughly 1000, every output token went to reasoning and
the response was HTTP 200 with `content: null`.

**Remedy:** `DEFAULT_MAX_TOKENS = 2000`, and `content: null` is treated as
**unavailable**, never as an empty answer. Treating it as empty would look like
"the model found no requirements" — a silent, wrong answer.

### F3 — Structured-output flags make it worse

`response_format={"type": "json_object"}` produced empty content.
`reasoning_effort="none"` was ignored.

**Remedy:** neither is sent. The JSON is recovered from the response text by
`extract_json_object()`, which tries the whole body, then a fenced block, then
the outermost brace-balanced span (respecting string literals).

### F4 — The format instruction must be in the **user** message

With "return only a JSON object" in the system prompt, this model replied in
prose on every attempt (three different prompt formulations, all prose). Moved
into the user turn, it returns a bare object every time.

**Remedy:** `USER_SUFFIX` is appended to the user message.

### F5 — The model answers in its own key vocabulary

Asked for `weight_gsm` it returns `gsm`; for `quantity`, `packs`; for
`budget_per_unit`, `per_pack_constraint`; for `category`, `product`.

**Remedy:** `normalise_model_keys()` translates the observed keys onto canonical
names before the allow-list runs. Without it the allow-list discarded every
value the model produced, so the "model" path silently degenerated to rules while
still claiming a model had been consulted — the worst kind of failure, because
it looks like it worked.

Noise keys the model emits about its own uncertainty (`status`,
`clarification`, `required_details`, `confidence`) are dropped: the assistant
decides when to clarify from the criteria and the catalog, not from the model's
self-assessment.

---

## Verified live

Against the served catalog with the real endpoint:

| Request | Path | Criteria | Outcome |
|---|---|---|---|
| letter-size flyers, one side, colour, under 250 a pack, 20 packs | mixed | Flyer printing / LTR / single / CMYK / 20 / 250.00 | `quoted`, 0 errors |
| A4 copy paper, 80 gsm, 20 reams | mixed | Copy paper / A4 / 80 / 20 | `quoted`, 0 errors |
| ivory A4 paper | rules | A4 / ivory | `refused` |
| A5 card 200 gsm | mixed | Card and photo paper / A5 / 200 | `no_match` |
| hello there | rules | — | `clarified` |

The `rules` path for *"ivory A4 paper"* is correct disclosure, not a failure: the
model returned nothing usable for that request, so the rules answered.

---

## What this layer does not do

* **No price is ever produced by a model.** There is no field for one.
* **No reply is written by a model.** The prose is rendered from computed values.
* **No invented product survives.** Guard G1 removes and reports it.
* **No unavailable item is quoted.** It is refused with its distinguishing detail.
* **No question is asked that cannot change the answer.** All four conditions in
  R3 must hold.
* **No silent fallback.** `path` says which interpreter ran, every time.
