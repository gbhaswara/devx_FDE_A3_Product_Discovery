# Observability: records, and the five measures derived from them

The assistant answers correctly or incorrectly with no operational signal either
way. This document describes the signal: one structured record per handled
request, and five measures computed from those records on every read.

**Every command in this document has been run as written.** Where output is
quoted, it is copied from a real run rather than composed.

---

## 1. The record

One JSON object per line, appended to `data/requests.jsonl` (git-ignored) when
the service handles a request that interprets or quotes.

```json
{
  "candidates_considered": 72,
  "endpoint": "/api/ask",
  "interpretation": "rules",
  "items_returned": 9,
  "lines": [{"quantity": 20, "sku": "PL-CP-A4-80-NUSA"}],
  "model_configured": false,
  "outcome": "quoted",
  "quoted_total": "2,664.30",
  "request_chars": 17,
  "request_digest": "0a999b322e85046d",
  "snapshot": {"path": ".../data/catalog.duckdb", "products": 72, "price_tiers": 105,
               "freshness": {"age_human": "3h", "age_seconds": 12866.5, "stale": false,
                             "stale_after_hours": 24.0}},
  "stated_total": "2,664.30",
  "timestamp": "2026-10-26T12:52:48.183+00:00",
  "timings": {"interpret_ms": 1.103, "price_ms": 0.257, "search_ms": 0.109, "total_ms": 59.063}
}
```

| Field | Why it is there |
|---|---|
| `timestamp` | When, to the millisecond, in UTC |
| `endpoint` | Which path handled it — the four that quote or answer, plus `eval:N` for harness records |
| `interpretation` | `model`, `rules`, `mixed` or `structured`. Which interpreter actually served the request |
| `model_configured` | Whether a model was *available*. Distinguishes a deployment without a model from a fallback |
| `fallback_reason` | Present only when a model was configured and rules ran anyway. **This is the silent-degradation field** |
| `outcome` | `quoted`, `clarified`, `no_match`, `refused`, or `failed`. A closed vocabulary; anything else is rejected at construction |
| `candidates_considered` | How many products the filter examined |
| `items_returned` | How many were put in front of the customer |
| `quoted_total` | The engine's figure |
| `stated_total` | The figure the reply **actually printed**, parsed from the rendered text |
| `lines` | `[{sku, quantity}]`, so the total can be re-derived independently |
| `timings` | `interpret_ms`, `search_ms`, `price_ms`, `total_ms`. Always all four; a stage that did not run is `0.0`, not absent |
| `snapshot` | Which catalog answered: path, product count, tier count, build time, and a `freshness` block with the age and the stale flag. Every answer can be traced to the prices it used, and to how old those are |
| `request_chars` | Length of the request |
| `request_digest` | 16 hex characters: a **grouping aid, not anonymisation** |
| `turn_index` | Present only for a multi-turn request: its 1-based position in the conversation. Keeps single-turn and multi-turn traffic separable in the measures rather than blending two behaviours into one population |
| `carried_fields` | Present whenever `turn_index` is: which requirements came from earlier turns. An empty list means "this turn carried nothing", which is a different fact from "this was turn one" |

### What the record deliberately excludes

**The request text.** By default the record carries `request_chars` and
`request_digest` instead. This is the one place the spec overruled
`ANALYZE_01.md` §9a, which specified logging `raw_message`; the reasoning is
recorded in `BUG.md` as defect A11.

The digest is not anonymisation. A 16-character hash of a short string is
brute-forceable by anyone with a candidate list, and describing it as anything
else would be a claim someone eventually relies on. It exists to group repeated
identical requests, which is the one thing the text was needed for.

**Credentials.** There is no field that could hold one, and the three fields that
carry free text (`fallback_reason`, `error`, `request_text`) are redacted in the
record's own constructor. That matters because the realistic leak is not a field
someone added for a key — it is an **error message**. A provider client that
fails often interpolates the request it was building, and the request carries the
`Authorization` header. That message becomes `fallback_reason`, which lands in
the record.

Two passes catch it: the configured key values are replaced literally (they are
known, so they are certain to be caught), then credential-shaped patterns catch a
key that arrived by some other route. The replacement is `[redacted]`, so a
reader can tell an error was scrubbed rather than silently truncated.

### Opting into text capture

```bash
export PAPERLANE_RECORD_TEXT=1        # off by default
export PAPERLANE_RECORD_TEXT_MAX=200  # the bound; default 200
```

Off by default, and bounded when on. "Capture the text for debugging" must not
become "retain every conversation".

### Turning recording off

```bash
export PAPERLANE_RECORD_PATH=off
```

Requests still work; nothing is written. A record write failure — a full disk,
an unwritable path — never fails the request. Losing a record is bad; failing a
customer's quote is worse. The writer counts its own failures so a recorder that
drops everything is at least visible.

---

## 2. The five measures

