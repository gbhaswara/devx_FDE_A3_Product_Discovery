# Design

## Context

Every request today is interpreted in isolation. `interpret_rules(text)` returns
`Criteria` built only from the text, `interpret(text, client)` merges a model
result onto that, and `answer(criteria, ...)` prices it. Nothing between them
knows a previous turn exists.

The scope cut in `ANALYZE_01.md` §8 rejected multi-turn memory for a reason worth
quoting exactly:

> Single-turn + explicit clarify beats half-built memory

That is a claim about half-built memory, and it is correct. The failure mode it
names is real: a memory that accumulates state without a rule for discarding it
will answer a new question using the previous one's constraints, and the
customer has no way to see it happen. This design is mostly an argument about
how to not build that.

## Goals

- A refinement is understood: "make it 20 packs", "the A5 one", "cheaper",
  "yes", "no, double-sided".
- A new request is not contaminated: "A4 copy paper" after a conversation about
  flyers is a fresh search, not a flyer search with A4 bolted on.
- What was remembered is visible in the reply, in words.
- With no `conversation_id`, behaviour is byte-identical to today.

## Non-Goals

- **Inferring a conversation from request text.** No hidden session, no
  cookie-derived identity, no "same customer, probably" heuristic.
- **Storing the customer's sentences.** The store holds `Criteria`, not text.
  This follows the observability spec's decision about raw text, and it is the
  reason the file store is small and dull.
- **Summarising history for the model.** The model interprets the current turn
  only; merging is deterministic and happens after interpretation. A model that
  can rewrite history is a model that can invent a constraint nobody stated.
- **Persistence as a service concern.** The file store is for demos and for
  `./run.sh ask`; the service defaults to memory.

## Decisions

### D1 — Merge after interpretation, never before

The model sees the current turn's text and nothing else. The merge happens
between `interpret` and `validate`, over `Criteria` objects.

*Why:* if the model saw the conversation, a merged result could contain a
constraint that appears in no turn — indistinguishable, in the output, from a
hallucination. Interpreting each turn in isolation and merging typed values
means every constraint in the result is traceable to a turn that stated it. The
cost is that the model cannot resolve "the cheaper one" — the merge rule has to,
and D3 is how.

*Rejected:* passing the transcript to the model. It reads better in a demo and
is untestable: there is no assertion that distinguishes "the model remembered"
from "the model made it up".

### D2 — The merge is a pure function over two `Criteria`

```python
merge_turn(previous: Criteria | None, current: Criteria) -> tuple[Criteria, frozenset[str], bool]
```

returning the merged criteria, the field names carried forward, and whether the
turn was a continuation at all. No store, no clock, no I/O.

*Why:* the interesting behaviour is then testable as a table of (previous,
current) → (merged, carried) with no fixtures, and the store's correctness
becomes a separate, much smaller question. It also means the eval harness can
replay the existing 28 cases as conversations without standing up an API.

### D3 — Continuation is decided by what the new turn *does not* say

A turn is a **continuation** when it states no new product kind or size, and a
**fresh request** when it states either.

| Previous | Current turn | Verdict |
|---|---|---|
| A4 copy paper, 20 reams | "make it 50" | continuation — a restated quantity |
| A4 copy paper, 20 reams | "and under 130 a pack" | continuation — a budget only |
| A4 copy paper, 80 gsm | "make it 100 gsm" | continuation — a weight is a correction |
| A4 copy paper, 20 reams | "A5 instead" | fresh — size stated |
| flyers, double-sided | "A4 copy paper" | fresh — category and size stated |
| (none) | anything | fresh — nothing to continue |
| A4 copy paper | "hello" | fresh — the turn understood nothing |

*Why this rule and not "does it parse to anything":* the alternative — continue
whenever the turn produced few fields — would treat "A4" as a continuation of a
flyer conversation and quote flyers in A4. A stated product kind or size is the
customer naming a subject; that is the strongest available signal that the
subject changed, and it is the one a salesperson uses.

*Why weight is not in that set — a decision made during implementation.* The
first version of this rule included exact weight, on the reasoning that a stated
weight narrows the catalog the way a size does. Implementing the merge table
showed it was wrong: "make it 100 gsm" would be a fresh request, so the size and
category the customer had just given would be discarded and the reply would ask
for them again. A weight *adjusts* a thing the customer has already named; a
size or a product kind *names* one. The distinction is the difference between a
correction and a change of subject, and only the second should discard context.

*Consequence, accepted:* "A5 instead" starts fresh rather than refining. It is
the one case where the rule is more conservative than a human, and the cost is
one extra clarification, not a wrong answer. Preferring a question over a wrong
quote is the same trade the assistant already makes elsewhere.

### D4 — An explicit field in the current turn always wins

