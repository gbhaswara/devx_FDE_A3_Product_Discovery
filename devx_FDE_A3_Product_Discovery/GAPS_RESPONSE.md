# Response to the gap analysis

`GAPS_ANALYSIS.md` reviews the finished system as a **production** sales
assistant. Read that way, most of what it finds is real — and most of it is out
of scope, because the brief asks for something narrower and says so in writing.
This document answers every finding, one by one, with one of four verdicts:

| Verdict | Meaning |
|---|---|
| **Closed** | The finding was correct and within scope. It is now fixed, with the fix and its verification named. |
| **Already closed** | The finding was correct but the build already handled it. The evidence is cited, not asserted. |
| **Out of scope by the brief** | The finding is real for a production deployment, but the brief defines what is in scope, and this is outside it. The reason is given. |
| **Not fixable in kind** | The finding is a real property of the approach, not an omission. It is stated as a limitation rather than papered over. |

Three findings were closed in the change that accompanies this document
(`openspec/changes/add-gap-closure/`). Everything else is answered below.

---

## 1. Stale or incorrect catalog data

**Severity the analysis gives it: Critical.**

**Verdict: partly closed, partly not fixable in kind.**

Split into two claims, because they have different answers.

**Freshness — closed.** The complaint is precise: *"the pricing engine can
calculate perfectly using outdated prices."* That was true, and worse than it
looked — `health()` reported counts and `metrics` reported five measures, and
none of them reported the catalog's **age**. A twelve-day-old catalog and one
crawled a minute ago rendered identically, so the exact condition described —
a correct engine behind stale data — was invisible to every surface the system
has.

Now: `age_seconds`, `age_human` and `stale` are derived from the recorded ingest
time and reported on `GET /api/health`, in the snapshot block of every API
response, in `./run.sh metrics`, and at `serve` startup. The threshold is a named
constant (`STALE_AFTER_HOURS`, 24, overridable by
`PAPERLANE_STALE_AFTER_HOURS`) rather than an implicit comparison. It is
**reported and never gating** — see §3 for why gating is the wrong instinct here.

Two details that matter and are easy to get wrong:

- The stored timestamp is zone-less. The crawl stamps it with
  `datetime.now(timezone.utc)` and DuckDB returns a naive `TIMESTAMP`, so reading
  it as local time in a UTC+7 deployment would make a nine-hour-old catalog look
  minutes old. It is read as UTC, and a test asserts that.
- An unknown age is `None`, not `False`. "Not stale" and "cannot tell" must not
  read the same.

**Incorrect data — not fixable in kind, and deliberately so.** The deeper point
in the analysis is that a crawl returning HTTP 200 does not establish that the
data is *correct*. That is true. What the system does instead is refuse to let a
plausible-but-unverified value become silent:

- Four markup shapes are parsed by a fallback ladder, and a page that cannot be
  parsed becomes a **review row**, not a missing product.
- Absent attributes are recorded as **not-applicable**, not as negative values,
  so an unknown weight cannot accidentally match or exclude a request.
- Every row carries provenance (source URL + retrieval timestamp).
- The injected-prompt case proves extraction cannot be talked into a different
  price: `tests/test_extract.py` feeds a page whose text instructs the reader to
  record `1.00`, and asserts the recorded price is unchanged.

The residual is real and is stated as a limitation in the README: the crawler
cannot know the supplier changed a price mid-crawl. §"The biggest architectural
blind spot" below answers the analysis's own version of this.

---

## 2. API and deployment security

**Verdict: out of scope by the brief — with one part already closed.**

The analysis is explicit that *"not all of these controls are necessary for a
small local demo."* The brief is that demo. It asks for a sales assistant over a
catalog, scored on scope judgment, and it names the seven scoring areas — none of
which is authentication, RBAC, rate limiting, idempotency or API versioning.
Adding a half-implemented version of any of them would be worse than the honest
limitation, because it would imply a control that does not hold.

