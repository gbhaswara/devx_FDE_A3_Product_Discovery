# Deploying behind LINE or WhatsApp

The assistant already exposes what a chat adapter needs: one endpoint that takes a
customer's words and returns a reply ready to send. This document says what that
adapter has to do, and — more usefully — what breaks if it is written naively.

**This is a design note, not a built adapter.** No LINE or WhatsApp code is in this
repository. Everything below about *this system* was measured against the running
service; everything about the *platforms* is cited from their own documentation,
and the platform limits are the kind that change without notice.

---

## 1. What the adapter has to do

The whole integration is one call:

```
POST /api/ask     {"request": "we need letter flyers, one side, colour, under 250 a pack, 20 packs"}
```

The response carries `outcome` and `reply`. The adapter's job:

| Step | What to do | Why |
|---|---|---|
| Receive the webhook | Acknowledge with `200` immediately, before answering | Both platforms retry an unacknowledged webhook. LINE and Meta time out in seconds; the model path can take much longer |
| Extract the text | Take the message body only; ignore stickers, images, location | The assistant answers text. An image is not a request, and treating one as empty text produces a spurious clarification |
| Call `/api/ask` | `use_model: true` in production | The rules path is a complete fallback, not a degraded one, but the model reads informal phrasing better |
| Send `reply` verbatim | Do **not** re-render or re-word it | The reply is composed deterministically from pricing output. Re-wording it is how a wrong total reaches a customer |
| Branch on `outcome`, not prose | `quoted` / `clarified` / `no_match` / `refused` | The four outcomes are a closed set declared in code and enforced by `check_outcome_contract()`. A caller never parses the sentence |

Two things the adapter must **not** do:

- **Do not send `figures` separately.** The totals are already in `reply`, formatted
  the way an invoice is. A second message with the same numbers is how the two
  drift apart.
- **Do not let the model write the message.** It never does here, and an adapter
  that asks it to would discard the property that makes the numbers trustworthy.

---

## 2. The four outcomes, and what each looks like to a customer

Measured on the running service, rules path, no model:

| Outcome | A real example | What the customer sees |
|---|---|---|
| `quoted` | `A4 80gsm copy paper, 20 reams` | Best match, why it matches, alternatives, itemised breakdown with VAT and total |
| `clarified` | `cheap paper` | One question: *"What are you looking for? For example: A4 copy paper, 80 gsm, 20 reams."* |
| `no_match` | — | The closest options, labelled as not matching |
| `refused` | `ivory A4 100gsm` | The item matches but cannot be ordered, with the restock date |

A chat adapter should render all four as plain text. `clarified` in particular
should not be swallowed: it is the assistant saying it needs one more detail, and
an adapter that drops it leaves the customer with silence.

---

## 3. The problem that will actually bite: no conversation memory

**This is single-turn by design, and a chat channel is inherently multi-turn.**
That mismatch is the main thing to solve, and it is not a small one.

Verified behaviour — the follow-up does not inherit anything:

```
Turn 1  "cheap paper"   → clarified   "What are you looking for? For example: A4 copy paper..."
Turn 2  "A4"            → quoted       criteria = {"size": "A4"}
```

Turn 2 was interpreted as a *fresh, complete request*. It happened to work, because
"A4" alone is answerable. But the request the customer was actually making — cheap
A4 paper — was silently dropped, and the assistant quoted Siam Office 70gsm at list
price with no budget filter applied.

The follow-ups that fail outright:

```
"make that 40 packs instead"      → no quantity, no product; nothing to act on
"and the 130gsm one?"             → no referent
"too expensive"                   → no referent
```

So the adapter needs a conversation store and one of two strategies:

1. **Rewrite before sending (recommended).** Keep the last N turns per chat id;
   prepend them to the customer's message so `/api/ask` sees a self-contained
   request. This costs one extra model call and keeps the assistant unchanged.
2. **Carry criteria forward.** Read `criteria` from the previous response, merge it
   with the new turn, and send `POST /api/quote` with explicit criteria instead of
   `/api/ask`. Cheaper and exact, but it cannot resolve "the 130gsm one" — the
   referent is in the product list, not the criteria.

Neither is built. Say so plainly rather than shipping an adapter that answers
"make that 40 packs" by quoting 20 again.

---

## 4. Platform limits that constrain the reply

The reply is plain text, no Markdown, and it is **short**: across all 28 recorded
evaluation cases the longest reply is 1,055 characters, and the longest single line
is 187.

| Limit | LINE | WhatsApp |
|---|---|---|
| Text body per message | 5,000 characters | 4,096 characters |
| Messages per send | 5 | 1 per call |
| Reply window | Reply token, single-use, ~1 minute (use it immediately) | 24-hour customer service window; outside it only pre-approved templates |

