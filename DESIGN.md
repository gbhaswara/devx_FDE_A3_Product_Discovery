# DESIGN.md — PaperLane Product Discovery

Product and interaction design. Behavioural requirements are in `openspec/specs/` (the eleven main specs) and the change that introduced each is under `openspec/changes/archive/`; system structure is in `ARCHITECTURE.md`.

## Who this is for

Two users, with different needs from the same system.

**The salesperson** (primary). Answers catalog questions in a chat channel all day. They need a reply they can forward to a customer without rewriting it, and they need to trust the number in it. They are not going to check the arithmetic. If the system is wrong once and they forward it, they stop using it.

**The customer** (secondary, via the salesperson). Wrote something like *"We need letter-size flyers, one side, colour, under 250 a pack, 20 packs."* They are describing a job they need doing, not catalog attributes. They will not know the site's vocabulary, and they may describe the same requirement in three different ways.

The business owner is a third audience, but they read `CUSTOMER_SUMMARY.md`, not the product.

## The design problem

The brief's example request contains five constraints and one quantity:

```
"We need letter-size flyers, one side, colour, under 250 a pack, 20 packs."
        size          sides    colour      budget            qty
```

Four of those six are things a customer says naturally and the catalog stores awkwardly. The fifth — the budget — is the interesting one, because **whether it is met depends on the quantity**, and the quantity is stated last. A system that checks the budget against the list price gets the answer wrong on the very example the brief provides.

That single dependency drives most of the interaction design below.

## Reply structure

Every successful reply has the same four parts, in this order. The order is deliberate: the answer first, then the justification, then the cost, then the caveat.

```
1  THE ANSWER        what matches, cheapest first
2  WHY IT MATCHES    per product, per constraint, requested vs actual
3  THE COST          unit, qty, subtotal, delivery, VAT, total
4  THE CAVEAT        budget verdict, assumption used, or what was relaxed
```

```
Here are three options that fit your request.

1. Digital Flyers Letter — Gloss 130gsm, single-sided, full colour
   PL-PR-LTR-GL-130-40 · pack of 100
   Matches:  size letter ✓ · single-sided ✓ · full colour ✓
             under 250/pack ✓ — 233.20 at 20 packs (20+ tier; list 265.00)

   20 packs × 233.20        =  4,664.00
   Delivery                    0.00   (order over 3,000)
   VAT 7%                    326.48
   ────────────────────────────────────
   Total                     4,990.48

   Budget compared per pack, before VAT — 233.20 against your 250 limit.
```

Why this shape:

- **The constraint list is the "why they match" requirement, made literal.** It is not prose about the system's reasoning; it is the filter's own record of what it checked. A salesperson can scan it and see the one number that might be wrong.
- **`20+ tier; list 265.00` is shown** because a customer who later sees the list price on the website will otherwise think they were overcharged. Explaining the discount is what makes the reply forwardable.
- **The budget line names its basis** ("before VAT") because PR7 requires stating the assumption, and because a customer who meant *including* VAT needs to know they should say so.
- **Total is last and separated** because it is the number that gets quoted, and it should not be confusable with the subtotal.

## The four outcomes as designed states

Each is a distinct screen, not a variation of the same one. This is the core interaction decision: the system never blurs "here is your answer" with "I could not answer". They ship as `quoted`, `clarified`, `no_match` and `refused`; the names below are the ones this document used while they were being designed, and they map one to one.

### `quoted` (designed as `ok`) — matched

As above. One to five products, cheapest first.

### `clarified` (designed as `clarify`) — one question, at most two

```
I can find that. Two things I need to get the price right:

  1  How many packs?  — 20 packs is 233.20 each, 4 packs is 265.00 each,
     so the budget answer changes with the quantity.
  2  Which side — single or double?

Everything else I have: letter, colour, under 250 a pack.
```

Design rules:

- **Ask only when the answer changes.** The prompt shows *why* it is asking ("so the budget answer changes"), which turns an interruption into a reason to answer.
- **Never ask about something that does not apply.** Asking a plain-paper request "single or double sided?" would reveal that the system does not understand its own catalog.
- **At most two questions.** More than two and the customer abandons the chat and phones instead.
- **Echo what was understood.** The last line proves the system captured the rest, so the customer is correcting one thing rather than re-typing everything.

### `no_match` — honest, with the relaxation named

```
Nothing in the catalog is under 60 a pack — the cheapest thing we sell is 72.00.

The closest I can do, and what I had to relax:

  PL-CP-A5-80   A5 copy paper 80gsm — 500 sheets per ream
    72.00 per ream (10+ tier: 68.40)
    relaxed: budget — 12.00 over your 60 limit

  If a smaller pack size would help, the A5 flyers start at 79.00 a pack.
```