All five are **derived from records on every read**. Nothing is incremented while
a request is being handled. The cost is an O(n) scan per read — microseconds at
this scale — and the benefit is that a metric cannot drift from the events it
claims to summarise. A counter and its log can disagree, and when they do you no
longer know which one is true.

```bash
./run.sh metrics
```

```
Records: 1  (p95 window: 1000)

  interpretation fallback rate     no data   (alarm above 20%)
  zero-result rate                    0.0%   (alarm above 10%)
  extraction review backlog              0   (alarm above 5)
  p95 latency                         42ms   (alarm above 2000ms)
  reply/total disagreement               0   (alarm above 0)
                                (1 checked)

  catalog age: 3h  (stale above 24h)
  outcomes: quoted=1
  interpretation: rules=1
```

`./run.sh metrics --json` gives the same as JSON; `GET /api/metrics` serves it
from the running service.

| Measure | Definition | Alarms above | Why it is worth watching |
|---|---|---|---|
| `fallback_rate` | Share of **model-eligible** requests served by the rule path | 20% | A rising share means the model is degrading and answers are quietly getting worse |
| `zero_result_rate` | Share of `quoted` + `no_match` requests that found nothing | 10% | Either a catalog gap or a parsing defect. The two look identical from outside |
| `review_backlog` | `open_review_items` + `carried_review_items` from the snapshot | 5 | A jump after a refresh means the site changed shape |
| `p95_latency_ms` | Nearest-rank p95 over the most recent N records (default 1000) | 2000 ms | An interactive assistant that responds slowly is not usable |
| `disagreement_count` | Replies whose printed total differs from an independently re-derived one | 0 | The only one that detects a **correctness** bug rather than a degradation |

### The catalog's age, which is reported rather than measured

`catalog age` is printed beside the review backlog because both are facts about
the **snapshot** rather than rates over records — a reader wants to know how old
the prices are regardless of how much traffic there was. It is deliberately **not**
a sixth derived measure: it is not computed from records, and adding it to the
table would blur what "derived on read" means.

```
  catalog age: 3h  (stale above 24h)
```

The same value travels in the JSON payload and in every API response, under
`snapshot.freshness`:

```json
"freshness": {"built_at": "2026-10-27 09:36:03.925543", "age_seconds": 4.4,
              "age_human": "just now", "stale_after_hours": 24.0, "stale": false}
```

Three details are deliberate.

- **It is reported, never gating.** A snapshot past the threshold is labelled, not
  withheld. A gate that refused to serve would fail exactly the deployment this
  exists to help — one that has a good but old catalog.
- **The stored timestamp is zone-less, and is read as UTC.** The crawl stamps it
  with `datetime.now(timezone.utc)` and DuckDB returns a naive `TIMESTAMP`. Read as
  local time in a UTC+7 deployment, a nine-hour-old catalog would look minutes
  old — the precise condition the signal exists to catch, inverted. That reading
  was only correct once the write side was fixed: DuckDB converts an aware value
  into the **session** timezone before storing it, so binding a UTC datetime
  directly stored local wall time and the age came out seven hours short, negative
  just after an ingest (defect A19). `catalog.stored_timestamp` now converts to UTC
  and drops the zone at every write site, so the column really holds what the
  reader assumes, whatever the host timezone is.
- **An unknown age is `None`, not `False`.** "Cannot tell" and "not stale" must not
  read the same, which is the same rule `criteria.py` applies to an unstated field.

### Three definitional choices that matter

**`fallback_rate`'s denominator is model-eligible requests, not all requests.** A
deployment with no model configured answers everything with rules, and that is
correct behaviour. Counting it as fallback would make the metric permanently
alarming and therefore ignored.

**`zero_result_rate` excludes clarifications and refusals.** A clarification is
the system correctly declining to guess; a refusal is the system correctly
declining to sell. Counting either as a miss would make the metric measure
questions rather than failures.

**p95 is nearest-rank, not interpolated.** With a small window an interpolated
p95 reports a duration between two observed requests — a number no request
experienced. The nearest-rank value is always a real measurement.

### An empty record set is not a healthy system

Every rate returns `null` rather than `0.0` when there is nothing to divide by,
and the payload says so in words:

```bash
$ PAPERLANE_RECORD_PATH=/tmp/none.jsonl ./run.sh metrics
No requests recorded yet — no metrics to report.
That is not a zero rate: a proportion over zero records would look like a
healthy system.
Records are written to /tmp/none.jsonl when the service handles a request.
```

`record_count` and `window` travel with the values for the same reason: a rate of
0% over 0 requests is indistinguishable from a perfect run unless you say which
you are reporting.

---

## 3. The disagreement metric

The reply contract is *supposed* to make a reply whose stated total differs from
the computed total impossible. "Supposed to be impossible" is exactly the kind of
claim that should be measured.