The LINE figures are from the official Messaging API reference (the `text` object's
`Max character limit: 5000`, the reply endpoint's `Max: 5`, and "reply tokens must
be used within one minute"). The WhatsApp 4,096 figure and the 24-hour window are
from Meta's Cloud API documentation as quoted by several independent providers;
**Meta's own page was not reachable from the machine this was written on, so treat
those two as unconfirmed at source and check them before relying on them.**

At 1,055 characters, **the reply fits in one message on both platforms.** No
chunking is needed, and chunking should not be added speculatively — a breakdown
split across two messages is worse than the same breakdown in one.

### The column alignment will not survive

The breakdown is aligned with leading spaces, which assumes a monospace font:

```
  Subtotal      2,340.00
  Delivery        150.00
  VAT 7%          174.30
  Total         2,664.30
```

LINE and WhatsApp render proportional fonts, so those columns will look ragged.
Two honest options: send it as-is (still readable, still correct — the numbers are
in order and labelled), or add a Markdown-free plain variant that drops the
alignment. **Do not reach for a Markdown table**: LINE's text message supports
Unicode emoji and LINE emoji and nothing else in the way of markup, and the reply
is not Markdown today, so a table would arrive as pipe characters. WhatsApp supports
only `*bold*`, `_italic_`, `~strike~` and monospace.

### The latency budget is fine on rules, tight on the model

Measured against the running service, 15 requests, rules path:

```
median 63.6 ms    p95 69.5 ms    max 69.8 ms
```

That is comfortably inside any chat platform's patience. The model path is the
risk: `PAPERLANE_LLM_*` calls carry a **45 s timeout**, which is most of LINE's
one-minute reply-token budget spent on a single request. Two consequences:

- Choose a model that answers in a few seconds, not one that thinks for forty.
- Do not raise the timeout to "give it more room". On a chat channel it buys a
  better answer that the customer never receives, because the reply token has
  already expired. If the model is slow, answer with the rules path — which is a
  complete path, not a degraded one — and let the customer refine.

Do not raise the model timeout to "give it more room". It will spend the reply
token and the customer will get nothing.

---

## 5. Deployment gaps in this repository

Stated as gaps, because a demo behind a chat channel is where each one stops being
theoretical.

**No authentication on the API.** Every endpoint is open, and there is no
`Depends`, no bearer token, no API key — verified by inspection. The service binds
`127.0.0.1` by default, which is the only thing protecting it. A public chat
webhook must be internet-reachable, so putting this behind one means adding auth
first. **This is the largest gap.**

**No webhook signature verification.** Both platforms sign their webhooks (LINE
with an HMAC of the body, Meta with `X-Hub-Signature-256`). Without checking, anyone
who learns the URL can drive the assistant and, through it, the record log.

**No idempotency.** Both platforms can redeliver a webhook — LINE's reference
documents reply tokens arriving in *redelivered* webhooks, and Meta retries failed
deliveries on its own schedule. There is no message-id dedupe here, so a redelivery
produces a second record and, worse, a second reply. Deduplicate on the platform's
message id before calling `/api/ask`.

**Single process only.** The record writer serialises appends with a
`threading.Lock` and `uvicorn.run(app, ...)` starts one process. That is correct for
one process and **not** safe across several: two worker processes each hold their
own lock and can interleave partial lines into the same file. Either keep one
worker, or move records to something with real cross-process semantics.

**No rate limiting or queue.** Nothing throttles inbound volume. A busy LINE
account would put concurrent requests straight onto the model endpoint.

**PII in the record log.** Records deliberately carry `request_chars` and a
16-character `request_digest`, **not** the customer's text — so the log is safe to
keep by default. `PAPERLANE_RECORD_TEXT=1` turns on capture for debugging, bounded
by `PAPERLANE_RECORD_TEXT_MAX` (default 200 characters). A chat deployment handling
real customer messages should leave that off; the digest groups repeat requests
without storing them.

---

## 6. What is already right for this

Worth saying, because these are the parts that usually go wrong:

- **The reply is a string meant for a human.** Not a template, not a JSON blob the
  adapter has to render. `reply` is the exact text to send.
- **The outcome set is closed and enforced.** Four values, declared in
  `OUTCOME_REQUIRED_FIELDS`, checked by `check_outcome_contract()`. An adapter that
  branches on `outcome` cannot be surprised by a fifth value.
- **No price can reach the customer without deterministic code having produced it.**
  That property is unchanged by adding a channel.
- **The service is stateless per request**, so horizontal scaling needs only the
  record writer fixed — no session affinity, no sticky routing.
- **Reply length is bounded in practice.** 1,055 characters worst case across all
  28 evaluation cases means no chunking, no truncation, no split breakdowns.

---

## 7. The order I would do it in

1. **Auth + webhook signature verification.** Nothing else matters until the
   endpoint is safe to expose.
2. **Idempotency on message id.** Cheap, and it prevents duplicate replies.
3. **Conversation store and query rewriting.** Without it the channel cannot hold
   the conversation a chat channel exists for. This is the real work.
4. **Then LINE, then WhatsApp.** LINE first for Bangkok — it is the channel
   PaperLane's customers are already in. WhatsApp adds the 24-hour template
   constraint, which is a business decision about message templates, not a
   technical one.
5. **Queue + rate limit**, sized to whatever the model endpoint tolerates.

The adapter itself is a few hundred lines. Steps 1–3 are the deployment, and they
are the reason this note exists rather than a code file.
