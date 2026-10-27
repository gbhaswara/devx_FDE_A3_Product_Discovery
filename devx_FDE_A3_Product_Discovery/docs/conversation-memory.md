# Conversation memory: what is carried, and what is not

A sales conversation is not a sequence of unrelated questions. A customer says
*A4 80gsm copy paper, 20 reams*, then *make it 50*. Without memory the second
sentence is unanswerable, and the most common thing a customer says second goes
unanswered.

This document describes the memory that now exists: the rule that decides when a
turn continues the last one, the two bounds, the two stores, and the one thing a
conversation id is not.

**Every command in this document has been run as written.** Where output is
quoted, it is copied from a real run rather than composed.

---

## 1. The constraint that shapes everything else

**The model never sees the conversation.**

The merge happens *after* interpretation, over typed `Criteria`, and only the
current turn's text ever reaches an interpreter. This is a deliberate restriction
and it costs something: the model cannot use the previous turn to resolve an
ambiguous word, so *"the cheaper one"* with no subject is a fresh request rather
than a reference to what was just quoted.

The reason is traceability. Every constraint in a merged result is traceable to a
turn that stated it. A model that could see the transcript could produce a
constraint appearing in no turn, and in the output that is indistinguishable from
a hallucination. The alternative — a model with the transcript — would handle
more sentences correctly and would make every wrong answer unfalsifiable.

So the merge rule does the work a human would: decide whether this turn continues
the last one, and which fields survive.

---

## 2. The continuation rule

A turn is a **continuation** when it names no new subject. A **subject** is a
category or a size — the two fields that name *which thing* is being discussed:

```python
SUBJECT_FIELDS = ("category", "size_code")
```

Weight is deliberately not a subject field. *Make it 100 gsm* adjusts the thing
already under discussion; it does not name a new one. Including weight here was
the first version of this rule and it was wrong: it made *make it 100 gsm* discard
the size and the category, so the refinement lost the paper it was refining.

| Previous | Current turn | Verdict |
|---|---|---|
| A4 copy paper, 20 reams | "make it 50" | continuation — a restated quantity |
| A4 copy paper, 20 reams | "and under 130 a pack" | continuation — a budget only |
| A4 copy paper, 80 gsm | "make it 100 gsm" | continuation — a weight is a correction |
| A4 copy paper, 20 reams | "A5 instead" | fresh — size stated |
| flyers, double-sided | "A4 copy paper" | fresh — category and size stated |
| (none) | anything | fresh — nothing to continue |
| A4 copy paper | "hello" | fresh — the turn understood nothing, and the criteria are kept for the next turn |
| 20 reams | "make it 50" | continuation — a first turn may state only a quantity (A12) |

### Field by field, the current turn wins

Where the current turn stated a value, that value is used. Where it did not, the
earlier value survives. `None` means *not stated* everywhere in `Criteria`, which
is what makes this expressible at all — and it is the same distinction that keeps
a printing constraint from excluding plain paper.

### A turn that understood nothing is fresh

*"hello"* after a quote does not re-answer the quote. Treating an empty turn as a
continuation would silently repeat the previous answer, which looks exactly like
the assistant ignoring what was just said.

**Fresh is about the reply, not about the history.** The turn is answered from an
empty request and is still recorded as a turn — but it does not *displace* what
the customer already asked for. `"A4 80gsm copy paper, 20 reams"`, then *"too
expensive"*, then *"make it 50"* still quotes 50 reams of the A4 80gsm paper.
The first implementation erased the criteria on an empty turn, so one unparseable
sentence ended the conversation's ability to be refined — the opposite of what
memory is for, and a stricter reading of D3 than D3 states (`BUG.md` A13). Only an
empty turn preserves this way; a turn that *names a subject* still replaces the
criteria, which is D3.

There is one exception, and it is a real one: a bare number. *Make it 50* contains
no unit word, so the general quantity parser cannot see a quantity — and that
parser is right, because in a *fresh* request a bare number is usually a size or a
weight (*A4 80gsm* must not become quantity 80). In a refinement the subject is
already fixed, so a lone number can only be the quantity.

