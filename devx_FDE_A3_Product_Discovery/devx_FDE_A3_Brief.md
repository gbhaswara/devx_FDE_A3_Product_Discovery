# A3 Product Discovery

Level: Hard. Plan for about 6 hours; scope it.

## The customer

PaperLane sells paper and flyer printing to offices in Bangkok. Most
orders start as a chat message such as "We need letter-size flyers, one
side, colour, under 250 a pack, 20 packs." Sales staff answer by hand.
PaperLane wants an assistant that understands these requests, finds the
right products and gives an accurate quote.

## What you get

• The PaperLane catalog website as PaperLane_site_v1.zip. To run it:
unzip, run python -m http.server 8000 in the unzipped folder, and open
http://localhost:8000/paperlane/. It must be served over HTTP; opening
the files from disk will not load volume prices. If our email includes a
hosted URL, it is an identical copy.

• Permission: you may crawl the site automatically, up to 2 requests per
second. Treat it like a real website and inspect it carefully; not all
content is in the initial HTML.

• The pricing rules below. Treat them as the customer's agreed
specification.

## Pricing rules

# Rule

PR1 All prices on the site exclude 7% VAT and are per pack (pack size
varies by product).

PR2 Volume pricing applies per item, based on the number of packs of
that item: use the highest tier whose minimum quantity is met.

PR3 A sale price replaces both the list price and volume pricing. They
cannot be combined.

PR4 Subtotal = sum of unit price x quantity. Delivery is free when the
subtotal is THB 3,000 or more; otherwise THB 150 per order.

PR5 VAT = 7% of (subtotal + delivery), rounded half-up to 2 decimals.
Total = subtotal + delivery + VAT.

PR6 When a customer gives a maximum price per pack, compare it with the
unit price they would pay at the requested quantity, before VAT.

PR7 Budgets are assumed to exclude VAT unless the customer says
otherwise. Say which assumption you used.

PR8 Out-of-stock and discontinued items must not be quoted as available.

Weights appear in gsm and in US bond pounds. Use: 20 lb = 75 gsm, 24 lb
= 90 gsm, 28 lb = 105 gsm, 32 lb = 120 gsm. Customers describe sizes and
options informally.

## What to build (must have)

1 An ingestion pipeline that crawls the site into a database of
normalised product records, including variants, volume pricing, stock
status and provenance (source URL and time).

2 A schema you can defend for size, weight, colour, finish, sides,
colour mode, pack size, prices and stock.

3 An assistant that turns a request into validated search criteria,
calls tools, and replies with matching products, why they match, and a
full price breakdown.

4 Pricing calculated by deterministic code, never by the model.

devx AI Labs \| AI Forward Deployed Engineer take-home \| A3 Product
Discovery Page 1

5 Clarifying questions when a request is ambiguous; a clear "no exact
match" with the closest alternatives when nothing fits; no invented
products.

6 An API (for example POST /chat or /quote) and a simple UI or CLI.

7 A test set of at least 10 requests with expected products and totals,
and your results.

8 A refresh path. In the demo round we will give you an updated version
of the site and ask you to re-ingest it without code changes.

## Nice to have

• Hybrid search (structured filters plus semantic matching)

• Multi-item quotes and conversation memory

• Defences against untrusted text in scraped content

• Logging and metrics you would watch in production

• Notes on deploying it behind a LINE or WhatsApp chat

## What we look for

Area Strong submissions

Data Complete, correctly typed records, including what is hidden in
variants or loaded by script.

Search Hard constraints as filters, softer wishes as ranking; unit and
size normalisation.

Agent design Clear tools and validation; the model decides intent, code
decides facts and prices.

Correctness Right products and totals to the satang on unseen requests,
including edge cases.

Business sense Replies a salesperson would be proud to send; honest when
nothing fits.

devx AI Labs \| AI Forward Deployed Engineer take-home \| A3 Product
Discovery Page 2

# Take-home assignment: start here

Thank you for your time in the first conversation. The next step is a
take-home assignment. There are three to choose from, and you do one.
Each is modelled on a real kind of project our engineers deliver for
customers in Southeast Asia. All companies, people and data in them are
fictional.

## The three options

Assignment Level What it emphasises

A1 Document Intelligence: a question-answering Easy Sound RAG
fundamentals, evaluation, assistant over an annual report honest answers

A2 Transaction Reconciliation: supplier invoices Medium Data integrity,
deterministic logic, against an ERP export auditability

A3 Product Discovery: a sales assistant over a Hard End-to-end design:
data, search, agents, product catalog website pricing

Pick the one where you can do your best work. A harder assignment earns
no extra points; an excellent A1 beats an average A3. Harder assignments
only give more room to show advanced skills.

## Time

• Plan for about 6 hours of focused work. Please do not spend much more;
good judgment about scope is part of what we look at.

• You have 5 calendar days from the day you receive this. The exact
deadline (18:00 your local time) is in our email.

• If you need more time for any reason, including a holiday, tell us.
Asking is fine.

## What to submit

1 A Git repository link (GitHub or GitLab; private is fine if you give
us access). Never commit API keys.

2 A README with: how to run it in 5 commands or fewer, an architecture
overview, key decisions and trade-offs, known limitations, and what you
would do with another week.

3 Your evaluation results as described in your brief, including cases
where your system fails.

4 A one-page customer summary (PDF or Markdown) written for the
customer's business owner, not an engineer: what you built, how well it
works, what it cannot do yet, and what you recommend next.

5 One short README paragraph on how you used AI tools while building.

Submit by replying to the email we sent you, with your repository link
and your one-page summary.

## Rules

• Any language, framework, model provider or database. Free tiers and
local models are fine.

• AI coding assistants are allowed. You must be able to explain and
change any part of your code in the interview.

• If model API costs are a barrier, tell us and we will give you a
capped API key.

• Use the data only for this assignment.

• Questions are welcome: reply to our email and we answer within one
business day. Asking good clarifying questions is part of the job.

devx AI Labs \| AI Forward Deployed Engineer take-home \| A3 Product
Discovery Page 3

## What happens after you submit

Round Length What happens

Demo and deep dive 60 min You demo your work. We run it on inputs you
have not seen. We discuss design, testing, failures and production
readiness.

Customer simulation 40 min A role-played discovery call, a short
solution pitch and a conversation with a sceptical stakeholder.

Live engineering 45 min A small debugging and diagnosis exercise. Bring
your usual tools.

Keep your solution runnable for the demo round: we will ask you to
process a new input file live, without changing code first.

## How we evaluate

Every candidate is scored on the same seven areas, whichever assignment
they pick: technical correctness, problem solving and judgment,
engineering quality, AI and data evaluation, communication, business and
pre-sales thinking, and ownership. We care more about evidence that your
system works, and honesty about where it does not, than about polish.

devx AI Labs \| AI Forward Deployed Engineer take-home \| A3 Product
Discovery Page 4
