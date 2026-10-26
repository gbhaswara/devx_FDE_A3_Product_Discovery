# PaperLane: a product assistant for your sales team

## What it does

A customer writes *"I need letter-size flyers, one side, full colour, under 250 a
pack, 20 packs"* — in their own words, the way they would say it on the phone.

The assistant replies with the right product, the right price, and a short
explanation of why it matches. It breaks the price down the way your invoices do:
goods, delivery, VAT, total.

It reads your existing website. There is no new catalogue to maintain and no data
entry — it reads the same pages your customers read.

## How well it works

**Prices are exact.** Every total is correct to the satang, including the awkward
cases: volume discounts, sale items, delivery charges and VAT.

**It finds the right product.** It understands trade shorthand — "4/4" for
double-sided full colour, "24 lb" for paper weight, "8½ × 11" and "letter" for the
same size — and it will not offer something out of stock as though it were
available.

**It knows when not to answer.** Four things can happen, and all four are useful:

- **It quotes** — a product, a price and a reason.
- **It asks** — when something essential is missing and would change the answer.
- **It says nothing matches** — and shows the closest options, labelled as not
  matching.
- **It refuses** — when the product matches but is out of stock, with the
  restock date, rather than pretending the item does not exist.

**It never invents a price.** The model reads the customer's words. All arithmetic
is done by ordinary code, tested on its own. The model cannot produce a number,
choose a product, or write a total into a reply.

## What it cannot do

**It cannot hold a conversation.** Every request stands alone. "Make that 40 packs
instead" is not understood as a follow-up.

**Two weight conversions are unproven.** The site stocks no 28 lb or 32 lb paper,
so those conversions are implemented but never checked against a real product. The
20 lb and 24 lb ones are verified.

**It cannot resolve a vague "pack".** When your products are sold in reams, pads
and packs of different sizes, the assistant says which basis it used instead of
quietly assuming one. That is honest, but it is not the same as knowing what the
customer meant.

**It is not ready for the open internet.** No login, no protection against heavy
traffic. It is built to run on a laptop or behind your own network.

**It reads one supplier.** A second site needs additional work.

## What to do next

1. **Try it on your real questions.** Send it twenty requests your team actually
   gets. The ones it gets wrong are the most valuable thing you can give us — each
   becomes a permanent test so it cannot regress.
2. **Decide what "good enough" means commercially.** It answers correctly today;
   the argument worth having is about which requests matter most.
3. **Then, in this order:** a second supplier; alerts when prices move sharply;
   let a salesperson correct a quote so the correction is learned.

## The honest summary

A working assistant that prices accurately and explains itself, built on the site
you already have. It is strongest on clear, specific requests and honest about its
limits — it asks rather than guesses, and says "nothing matches" rather than
inventing something. What it is not yet: a system that holds a conversation, or one
ready for unattended public use. Both are a week of work, not a rewrite.

## What we left out

We built the core first — reading your site, pricing accurately, answering
correctly. That is complete and tested. Three extras were deliberately held back:

- **A test copy of your site with deliberate faults**, to prove the refresh catches
  a missing product or a wrong price. The change report already works; this is the
  rehearsal against known-bad input.
- **A smarter "closest match" search** for requests phrased entirely in paraphrase,
  with no size, weight or trade term to go on.
- **A dashboard and alerts**, turning the records we already keep into answers to
  "how often did we have to ask instead of quote?".

All three are small additions. We spent the time on pricing accuracy instead, which
is what your customers notice.