The merge refuses to read a bare number as a quantity when the same turn states a
budget. *Under 130 a pack* also contains a bare number, and reading the budget as
the quantity would quote 130 reams — a wrong total, not a cosmetic slip.
Ambiguity resolves to *not stated*, which leaves the earlier quantity in place.

A lone number can also be one the catalog stocks as a weight, and there the rule
interpreter claims it first: *100* is read as 100 gsm because in a fresh request
that is the right reading (*A5 gloss 130*). Interpretation sees one turn and
cannot know it is a refinement (D1), so the merge reclaims the number when it is
the same one the turn adopted as its quantity, and carries the earlier weight
instead. Without that, *change it to 100* after 160 gsm paper changed the paper as
well as the quantity — and the wrong weight then survived every later turn, so
returning to a quantity that had already quoted came back as no-match (`BUG.md`
A17). An explicit *100 gsm* is still a weight correction: the helper returns
nothing the moment a unit word is present.

### A refusal and a no-match are turns

A refused or unmatched turn is still recorded, because the customer's next
sentence is usually *then what else have you got*. The constraints that failed are
exactly what the relaxation needs to see.

---

## 3. What the reply discloses

A customer who cannot see which requirement was remembered cannot correct it. So
every reply from a continued turn names what came from earlier:

```
Remembered from your earlier message: category Copy paper, size A4, 80 gsm.
Tell me if any of that is wrong.
```

This is applied in one place (`assistant._disclose_carried`) to all four
outcomes, so a refined request cannot quietly quote a remembered constraint in any
of the four shapes.

Quantity and budget are named individually rather than folded into the match
reasons, because both change the figure the customer is looking at and neither
appears in a match reason. A quantity the customer *just restated* is not
disclosed as remembered — it is current, and claiming otherwise is a small lie the
customer cannot check.

---

## 4. The two stores

| Store | Used by | Why |
|---|---|---|
| `InMemoryConversationStore` | `POST /api/ask`, the page | The service is one process; memory is enough and leaves nothing behind |
| `JsonlConversationStore` | `./run.sh ask --conversation` | Every CLI invocation is a new process, so an in-memory store would look like it worked while remembering nothing |

Both are bounded, and the bounds are a security property rather than a tidiness
one:

- **`MAX_CONVERSATIONS = 100`** — least-recently-used eviction.
- **`MAX_TURNS = 20`** — the oldest turn is dropped from a long conversation. The
  *turn number* is not capped with it: it comes from a counter on the
  conversation, so a 25-turn conversation still numbers its turns 1…25 even
  though only the newest 20 are retained (`BUG.md` A14 — deriving the number from
  the retained list made it saturate).

Without the first, an unauthenticated caller could grow the process's memory
without bound by inventing conversation ids. Without the second, one conversation
could do the same.

The JSONL store writes a **tombstone** on forget — `{"id": ..., "forgotten": true}`
— rather than an empty conversation, because an empty conversation is a legitimate
state (a caller who named an id and said nothing useful yet) and must not be
confused with a deleted one.

**Neither store holds request text.** The store holds `Criteria`. The
observability spec's decision about raw text applies here for the same reason, and
a conversation is the more dangerous place to keep it. Records carry
`turn_index` and `carried_fields`; they do not carry what was said.

---

## 5. A conversation id is a label, not a session

`conversation_id` is **unauthenticated**. Anyone who knows an id can read what is
carried in it by naming it, and anyone can name any id.

This is acceptable for the reason the whole service is not yet internet-reachable:
there is no authentication anywhere, and a conversation id that pretended to be a
session would be worse than one that is honest about being a label. Before
deployment it needs to become an authenticated principal — see
`docs/chat-channel.md` §4.

The id is validated (length-bounded, non-blank) and is **never echoed into the
page**. It is caller-supplied, so it is untrusted input like any other.

---

## 6. Off by default, and asserted

A request naming no conversation touches no store at all. This is not a
convention — it is tested with a store whose every method raises, so any access
fails the test.

