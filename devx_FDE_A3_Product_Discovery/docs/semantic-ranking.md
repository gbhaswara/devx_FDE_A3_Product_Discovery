# Semantic ranking

An optional tiebreak: results that already satisfy every stated requirement are
ordered partly by how closely a product's description matches the customer's
wording.

The one property that matters: **it cannot change which products come back.** It
reorders. It never includes a product the filter excluded, and never drops one the
filter kept.

---

## Where it sits in the ranking

```
availability_penalty   available before unavailable
budget_margin          cheapest first, when no preference distinguishes
similarity             closest wording first, among items priced equally
sku                    stable, total tiebreak
```

`similarity` is **conditional** — present only when a provider is configured and
answered. With no provider the key is the three-element tuple it was before this
capability existed, and that is asserted as an exact tuple, not as an equivalent
ordering.

### Why after price, not before

The design originally placed similarity *before* price, arguing that price rarely
ties so the term would be decorative otherwise. That was measured and **rejected**.

Placing it before price reordered **13 of 28** recorded cases and moved the
expected first result in **9** of them, with **0 improvements and 6 regressions**
— measured, not estimated. Two concrete examples:

| Case | Request | Off | On |
|---|---|---|---|
| 4 | `A4 80gsm copy paper, 10 reams` | `NUSA` > `ECO` > `80` | `ECO` > `NUSA` > `80` |
| 26 | `A4 copy paper` | `70` > `75` > `NUSA` > `ECO` | `ECO` > `80` > `NUSA` > `70` |

Case 26 is the clearest: `PL-CP-A4-70` is the cheapest qualifying item and it
fell to fourth. That directly contradicts this system's own stated rule —
*"when several items satisfy every stated requirement and no preference
distinguishes them, the cheapest is returned first"* — and the spec's scenario
*"similarity does not override a stated preference for cheaper"*.

After price, it is a genuine tiebreak and the recorded set confirms it:

| Position | Cases reordered | First result changed | Improvements | Regressions |
|---|---|---|---|---|
| Before price | 13 / 28 | 9 | 0 | 6 |
| **After price** | **3 / 28** | **0** | **0** | **0** |

The three cases that still reorder are ties on price among equally-valid items —
exactly what a tiebreak is for. For example case 25 (`colour paper A4`) swaps
`PL-CL-A4-80-PYL` ahead of `PL-CL-A4-80-PGR`; both are A4 80gsm coloured paper at
the same price, so the order carries no correctness claim either way.

**The honest reading: on this evaluation set the feature is a pure tiebreak with
zero measured improvement and zero measured regression.** It is not sold here as
a quality win. It decides ties more sensibly than SKU order does, and it does not
displace the rules that do carry correctness.

---

## The membership invariant, and why it is structural

Similarity is computed **only for candidates that already passed `_evaluate()`**.
There is no code path that consults a score before filtering, so the guarantee is
a property of the design rather than of careful coding.

Tested across the whole recorded set, not spot-checked
(`tests/test_embeddings.py::TestMembershipInvariantAcrossRecordedCases`). The
scores are adversarial: the most similar product is deliberately the one the
previous ranking put *last*, so any case where membership could shift has the
best chance to show it. All 28 cases return an identical SKU set.

A detail worth stating, because it is easy to mistake for a bug: the reply shows
at most five alternatives, and enabling similarity **can** change which five are
shown. That is ordering of a display cap, not membership — the full qualifying
set is identical either way, and the test compares the full set for exactly this
reason.

---

## Optional by construction

The test suite runs under `unshare -rn`, where loopback is **down** and
`connect()` to `127.0.0.1` fails `ENETUNREACH`. An unconditional embedding call
would break the offline guarantee, so:

| Provider state | Ranking | `semantic` in the response |
|---|---|---|
| not configured | pre-semantic, exactly | absent |
| configured and reachable | similarity term active | `applied` |
| configured but failing | pre-semantic, exactly | `unavailable` |

A provider failure degrades the *order*, never the *answer*: the request is still
quoted, and the degradation is reported rather than silent. Verified against a
dead port — HTTP 200, `semantic: "unavailable"`, `semantic_detail:
"embedding request failed: ConnectError"`, and the same total.

"Not configured" and "configured but broken" are deliberately distinguished.
Both rank identically, but an operator needs to tell them apart, and a silent
fallback is how a model-backed feature rots unnoticed.

### No credential

The endpoint is local. The client sends **no `Authorization` header** and reads
no key, so there is none to leak — asserted by a test rather than described.

---

## Configuration

```
PAPERLANE_EMBED_BASE_URL   e.g. http://localhost:11434
PAPERLANE_EMBED_MODEL      e.g. bge-m3:latest
PAPERLANE_EMBED_TIMEOUT    optional, default 10s
```

Half-configuration counts as unconfigured. Guessing a model name would mean
scoring against a model the operator did not choose.

### Measured on this machine

Ollama 0.34.4, `bge-m3:latest` — BERT, F16, **1024 dimensions**.

| Operation | Cold | Warm |
|---|---|---|
| 1 text | 2.00s | 0.02s |
| 72 products, one call | 2.80s | 0.64s |

**The timeout is 10s because of the cold column.** The design originally proposed
2s, on the reasoning that an embedding call is a local matrix multiply. That
figure came from warm-only measurements and failed the first request after every
restart — the feature degraded on first use and looked broken. 10s covers a cold
load with headroom and still fails fast against a dead provider.

Vectors are L2-normalised, but only to float32 precision: across 72 products the
norm ranged 0.99999935 to 1.00000057, a maximum deviation of 6.5e-7. Cosine
similarity is therefore a plain dot product, and the receipt check allows 1e-3 —
about 1500× the observed error, while still rejecting a provider returning
un-normalised vectors. Demanding `norm == 1.0` would reject every real response.

Responses are deterministic: two identical calls returned bit-identical vectors
(max difference 0.0). That is what makes the ordering total.

---

## Measuring it yourself

```bash
PAPERLANE_EMBED_BASE_URL=http://localhost:11434 \
  PAPERLANE_EMBED_MODEL=bge-m3:latest \
  ./run.sh similarity
```

Prints counts, not a narrative: cases run, cases whose order changed, cases whose
first result changed, improvements and regressions. "Improvement" means the
case's expected first item moved **up**; that definition was fixed before any
result was seen, so it cannot be fitted to the outcome.

With no provider configured it prints `NOT MEASURED` and says why, rather than
reporting a zero that would look like a measured result.

```bash
./run.sh similarity --json     # machine-readable
```

---

## What this is not

- **Not retrieval.** Embeddings never enter the filter. Membership is decided by
  the hard constraints alone.
- **Not a vector index.** 72 products is one dot product per candidate; an index
  would be unjustified complexity.
- **Not a replacement for the alias layer.** `aliases.py` still resolves
  vocabulary deterministically and is unaffected.
- **Not a hosted API.** Local server only, so no credential and no external
  dependency.

---

## Tests

```bash
./run.sh test              # 1252 tests; provider-dependent ones skip
unshare -rn ./run.sh test  # the offline guarantee, 8 skips
```

Provider-dependent tests are marked `needs_embedding` and **skip** when no
provider answers — reported in the summary, never counted as a pass. There are
two distinct skip reasons: no loopback at all (offline run), and loopback present
but no Ollama listening.