Merging is field-by-field: for each field, take the current turn's value if it
is set, else the previous value. `None` means "not stated" everywhere in
`Criteria`, which is what makes this expressible at all.

*Why:* a correction must correct. "No, 100 gsm" after "80 gsm" has to produce
100 gsm. Because `None` never means "explicitly cleared", the merge cannot
distinguish "the customer did not mention size" from "the customer wants any
size" — see D5.

### D5 — Carried fields are disclosed, and a contradiction is asked about

The reply names the fields it carried: "size A4 and 20 reams, from your earlier
message". Two fields need more than disclosure:

- **quantity**, because carrying it silently changes a total the customer did
  not ask to change;
- **budget**, because a budget is the constraint most likely to be a one-off.

Both are carried, but the reply states them explicitly rather than folding them
into the match reasons.

*Why not "clear a field when the new turn omits it":* that is single-turn
behaviour with extra steps, and it makes "make it 50" forget the product.

### D6 — Bounds are part of the contract, not a tuning detail

`MAX_CONVERSATIONS = 100`, `MAX_TURNS = 20`, evicting least-recently-used first.
Both are asserted by tests, not left to a comment.

*Why:* an unbounded in-memory store keyed by a caller-supplied id is a memory
exhaustion vector — anyone can send a new `conversation_id` per request. The
bound is what makes accepting a caller-supplied key safe, so it is a security
property rather than a housekeeping one, and it is tested as one.

`MAX_TURNS` exists for a different reason: a conversation that has run 20 turns
is usually a conversation where the customer has changed their mind so often
that the merged criteria are archaeology. Truncating the *stored* turn count
while keeping the merged criteria is deliberate — the criteria are the state;
the turn count is only a bound on how much history is retained for disclosure.

### D7 — Two stores, one interface, and memory is the default

`InMemoryConversationStore` and `JsonlConversationStore` share a protocol:
`get`, `put`, `forget`, `ids`. The API defaults to in-memory; `./run.sh ask`
uses the file store, because a CLI invocation is a new process and an in-memory
store would make `--conversation` a no-op that appears to work.

*Why the file store is not the default:* the service is the thing that must not
write unbounded operational data to disk by default, and an in-memory store with
a bounded size is the honest default for it.

### D8 — `conversation_id` is opaque and caller-supplied

Any non-empty string up to 128 characters. It is not authenticated — there is no
auth in this service at all, which is stated in `docs/` and unchanged here — and
it is not a security boundary. It is a label.

*Why state this loudly:* a caller-supplied key that looks like a session id
invites the assumption that it is one. It is not: anyone who knows an id can
continue that conversation. That is acceptable for a single-user local demo and
would not be acceptable in a deployment, which is why it is written down here
and in the docs rather than discovered later.

### D9 — Memory is off unless asked for, and that is observable

No `conversation_id` ⇒ no store read, no store write, no change to the record's
`turn_index` (it stays `None`). A test asserts the store is never touched.

*Why:* the existing 24 eval cases and every single-turn caller must be provably
unaffected. "Off by default" that is not asserted is a default that drifts.

### D10 — The eval set gains conversation cases, and the existing cases are replayed as conversations

A new case file replays the existing requests as sequences, asserting that the
merged criteria are what a human would have understood. The 24 existing cases
stay as they are.

*Why both:* the replayed cases prove memory does not corrupt single-turn
behaviour (each turn must produce the same answer as the standalone case when
the turn is fresh); the new cases prove refinements are actually understood.
Only doing the second would let a regression in single-turn behaviour hide.

## Risks

| Risk | Mitigation |
|---|---|
| A carried constraint is presented as fresh, so the customer cannot explain the answer | Carried fields are named in the reply (D5), and the record lists them |
| A stale conversation contaminates a new subject | The continuation rule treats a stated kind/size/category as a new subject (D3) |
| Unbounded memory from caller-supplied ids | Hard bounds, LRU eviction, tested (D6) |
| The model invents a constraint during a merge | The model never sees the conversation (D1) |
| Single-turn behaviour regresses | Off by default and asserted untouched (D9); existing 24 cases replayed |
| An id is mistaken for an authenticated session | Stated in the design and the docs; no auth exists in this service at all (D8) |

## Migration

None. No schema change to the catalog, no change to any existing response shape,
and `conversation_id` absent means the current code path.

## Open Questions

- Should a `clarified` reply be remembered as a turn? **Yes** — the criteria are
  what matter, and a clarification often supplies the only constraint. A turn
  that clarified is still a turn.
- Should a `refused` reply be remembered? **Yes**, for the same reason: the
  customer's next sentence is usually "then what else have you got", which is a
  continuation.
- Should `no_match` be remembered? **Yes.** The customer's next turn is almost
  always a relaxation of the request that failed, which is exactly what D3's
  continuation rule needs to see.