Design rules:

- **State the cheapest thing that exists**, so "no match" is informative rather than a dead end. Here the catalog-wide cheapest is an A5 copy-paper ream at 72.00, and the cheapest *flyer* is 79.00 — worth distinguishing, because "cheapest" depends on which product family the customer was asking about.
- **Name the relaxed constraint per alternative.** "Closest alternatives" is meaningless without saying closest *how*.
- **Quantify the gap** ("12.00 over"), because a customer can decide about 12 baht; they cannot decide about "over budget".
- **Never present an alternative as a match.** The label says `relaxed:`, not a tick.

### `refused` — unavailable, with the reason that matters

```
That one is out of stock — Heritage Ivory A4 100gsm (PL-CL-A4-100-IVY).
Expected back 20 November 2026.

In stock now, closest to it:
  PL-CL-A4-90-CRM   Heritage Cream A4 90gsm · 250 sheets per pack · 152.00
```

Design rules:

- **Distinguish out-of-stock from discontinued.** One has a date and is worth waiting for; the other is never coming back.
- **Give the restock date** when the site states it, because "out of stock" with no date is a lost sale.
- **Always offer the nearest available alternative**, so a refusal is still a sales opportunity.

## Why the price breakdown is the product

The brief scores "business sense: replies a salesperson would be proud to send." The breakdown is where that is won or lost, and it is also where trust is built or destroyed.

Three specific choices:

**Delivery is a line, not a footnote.** `0.00 (order over 3,000)` tells the customer they saved 150 baht and why. A hidden delivery charge is the single most common reason a quoted total gets disputed.

**VAT is shown as an amount, not a rate.** `VAT 7% 326.48` rather than `+VAT`. The customer is going to add up the total themselves; if the arithmetic does not visibly work, the quote is not trusted.

**Discount provenance is always stated.** Either `20+ tier` or `sale price — no volume discount on sale items`. Both are cases where the customer could otherwise compare against the website and conclude they were misled.

## Interaction with the model

The model is used for one thing: turning a sentence into structured criteria. It is deliberately not in the reply path.

```
customer text
     |
     v
[ model: text -> criteria ]        <- only job; validated before use
     |  (on failure: rules -> criteria)
     v
[ validate criteria against catalog vocabulary ]
     |
     v
[ deterministic: filter -> rank -> price -> justify ]
     |
     v
[ reply prose assembled from computed values ]
```

Consequences that are visible in the product:

- **The product list is never wrong in a way the model caused.** Products come from the filter.
- **Every figure in the reply text is inserted from the computed result**, not generated. The number in the sentence and the number in the breakdown are the same object.
- **If the model is down, the product still answers.** Rule interpretation covers the common shapes; anything it cannot parse becomes a `clarified`, which is a normal state, not an error.

The trade-off accepted: replies read slightly more templated than a fully model-composed answer. In exchange, a wrong price cannot be blamed on the model, and a model outage is a quality dip rather than an outage.

## Deliberate omissions

Each of these was considered and cut. They are listed because a reviewer will ask.

| Omitted | Why |
|---|---|
| Product images | The catalog's value is in attributes and price, not presentation. Images would add a crawler path and storage for no scored benefit. |
| A cart / checkout | The brief asks for a quote, not an order. Quoting is where the errors are; ordering is out of scope. |
| Rich formatting, charts, PDF export | The reply is meant to be forwarded as text into a chat channel. |
| Streaming responses | Replies are fast because pricing is local. Streaming would add complexity to hide a latency problem that does not exist. |
| A customer-facing UI | The user is a salesperson. The interface is a working tool, not a storefront. |

**Conversation memory was on this list and is not any more.** It was cut during
planning — *"single-turn plus an explicit clarification is more reliable than
half-built memory"* — and that reasoning is right about a *half-built* memory. It
was wrong about the capability: the second most natural thing a customer says is
a refinement, and the assistant could not hear it. It was built after the scored
work was complete, conservatively: a turn continues only when it names no new
subject, the merge is over typed criteria rather than the transcript, and every
continued reply says what it remembered. See
[`docs/conversation-memory.md`](devx_FDE_A3_Product_Discovery/docs/conversation-memory.md).

## Accessibility of the answer itself

The reply is plain text with aligned columns, because it is designed to survive being pasted into LINE or WhatsApp. That constraint rules out tables, markdown emphasis, and colour — all of which render badly or not at all in a chat client.

This is why the breakdown uses aligned monospace-ish columns and a horizontal rule rather than a table: the same string must be readable in a browser, in a chat bubble, and in a terminal.
