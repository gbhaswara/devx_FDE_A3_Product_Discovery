# Proposal

## Why

The assistant is single-turn. Every request is interpreted from nothing, so a
customer who says "actually, make it 20 packs" gets asked for a product kind
again, and one who says "no, the A5 one" gets the whole catalog re-searched
from a sentence that contains no size and no category.

`ANALYZE_01.md` §8 cut conversation memory deliberately, with the reason
"single-turn + explicit clarify beats half-built memory". That reasoning is
about a *half-built* memory, and it is right about that: a store that
accumulates state without a rule for when to discard it produces confidently
wrong answers, which is worse than asking again. But the conclusion was applied
to the whole capability, and the cost is visible in the demo — the second most
natural thing a customer says is a refinement, and the assistant cannot hear it.

This change builds the memory the scope cut was protecting against being built
badly. Three rules do the work:

1. **A turn is merged onto the conversation only when it is a refinement.** A
   new product kind, size, or category starts a fresh request. "20 packs" or
   "cheaper" or "the A5 one" continues the current one.
2. **A field is only carried forward when the new turn did not state it.** An
   explicit value in the current turn always wins, so a correction corrects.
3. **Memory is a per-conversation store the caller names, and it is never
   inferred from the request text.** No implicit sessions, no hidden state
   keyed on a phrase, and no state that survives a restart unless a file store
   was asked for.

The spec already says the assistant must never invent a product. Merging makes
that obligation harder, not easier, so this change also adds the guarantee that
a merged request is re-validated in full and that the reply says which fields
came from earlier turns.

## What Changes

- A **conversation store**: an in-memory store with a bounded number of
  conversations and a bounded number of turns per conversation, plus an
  optional JSONL-backed store for a restart-surviving demo. Both are
  thread-safe and both evict oldest-first.
- A **merge rule** that decides, per turn, whether it refines the previous
  request or replaces it, and which fields carry forward. It is a pure function
  over (previous criteria, new criteria) and is tested as one.
- **Criteria gain their provenance**: each field records whether it came from
  this turn or an earlier one, so the reply can say "size A4 (from your earlier
  message)" rather than presenting a remembered constraint as a fresh one.
- **`POST /api/ask` accepts an optional `conversation_id`**, returns the one it
  used, and `DELETE /api/conversations/{id}` forgets it. A request with no id
  behaves exactly as it does today — no store is touched.
- **`./run.sh ask --conversation <id>`** keeps a conversation across
  invocations, and `--forget` clears it.
- **The page keeps its conversation** across turns.
- **The record gains `turn_index` and `carried_fields`**, so multi-turn traffic
  is distinguishable from single-turn traffic in the metrics rather than
  silently blended into it.

**BREAKING:** none. `conversation_id` is optional and absent by default; with it
absent every code path is the current one.

## Capabilities

### New Capabilities

- `conversation-memory`: the store, its bounds, its eviction, the merge rule,
  and the guarantees about what memory must never do (carry a field the new turn
  contradicted, survive a request that named no conversation, or let a stale
  constraint be presented as a fresh one).

### Modified Capabilities

- `sales-assistant`: a request may be a refinement of an earlier one, and when
  it is, the reply states which requirements came from earlier turns. The
  never-invent guarantee is extended to merged requests.
- `observability`: the record carries `turn_index` and `carried_fields`, so
  multi-turn and single-turn traffic are separable.

## Impact

- **New code:** `conversation.py` (the store and the merge rule), plus a
  `--conversation` flag in `ask_cli.py` and a `conversation_id` field on the
  request model.
- **Modified code:** `api.py` (accept, return, and forget conversations; the
  page's fragment endpoint keeps one), `criteria.py` (field provenance),
  `records.py` (two new fields), `ui.py` (a "forget" control and a note on which
  requirements were carried).
- **Storage:** in memory by default. The optional file store writes to
  `data/conversations.jsonl`, which is git-ignored for the same reason request
  records are: it is runtime data, and committing it would look like a second
  source of truth.
- **Docs:** `docs/conversation-memory.md`, plus the three places that currently
  state memory is absent (`README.md`, `CUSTOMER_SUMMARY.md`,
  `docs/chat-channel.md` §3). Those statements become false in this change, and
  a doc that describes a limitation you removed is worse than no doc.
- **The load-bearing risk:** a merge that carries too much produces a reply the
  customer cannot explain. The mitigation is not more tests of the happy path —
  it is that the merge is a pure function, that it is tested against the eval
  set replayed as conversations, and that the reply discloses what was carried.