For every record whose reply printed a total, that figure is compared against
`evaluate.recompute_totals()` run on the same SKUs and quantities.
`recompute_totals` was written from the published pricing rules by independent
integer arithmetic and is separately asserted — by source inspection of its AST —
not to call `quote()`. So this compares two implementations, not a reply agreeing
with itself.

The tempting version — compare `reply.total` against `reply.quote.total` — is
worthless, because both come from the same object and always agree. It is
structurally incapable of failing.

**The metric reports how many replies it checked**, not just how many disagreed:

```
  reply/total disagreement               0   (alarm above 0)
                                (17 checked)
```

Without that, "0" over zero checked records and "0" over seventeen are the same
output, and they are opposite findings.

A record that printed a total but cannot be re-derived — no lines recorded, or a
SKU that is not in the catalog — is reported as a **disagreement with a reason**,
not skipped. Dropping the records that cannot be checked would make the metric
look better the less it was able to do.

### Measuring it on the recorded evaluation set

```bash
./run.sh eval            # writes one record per scored case
./run.sh metrics --eval  # reports over those records
```

```
Records: 24  (p95 window: 1000)

  interpretation fallback rate     no data   (alarm above 20%)
  zero-result rate                    5.0%   (alarm above 10%)
  extraction review backlog              0   (alarm above 5)
  p95 latency                      no data   (alarm above 2000ms)
  reply/total disagreement               0   (alarm above 0)
                                (17 checked)

  outcomes: clarified=2, no_match=1, quoted=19, refused=2
  interpretation: rules=24
```

**Observed on 2026-10-26: 0 disagreements over 17 checked replies.** That is a
measurement, not an expectation. The two basket cases have no rendered reply text
to parse, so they are not checked — which is why the checked count (17) is lower
than the quoted count (19) and is reported rather than hidden.

`p95 latency` reads `no data` on an eval run on purpose: the harness measures
correctness, not speed. A `0.0` timing would drag the p95 to zero and read as
"instant", so harness records carry no timing at all and the p95 skips them.

### Why the harness has its own log

`data/eval-records.jsonl`, not `data/requests.jsonl`. The eval set is a curated
sample chosen to exercise edge cases, so mixing it into the live log would drag
the fallback and zero-result rates toward whatever the case list happens to
emphasise. A rate over a mixture answers neither question. It also means the
harness can be re-run as often as you like without disturbing production numbers.

### One run, not a union of runs

The eval log accumulates across runs — including the negative-control run, whose
whole purpose is to fail. So each harness run stamps a `run_id` on its records,
and `metrics --eval` reports **the most recent run** rather than the whole file:

```
Records: 24  (p95 window: 1000)
Source: evaluation harness, run 20261026T134152080834
```

Without that, re-running the harness would silently change what the next read
reports, and running the negative control would poison the numbers. Name a
specific run with `--run`:

```bash
./run.sh metrics --eval --run 20261026T132901792721
```

An unknown run id reports no data rather than falling back to the latest — a
report that silently answers a different question than the one asked is worse
than one that answers nothing.

### The metric is shown able to fail

`tests/test_metrics.py::TestDisagreement` corrupts a reply's stated total and
asserts the count becomes non-zero and names the affected request. Without that
test, "reads zero" is indistinguishable from "never runs".

---

## 4. Known limitations

Stated plainly rather than half-built.

- **No log rotation.** `data/requests.jsonl` grows without bound. The remedy is
  manual (`rm` it, or move it aside); automatic rotation needs a retention
  policy, which is a bigger feature than this one.
- **p95 is over a count window, not a time window.** A burst can flush history.
  A time window needs a clock and a retention policy.
- **The eval log accumulates across runs.** `metrics --eval` reads only the most
  recent, but the file itself grows without bound and there is no pruning.
- **The digest is a grouping aid, not anonymisation.** A short hash of a short
  string is brute-forceable.
- **The metrics endpoint has no authentication.** It exposes outcome counts and
  latency, not customer data, but it is not intended for a public interface.
- **Redaction is pattern-based.** It catches the shapes it knows. A credential in
  an unusual format could still reach the log, which is why the structural
  guarantee — no field that could hold a key — matters more than the patterns.
- **A record is written after the response is computed, not before.** A process
  killed mid-request leaves no record. "One record per handled request" means
  every request that completed handling.

---

## 5. Where the code is

| Concern | File |
|---|---|
| Record schema, emission, redaction | `src/paperlane/records.py` |
| The five measures and their rendering | `src/paperlane/metrics.py` |
| Emission points | `src/paperlane/api.py` — `record()` and `_record_basket()` |
| Harness records | `src/paperlane/evaluate.py` — `_record_eval_run()` |
| Per-stage timing | `src/paperlane/assistant.py` — `answer()` |
| Tests | `tests/test_records.py`, `tests/test_metrics.py`, `tests/test_observability_api.py`, `tests/test_hygiene.py` |