A *first* turn in a conversation must also be indistinguishable from the same
request made standalone: same outcome, same reply text, same criteria. That
equivalence is what lets the original 28-case evaluation keep measuring what it
claims to. `./run.sh eval --cases eval/conversation-cases.json` replays all of
them as first turns and reports how many still produce the same reply.

---

## 7. Using it

**Over HTTP:**

```bash
curl -s localhost:8001/api/ask -H 'content-type: application/json' \
  -d '{"request": "A4 80gsm copy paper, 20 reams", "conversation_id": "c1"}'
curl -s localhost:8001/api/ask -H 'content-type: application/json' \
  -d '{"request": "make it 50", "conversation_id": "c1"}'
curl -s -X DELETE localhost:8001/api/conversations/c1
```

**On the page:** every page load starts a conversation with a fresh id, and the
result panel shows which turn it was and what it remembered. *Start over* is a
link back to `/`, so abandoning a conversation needs no request.

**From the CLI:**

```bash
./run.sh ask "A4 80gsm copy paper, 20 reams" --conversation demo
./run.sh ask "make it 50" --conversation demo
./run.sh ask --forget --conversation demo
```

---

## 8. The evaluation

```bash
./run.sh eval --cases eval/conversation-cases.json
```

Eleven recorded conversations, twenty-four turns, each asserting the merged
criteria a human would have understood, what the reply disclosed, and — where it
matters — that a fresh turn quotes the same total as the same request run
standalone.

Cases 9 and 10 are regressions from `BUG.md` A12: a first turn whose only
requirement is a quantity, or only a budget. For those turns
`has_any_constraint()` is False, and gating the *earlier* criteria on it threw the
conversation away. Case 11 is A13: an unparseable turn is answered fresh but must
not forget, so it asserts both halves. Every one of the three fails if the
corresponding defect is reintroduced.

The harness is shown able to fail:

```bash
./run.sh eval --cases eval/conversation-negative-control.json   # exits 1
```

Five cases, each wrong in exactly one way: a quantity not carried, a new subject
wrongly inheriting, a missing disclosure, a restated field called remembered, and
a wrong outcome. All five are rejected.

One axis is **not** falsifiable from a case file and is not claimed to be: the
pricing axis compares a fresh turn against the standalone run, and both go through
the same code. It is checked structurally instead — a `quoted` outcome must carry
a total.

---

## 9. Known limitations

- **The model cannot use the conversation.** *"The cheaper one"* with no subject
  is a fresh request. This is the cost of §1, and it is the larger of the two
  limitations here.
- **A continuation is decided by what the turn names, not by what it means.** *"A4
  copy paper"* mid-conversation about flyers starts fresh even if the customer
  meant to compare. That is the conservative direction: a wrong carry is worse
  than a lost one, because a wrong carry is a confident wrong answer.
- **A turn carrying both a bare quantity and a budget keeps the budget and drops
  the bare number.** Per-number resolution (skip the number the budget consumed)
  is the fix if it ever shows up in a real request.
- **Conversation state is per process.** The API's store is in memory, so a
  restart forgets every conversation and two workers do not share one. A shared
  store is the change a deployment needs, and the interface already allows it.
- **There is no expiry.** Bounds cap how much is held; nothing ages out a
  conversation that is merely old.

---

## 10. Where the code is

| Concern | File |
|---|---|
| The merge rule and both stores | `src/paperlane/conversation.py` |
| `Criteria.sources`, `describe_carried()` | `src/paperlane/criteria.py` |
| The disclosure in the reply | `src/paperlane/assistant.py` |
| The merge in `POST /api/ask`, the delete endpoint | `src/paperlane/api.py` |
| The merge on the page, the conversation bar | `src/paperlane/api.py`, `src/paperlane/ui.py` |
| `--conversation` / `--forget` | `src/paperlane/ask_cli.py`, `src/paperlane/cli.py` |
| `turn_index`, `carried_fields` on records | `src/paperlane/records.py` |
| The conversation evaluation | `src/paperlane/conversation_eval.py`, `eval/conversation-cases.json` |
| Tests | `tests/test_conversation.py`, `tests/test_conversation_api.py`, `tests/test_conversation_eval.py` |
