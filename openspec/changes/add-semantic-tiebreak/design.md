# Design

## Context

See `proposal.md` — Why. Constraints that shape the approach, all verified on this machine rather than assumed:

- **Ranking today** is `matched.sort(key=_rank_key)` where `_rank_key` returns `(availability_penalty, unit_price.satang, sku)`. `RANKING_ORDER` documents the same tuple, and `tests/test_search.py:230` asserts the two agree — the tuple's order *is* the ranking rule, by design.
- **`_rank_key` is used twice**: on `matched` in `search()`, and on `found` in `_relax()`. A new term affects both, so the alternatives path needs the same treatment and the same test.
- **Ollama 0.34.4 is running at `http://localhost:11434`** and `bge-m3:latest` is installed (BERT, F16, 1024-dim, `capabilities: ["embedding"]`). `/api/embed` accepts `{"model": ..., "input": [...]}` and returns `{"embeddings": [[...]]}`.
- **Measured on this machine:** 1 text = 65ms, 10 = 96ms, all 72 products in one call = 627ms. Vectors are **L2-normalised** (‖v‖ = 1.0), so cosine similarity is a plain dot product. **Deterministic**: two identical calls returned bit-identical vectors (maxdiff 0.0).
- **Semantic sanity confirmed, not assumed:** cos("cheap writing paper", "A4 80gsm copy paper") = 0.6105; cos("glossy flyers", "A4 170gsm gloss flyer") = 0.7386; cos("glossy flyers", "A4 80gsm copy paper") = 0.4705; cos("banner", "A4 80gsm copy paper") = 0.3783. Paraphrase scores above unrelated — the model does what it is claimed to do.
- **Critical constraint:** under `unshare -rn` the loopback interface is DOWN and `connect()` to 127.0.0.1:11434 fails with `ENETUNREACH`. The test suite runs under exactly that namespace. **An unconditional embedding call would therefore break the "590 tests pass offline" guarantee.** This single fact drives decisions D2 and D4.

## Goals / Non-Goals

**Goals:**

- Reorder qualifying results by similarity, with membership provably unchanged.
- Preserve cheapest-first where price distinguishes.
- Keep determinism total.
- Keep the offline test suite passing with no provider.

**Non-Goals:**

- Semantic *retrieval* — embeddings do not enter the filter. The hard filter remains the only thing that decides membership.
- Replacing the alias layer. `aliases.py` resolves vocabulary deterministically and is unaffected.
- Any hosted embedding API. A local server only, so no credential and no external dependency.
- A vector index. 72 products is a dot product per candidate; an index would be unjustified complexity.

## Decisions

### D1 — Similarity is a ranking term, not a filter

**Chosen:** embed once, score each already-matched candidate, and insert the score into the sort key.

**Why:** the safe property is structural, not careful. If similarity is computed only for candidates that already passed `_evaluate()`, it is *impossible* for it to introduce an item — there is no code path that consults it before filtering. Making the guarantee structural means the test that asserts it is checking an invariant of the design rather than a behaviour that could regress with an edit elsewhere.

**Alternative rejected:** embedding-based pre-filtering or approximate nearest-neighbour retrieval. It changes membership, which means it can now *miss* a correct answer, and no test can distinguish "correctly excluded" from "silently lost".

### D2 — Ranking position: after availability, before price

**Chosen:** `(availability_penalty, -similarity, unit_price.satang, sku)`.

**Why:** this ordering satisfies both specs without a special case. Price still decides when items are equally similar; similarity decides when they are not. Putting similarity *after* price would make it nearly inert, since SKUs rarely tie on price — the term would almost never fire and the feature would be decorative. Putting it before availability would let a similar-but-unavailable item outrank an available one, which contradicts the existing availability rule.

**Cost:** the existing test asserting "cheapest qualifying option ranks first" must be checked to still hold. It does, because that scenario has no similarity spread between candidates when the provider is unconfigured, and the test runs unconfigured.

**Note on ordering semantics:** similarity is a float in [0,1] and sorts descending, so the key uses `-similarity`. Floats in a sort key are acceptable here *only because* the final term is `sku`, which makes the order total. Without that final term, float non-associativity could make order depend on input sequence.

### D3 — Cache embeddings per snapshot, not per request

**Chosen:** embed all product texts once per snapshot and memoise keyed by (snapshot identity, model name, text).