The README already lists this as a limitation rather than leaving it implied.

**One part is closed, because it is not a deployment control but an input
boundary.** The analysis asks whether *"malformed inputs, oversized payloads and
invalid quantities"* are rejected. They are:

- every quantity field in `api.py` is constrained `ge=1, le=100_000`;
- `weight_gsm`, `weight_gsm_min` and `weight_gsm_max` are constrained `ge=1,
  le=1000`;
- a request that fails validation is a **client error**, and the design's
  degrade-never-crash rule explicitly does not apply to client errors — only to
  server-side failure.

**Secrets are closed.** The analysis asks whether keys stay out of source control
and logs. `tests/test_hygiene.py` asserts five things: no credential file is
committable, `.gitignore` covers the forbidden names, no source file contains a
literal secret, the documented configuration is environment-only, and a key
appearing in an **error path** does not reach the request record.

---

## 3. Catalog consistency across refreshes

**Verdict: closed in part, and deliberately not closed in the way proposed.**

The finding: *"atomic replacement prevents readers from seeing a half-written
database, but it does not by itself prove that the new catalog is complete,
fresh, or semantically correct … a bad but structurally valid snapshot could
replace a good one."*

Half of that was already handled. `catalog.build_snapshot` raises **before** the
swap if any row fails validation, so a malformed row cannot reach the serving
catalog, and a failed crawl leaves the previous snapshot serving untouched.

The other half — "a bad but *structurally valid* snapshot" — touches a real
trade-off, and the answer is not the proposed one.

