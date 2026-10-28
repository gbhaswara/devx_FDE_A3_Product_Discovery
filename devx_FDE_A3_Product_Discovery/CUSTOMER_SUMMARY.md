# PaperLane: a product assistant for your sales team

## What it does

A customer writes *"I need letter-size flyers, one side, full colour, under 250 a
pack, 20 packs"* — in their own words, the way they would say it on the phone.
The assistant replies with the right product, the right price, and why it matches,
broken down as goods, delivery, VAT and total. It reads your existing website: no
new catalogue, no data entry.

## How well it works

**Prices are exact to the satang**, including volume discounts, sale items, the
150 baht delivery charge (free from 3,000) and 7% VAT. The arithmetic is ordinary
tested code: the model reads the customer's words but cannot produce a number,
choose a product, or write a total.

**It understands trade shorthand** — "4/4" for double-sided full colour, "24 lb"
for paper weight, "8½ × 11" and "letter" for the same size — and it will not offer
an out-of-stock item as available, on any endpoint. It refuses and gives the
restock date.

**It checks your budget against the number you meant.** A ceiling stated per pack
before VAT is compared before VAT; say "including VAT" and it is compared against
the VAT-inclusive price, and the reply names which assumption it used.

**It knows when not to answer.** It quotes; it asks when a missing detail would
change the answer; it says "nothing matches" and shows labelled alternatives; it
refuses an unavailable item.

## What it cannot do

- **Conversation is conservative.** "Make that 40 packs" continues the previous
  request, and the reply says what it remembered; "the cheaper one" alone is a new
  question, not a guess. The model never sees the conversation, so every
  requirement traces to something the customer said.
- **28 lb and 32 lb are unproven.** The site stocks neither, so those conversions
  are implemented but never checked against a real product; 20 lb and 24 lb are
  verified.
- **A vague "pack" is stated, not resolved.** When products come in reams, pads and
  packs of different sizes, it says which basis it used instead of quietly assuming
  one.
- **It does not track stock levels.** Your site says in stock, out of stock or
  discontinued, but never how many are left, so a request for 50 packs is quoted
  even if only 45 remain. It will not offer an out-of-stock item, but the count is
  a fulfilment question it cannot see.
- **Not ready for the open internet.** No login and no protection against heavy
  traffic; run it on a laptop or behind your own network. It reads one supplier; a
  second site needs additional work.

## What to do next

1. **Send twenty real requests.** The ones it gets wrong are the most valuable
   thing you can give us: each becomes a permanent test so it cannot regress.
2. **Decide what "good enough" means commercially.** It prices correctly today;
   the useful argument is which requests matter most.
3. **Then, in this order:** a second supplier; alerts when prices move sharply; a
   way for a salesperson to correct a quote so the correction is learned.

On a test copy of your site we plant twelve changes; the refresh report catches
twelve of twelve, so the report can be trusted when your real site moves.

The pricing engine and the search that decide a customer's total are finished;
what remains is presentation and delivery.