**Why:** 72 products cost 627ms once. Per request it would be 627ms + request embedding on every call, which is a worse chat experience than the feature is worth. The request text alone is embedded per call (65ms).

**Cache invalidation:** keyed on the snapshot's `built_at` and product count, so a re-ingest invalidates naturally. A stale cache would silently score against an old catalog, which is the kind of bug that produces plausible wrong orderings forever.

### D4 — Provider absent means the term is *exactly* absent, not zero

**Chosen:** when no provider is configured, the sort key omits the similarity term entirely; it does not insert a constant.

**Why:** a constant 0.0 would be *equivalent* in ordering but not identical in effect — it would still occupy a position in the tuple, and a future edit that made the term non-constant would silently change behaviour in the unconfigured path too. Omitting it keeps the unconfigured path provably identical to today's, which is what the spec requires ("behaves exactly as it does without the capability").

**Implementation:** `_rank_key(candidate, *, use_similarity: bool)`. The existing test at `test_search.py:230` is updated to assert the *documented* order includes the term conditionally, and a new test asserts the unconfigured key equals the old 3-tuple exactly.

### D5 — A provider failure degrades the request, and says so

**Chosen:** on connection error or timeout, fall back to the unconfigured ordering and record the degradation in the response metadata.

**Why:** an assistant that returns a 500 because a local embedding server is down is worse than one that returns a slightly worse ordering. But silent degradation is how a model-backed feature rots unnoticed — the same failure mode the observability change exists to catch. So: answer, and state that similarity was unavailable.

**Timeout:** short by generation standards, but **not 2s** as this design first
proposed. Measured on this machine: a *cold* model load costs 2.0s for one text
and 2.8s for all 72, while warm calls cost 0.02s and 0.64s. A 2s timeout failed
the first request after every restart, so the feature degraded on first use and
looked broken — the failure mode D5 exists to make visible, triggered by the
default path rather than an outage. 10s covers a cold load with headroom and
still fails fast on a dead provider. The original 2s figure came from warm-only
measurements; recorded here because the correction changes a stated decision.

### D6 — Measure the effect on the recorded set and report the number

**Chosen:** a command that runs every evaluation case with similarity off and on, and reports which cases changed order, how, and whether the change was an improvement.

**Why:** the honest risk here is shipping a feature that changes nothing and describing it as an improvement. `eval/cases.json` records expected *products*; most cases expect a specific top item. Running both configurations and diffing the orderings produces a number. If that number is zero, the README says zero.

**What "improvement" means here, precisely:** a case's expected first item moving *up* under similarity is an improvement; moving *down* is a regression; unchanged is neither. Cases are counted, not eyeballed.

## Risks / Trade-offs

- **Similarity displaces a correct cheapest-first answer** → similarity sorts after availability but before price, so it *can* reorder items that differ in price when their similarity also differs. This is a genuine behaviour change when the provider is on. Mitigation: the measurement in D6 counts how many recorded cases change, and the README states it. If it regresses cases, the term moves after price and the feature becomes a pure tiebreak — that is a one-line change, and the decision is recorded rather than guessed.
- **The offline guarantee silently breaks** → the suite runs under `unshare -rn` where loopback is down; provider-absent is the default path, and a test asserts the suite passes with no provider. The provider-dependent tests are explicitly gated and skip rather than fail when it is absent.
- **Float ordering instability** → the final `sku` term makes the order total; a test asserts two items with equal similarity still order consistently.
- **Embedding text is chosen badly** (e.g. embedding only the SKU) and the feature is inert → the text is built from name, category, finish, weight and size, and the D6 measurement exposes inertness as a zero.
- **The local server is not available on a reviewer's machine** → the feature is optional by construction; the README documents it as optional and gives the fallback behaviour. Nothing in the required demo path depends on it.
- **Claiming "semantic" for something that is not** → the model is a real embedding model and similarity is real cosine distance; but the README must state the model name, the dimension, and that it is a tiebreak over a deterministic filter, not a retrieval system.

## Migration Plan

Additive and optional. No snapshot schema change, no data migration. Rollback: unset the environment variables and behaviour returns to today's exactly — verified by a test that asserts the unconfigured path is byte-identical.

## Open Questions

- Whether to expose similarity in the JSON response always or only when enabled. Resolved: only when enabled, so the response shape does not change for existing callers, and the field's presence is itself the signal that similarity participated.