**What was closed:** freshness (§1 — a snapshot's age is now on every surface),
and the ability to **keep** the good snapshot while building another. Ingest now
takes `--db` (and `PAPERLANE_DB`), so an unseen site can be ingested into a named
snapshot without disturbing `data/catalog.duckdb` — and that is verified by
asserting the committed file's **bytes** are unchanged, not its size or mtime,
which would pass a rewrite.

**Why the proposed completeness gate is refused.** The analysis recommends
*"block publication when critical thresholds fail."* This is refused on purpose,
and the reason is the demo round: it re-ingests a **live, unseen site** and asks
for answers immediately. A heuristic gate that refuses to publish when it is
unhappy would fail the demonstration in the room — the exact failure the gate was
meant to prevent. Incompleteness is **surfaced and counted** (review rows,
carried-forward items, the diff report) and not gated on, with one narrow
exception added later: a crawl that collapses to zero or below half the serving
row count is refused before the swap (see the update below). §1's freshness signal
follows the same rule.

**Update, 2026-10-28 — a narrower gate does exist.** A later probe found that a
structured change (the `table` → `dl` shape, or reworded availability) could
produce a *structurally valid* snapshot with almost nothing in it, and the old
snapshot would still be replaced. `ingest._swap_refusal` now refuses a swap when
the new snapshot has **zero SKUs** or **fewer than half** the serving snapshot's
rows, exits **3**, and keeps the staging file; `--accept-shrink` overrides it for
a genuine catalog cut. That is a **collapse detector, not the proposed
threshold**: it does not judge completeness, quality or freshness, and a swap
that merely loses a handful of rows still publishes. The distinction matters
because the demo round needs a working site to publish.

The rest of layer A is answered by existing mechanisms, cited rather than
claimed:

| Gap the analysis raises | What the system does |
|---|---|
| Partial crawl mistaken for complete | Unparseable pages become review rows; `verify-refresh` injects 12 known changes and asserts each is detected. A crawl that collapses to zero, or below half the serving row count, is refused before the swap (A32) |
| Incorrect extraction without a parse error | Provenance, not-applicable recording, and the injected-prompt test above |
| Review rows accumulate | Review status persists across refreshes with `carried_from`, so a flagged item stays flagged until resolved |
| Catalog rollback not described | The previous snapshot is kept as `catalog.previous.duckdb`, and the diff runs against it |
| Source site changes unexpectedly | Four markup shapes in a fallback ladder; `verify-refresh` is the canary |

---

## 4. Incorrect interpretation of customer intent

**Verdict: closed.** This was the most valuable finding in the analysis, and it
was right.

The analysis states it precisely: *"a valid criterion can still be semantically
wrong … an A4 request misread as A3 passes validation and returns a perfectly
valid quote for the wrong request."* That was true, and it was the one thing the
harness could not see — there were four axes (retrieval, match, pricing, reply)
and none asked whether the request was **understood**. A misreading surfaced as a
retrieval failure, which names the symptom and hides the cause.

Now `interpretation` is a fifth axis and the **first** in `AXES`, because it is
the earliest thing that can go wrong. Each case records what the request must be
read as (a declared **subset** of its fields, never a transcription of the
engine's own output) and what it must **not** invent. Two directions, because
they are different defects:

- a criterion the request implies that the reading **misses**;
- a criterion the request does not imply that the reading **invents** — "under
  250 a pack" becoming "80 gsm or lighter" is the second kind, and a subset check
  alone would miss it.

`self_check()` proves the axis discriminates: corrupting a case's derived size
fails interpretation and leaves retrieval, pricing and reply at pass.
`negative-control.json` gained a fourth corruption on this axis, and it fails on
interpretation **alone** — the products and the price are correct, and only the
reading is wrong. That is the finding, reproduced as a test.

---

## 5. Pricing policy and quote validity

**Verdict: out of scope by the brief, except quantity validation, which is already closed.**

The brief states that PR1–PR8 are *"the customer's agreed specification."* The
analysis's own framing agrees: *"the document's rules are based on the
assignment's specified policy. Before commercial deployment, those rules must be
reconciled with the real supplier's terms."* Reconciling them against a real
supplier's agreement — tax policy, quote expiry, concurrent price changes — would
mean contradicting the specification the customer agreed to. The analysis calls
these *"questions for verification, not confirmed defects,"* and that is how they
are treated here: documented as assumptions in the README, not silently resolved.

The table resolves as:

| Question | Where it stands |
|---|---|
| Tax policy — is 7% right? | PR5 in the brief. Not this system's to decide. |
| Discount precedence | PR3 in the brief, implemented and independently recomputed by `recompute_totals()` |
| Quantity validation | **Closed.** `ge=1, le=100_000` on every quantity field; a client error, not a degraded answer |
| Delivery policy | PR4. One threshold, charged once per order against the summed subtotal |
| Quote expiry | Out of scope by the brief |
| Price change between quote and order | §"biggest blind spot" below |
| Multiple lines | Duplicate SKUs are independent lines; tiers are per **SKU**, so 10 + 10 packs is not 20 packs of one thing (case 27) |
| Monetary limits | Integer satang throughout, so no float drift; quantity bounded as above |

---

## 6. Observability and evaluation

**Verdict: two of the three sub-findings closed, one already closed, one out of scope.**

The analysis's sharpest point here is **evaluation-set overfitting**: *"a system
may pass its 28 ranking cases while performing poorly on new requests, unfamiliar
phrasing, or unusual catalog changes … keep separate test sets for routine
regression testing, unseen customer requests, and deliberately adversarial edge
cases."*

That was correct, and it is now closed. `eval/held-out-cases.json` holds 11
requests in phrasings that appear nowhere in `cases.json`, written after the
rules path was finished. Expectations are derived by filtering the catalog
directly and applying the **documented** ranking chain — never by reading the
engine's response, which would make the set a recording of current behaviour
rather than a statement of what the request means.

**It fails, and the failures are kept.** Three of eleven fail, all from one root
cause: an unmappable noun is dropped rather than honoured, so the answer silently
widens.

- *"the pink A4 coloured paper, 2 packs"* — the shade reads as `None`, and the
  answer widens from the one pink product to all seven A4 coloured papers. The
  price moves with it. This is §4's finding, found independently by the held-out
  set.
- *"pastel grey A4 paper"* — nothing grey is stocked, so no match is correct. The
  engine returns all 33 A4 papers.
- *"30 lb letter paper"* — 30 lb is about 112 gsm and nothing matches. The engine
  returns all 19 letter papers.

A test asserts at least one held-out failure **remains**, because a held-out set
that passes completely is evidence about its author. Deleting these cases to get
a clean sweep is the move the test exists to prevent.

Of the seven things the analysis asks whether the system measures, four were
already measured (interpretation success and fallback frequency and clarification
rates — `metrics`; product-match accuracy independent of price — the separate
axes; latency and provider failures — `metrics`; regression rates on catalog
change — `verify-refresh`), freshness is now added, and one is out of scope:

| Asked | Status |
|---|---|
| Catalog freshness and crawl completeness | **Freshness closed**; completeness surfaced via review rows, not gated — except a collapse to zero or below half the serving row count, which is refused before the swap (§3, A32) |
| Review-row counts and unresolved fields | Already — `metrics` reports the review backlog |
| Interpretation success, fallback, clarification rates | Interpretation **closed** (§4); the other two already in `metrics` |
| Product-match accuracy independent of price | Already — separate `retrieval` and `pricing` axes, cases 25–27 |
| Latency, error rates, provider failures | Already — p95, fallback rate, disagreement metric |
| Price/stock discrepancy after quotes | **Out of scope** — requires an ordering system the brief does not ask for |
| Regression rates on catalog/interpretation change | Already — `verify-refresh`, and the negative controls |

---

## The biggest architectural blind spot

> PaperLane verifies that its calculations and responses are internally
> consistent, but internal consistency is not the same as external truth.

**Verdict: correct, and accepted as a limitation rather than fixed.**

This is the best observation in the analysis, and it is true. The failure it
describes is precise: the crawler records ฿120, the engine computes with ฿120,
the guards confirm the reply says ฿120 — and the supplier changed the price to
฿130 before the crawl finished. Every internal check passes and the customer gets
an outdated quote.

It cannot be fixed from inside. No amount of internal verification can establish
a fact about the outside world; that requires a second, external source of truth,
which the brief explicitly rules out (*"use the data only for this assignment"*
and no external data). What the system does instead is the honest second-best:

- every row carries **provenance** — where it came from and when;
- every snapshot reports its **age** and whether it exceeds a stated threshold;
- every answer reports the **snapshot** its figures were computed from;
- incompleteness is **surfaced** — review rows, carried-forward items, the diff.

A reader can therefore see *when* a figure was true, which is the most a system
without an independent source can honestly offer. The limitation is stated in the
README. The analysis's own conclusion — *"strengthen the data freshness,
validation, and commercial verification around the deterministic core"* — is what
this change did; the one part it did not do, gating publication, is refused for
the reason in §3.

---

## Summary

| # | Finding | Verdict |
|---|---|---|
| 1 | Stale catalog data | **Closed** (freshness); incorrect-data residual **not fixable in kind** |
| 2 | API/deployment security | **Out of scope by the brief**; input validation and secrets **already closed** |
| 3 | Consistency across refreshes | **Closed in part**; the completeness **gate refused** deliberately |
| 4 | Incorrect interpretation of intent | **Closed** — the interpretation axis |
| 5 | Pricing policy and quote validity | **Out of scope by the brief**; quantity validation already closed |
| 6 | Observability and evaluation | **Closed** — the held-out set, plus the freshness signal |
| — | The blind spot: internal ≠ external truth | **Accepted as a limitation**, and stated as one |

The three findings that sit inside the brief's scored areas — interpretation,
freshness, and evaluation overfitting — are closed and verified. The rest are
answered rather than fixed, because a take-home that quietly expanded to cover a
production security review would be failing the part of the brief that scores
scope judgment.
