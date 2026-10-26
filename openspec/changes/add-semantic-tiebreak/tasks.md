# Tasks

## 1. Embedding client

- [x] 1.1 Add an embedding client that reads `PAPERLANE_EMBED_BASE_URL` and `PAPERLANE_EMBED_MODEL` from the environment and reports itself unconfigured when either is absent, and verify a test asserts unconfigured state attempts no network call
- [x] 1.2 Implement the embed call against the local `/api/embed` shape and verify a test against a stub transport asserts the request body is `{"model": ..., "input": [...]}` and the response `embeddings` are parsed into a list of float vectors
- [x] 1.3 Assert vector shape and normalisation on receipt and verify a test asserts a mismatched dimension or a non-finite value raises rather than silently scoring, so a malformed response cannot produce a plausible-looking ordering
- [x] 1.4 Implement a short timeout (2s) and a typed failure for unreachable or erroring providers, and verify a test asserts both a connection refusal and a 500 produce the typed failure rather than propagating
  - **Deviation, measured:** the timeout is **10s, not 2s**. A cold model load costs 2.0s for one text and 2.8s for all 72, while warm calls cost 0.02s and 0.64s — so 2s failed the first request after every restart and the feature degraded on first use. Typed failure (`EmbeddingUnavailable`) covers refusal, timeout, 500 and unparseable bodies, each tested. Recorded in `design.md` D5 and `docs/semantic-ranking.md`.
- [x] 1.5 Verify no credential is required and none is read: assert the client sends no `Authorization` header when no key is set, and that `tests/test_hygiene.py`'s scan still passes

## 2. Product text and similarity

- [x] 2.1 Build the searchable text for a product from name, category, finish, weight and size, and verify a test asserts a product's text contains each of those fields and that a product missing one does not produce a malformed string
- [x] 2.2 Implement cosine similarity as a dot product for L2-normalised vectors, and verify tests assert identical vectors score 1.0, orthogonal score 0.0, and that the function does not re-normalise (guarding against double normalisation)
- [x] 2.3 Implement per-snapshot embedding cache keyed on snapshot build time, product count and model name, and verify a test asserts a cache hit avoids a second provider call and that a changed build time invalidates
- [x] 2.4 Verify against the real local server that 72 products embed in one call and that two calls return identical vectors, recording the observed latency — this task's verification is the measured numbers appearing in `docs/search.md`
  - 72 products in one call: **944ms warm**, 2.80s cold. Two calls returned bit-identical vectors (max difference 0.0). Dimension 1024. Numbers recorded in `docs/semantic-ranking.md` and `docs/search.md`.

## 3. Ranking integration

- [x] 3.1 Change `_rank_key` to accept a `use_similarity` flag and return `(availability_penalty, -similarity, unit_price.satang, sku)` when enabled and the existing 3-tuple when not, and verify a test asserts the disabled key is **exactly** the previous tuple, so the unconfigured path is provably unchanged
  - Flag implemented; the enabled tuple is `(availability_penalty, unit_price.satang, -similarity, sku)` — **similarity after price**, per the measurement in 6.3. The disabled key is asserted as the literal `(0, 1000, "A")`, not as an equivalent ordering.
- [x] 3.2 Update `RANKING_ORDER` to document the conditional term and verify the existing test asserting the documented order matches the implementation is updated and passes, including the conditional case
- [x] 3.3 Apply the flag to both call sites — `search()` on `matched` and `_relax()` on `found` — and verify a test asserts the alternatives path also orders by similarity when enabled, so the two paths cannot diverge
- [x] 3.4 Add the similarity score to `Candidate` and verify a test asserts it is present when enabled, absent when disabled, and that it does not appear in the reply text

## 4. Membership invariant

- [x] 4.1 Add a test asserting that for every case in `eval/cases.json`, the set of returned SKUs is identical with similarity enabled and disabled — this is the load-bearing invariant and it is tested across the whole recorded set, not a spot check
- [x] 4.2 Add a test asserting an item that fails a hard requirement is never returned no matter how similar, by constructing a request whose text is closest to an item the filter must exclude
- [x] 4.3 Add a test asserting a qualifying but lexically distant item is still returned, so the term cannot exclude
- [x] 4.4 Add a determinism test asserting two runs with similarity enabled return the same order, and that two candidates with equal similarity still order consistently via the SKU term

## 5. Degradation

- [x] 5.1 Wire provider failure to fall back to the disabled ordering and record the degradation in response metadata, and verify a test asserts a request succeeds with the fallback order when the provider is unreachable
- [x] 5.2 Verify the full suite passes with no provider configured and no network, by running it under `unshare -rn` and recording the result — this task exists because an unconditional call would break the offline guarantee
- [x] 5.3 Gate the provider-dependent tests so they skip cleanly when no provider is reachable, and verify the skip is reported rather than silently counted as a pass

## 6. Measurement

- [x] 6.1 Add a command that runs every recorded case with similarity off and on and reports which cases changed order and in which direction, and verify running it produces a case count, not a narrative
  - `./run.sh similarity` → `Cases run: 28 / Cases whose order changed: 3 / Cases whose first result changed: 0 / Improvements: 0 / Regressions: 0`. Counts, not prose. `--json` for machine reading.
- [x] 6.2 Record the measured effect in `docs/search.md` including the model name, dimension, latency figures and the number of cases whose order changed — and if the number is zero, say so plainly
  - `docs/search.md` and `docs/semantic-ranking.md`: `bge-m3:latest`, 1024 dimensions, 72 products in 944ms warm / 2.80s cold, 3 of 28 cases reordered. Improvements are **0** and stated as 0, not dressed up.
- [x] 6.3 If the measurement shows a regression on recorded cases, move the similarity term after price and re-record, stating which choice was made and why — verify the decision is recorded either way
  - **This fired.** Before price: 13/28 reordered, 9 first-result changes, 0 improvements, 6 regressions. Case 26 dropped `PL-CP-A4-70` — the cheapest qualifying item — from first to fourth, contradicting the spec scenario "similarity does not override a stated preference for cheaper". Moved after price and re-recorded: 3/28 reordered, 0 first-result changes, 0 improvements, 0 regressions. Both measurements are recorded in `docs/semantic-ranking.md`, `docs/search.md`, `design.md` D2 and `CHANGELOG.md`.

## 7. Documentation

- [x] 7.1 Write `docs/semantic-ranking.md` covering the ranking position and why, the membership invariant, the optional-provider contract, and the measured effect, and verify every command in it runs as written
- [x] 7.2 Update `README.md` to replace the "no embedding layer" limitation with what is now built, stating the model, the tiebreak scope, and that it is optional — and verify the five-command path is unchanged and still needs no provider
- [x] 7.3 Update `docs/search.md` and `ARCHITECTURE.md` ranking sections to show the conditional term, and verify the documented order matches `RANKING_ORDER` as asserted by the test
