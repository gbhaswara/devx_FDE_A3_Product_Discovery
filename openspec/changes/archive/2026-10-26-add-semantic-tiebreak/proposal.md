# Proposal

## Why

Search today is **hard filtering plus a deterministic ranking**, and the ranking's only price-independent term is the SKU. That is defensible — it is total, stable, and reproducible — but it has a real consequence that the README currently states as a limitation: when several items satisfy every stated requirement equally well, the order carries no signal about which one the customer's *wording* was closest to. Two items that both match "A4 80gsm copy paper" are ordered by SKU, which is arbitrary from the customer's point of view.

The brief's nice-to-have list asks for semantic ranking. The value is not in replacing the hard filter — the filter is what makes results *correct* — but in breaking ties by how well an item's description matches the request, so the top result is the one a salesperson would have picked.

There is also a correctness argument for building it now rather than later: the property that makes a semantic layer safe is that it **cannot change the set of results, only their order**. That property is easy to guarantee by construction and easy to lose by accident. Building it with the guarantee as an explicit, tested invariant is worth more than adding it later under pressure.

## What Changes

- A **semantic similarity layer** that embeds a product's searchable text and the customer's request, and scores each candidate by cosine similarity.
- The similarity score enters the ranking as a **tiebreak that sorts only among items already passing every hard constraint**. It cannot introduce an item into the result set, and cannot remove one.
- The ranking order becomes: availability, then **similarity (descending)**, then unit price, then SKU. Similarity outranks price only where price does not distinguish — the brief scores "cheapest qualifying option first" and that behaviour must not regress.
- **Embedding is optional and degrades to today's behaviour exactly.** With no embedding provider configured, the ranking is byte-identical to the current one and no network call is attempted.
- The similarity score is exposed per candidate so a reviewer can see the tiebreak acting, rather than taking it on trust.

**BREAKING:** none. With embedding unconfigured, behaviour is unchanged; the existing ranking test that pins `RANKING_ORDER` is updated to include the new term, but its assertion about cheapest-first and deterministic ordering still holds.

## Capabilities

### New Capabilities

- `semantic-ranking`: ordering of already-qualifying results by the similarity between a customer's wording and an item's description, with the guarantee that it reorders without including or excluding, and with a documented no-provider fallback.

### Modified Capabilities

- `product-search`: the requirement *"Ranking is deterministic"* gains scenarios covering a similarity term — determinism must survive it, and ties must still resolve totally. The requirement *"Soft preferences rank results without excluding them"* gains a scenario asserting the semantic term never changes membership.

## Impact

- **New code:** an embedding client (thin HTTP to a local embedding endpoint), a small similarity module, and wiring into `search()`.
- **Modified code:** `search.py` — `RANKING_ORDER` and `_rank_key` gain a term; `Candidate` gains a similarity field. `api.py` surfaces it. `cli.py` gains a way to run the comparison.
- **Dependencies:** none added to `pyproject.toml`. The embedding client uses `httpx`, already a dependency, and speaks to a local server over HTTP. No SDK.
- **Configuration:** `PAPERLANE_EMBED_BASE_URL` and `PAPERLANE_EMBED_MODEL`, following the existing environment-only convention. No credential is required for a local endpoint, and none is committed.
- **Tests:** the invariant that membership is unchanged becomes a property test across every evaluation case, not a spot check. The offline test suite must still pass with no embedding server running — this is the load-bearing constraint, since the suite is run under a network namespace where loopback is down.
- **Performance:** embedding 72 products takes ~0.6s against the local server and is cached per snapshot, not per request. A request embeds only its own text.
- **Risk:** a semantic layer that is claimed to be "measured" without measurement is worse than none. Recall must be reported against the labelled evaluation set, and the README must state the number and the method or state plainly that it is unmeasured.
