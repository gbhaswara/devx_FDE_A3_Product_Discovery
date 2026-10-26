# Tasks

## 1. Record format and emission

- [ ] 1.1 Define the record schema as a typed structure with fields for timestamp, endpoint, interpretation path, fallback reason, outcome, candidates considered, items returned, quoted total, per-stage timings, snapshot identity, request length and request digest — and verify a test asserts every field is present and that an unknown outcome value is rejected
- [ ] 1.2 Implement JSONL emission to a configurable path under a lock, and verify a test asserts two concurrent writers produce two well-formed lines rather than an interleaved one
- [ ] 1.3 Verify a record write failure does not fail the request: inject a write error and assert the request still returns its normal response and the failure is itself noted
- [ ] 1.4 Assert the record contains no credential when one is configured, and verify a test sets a sentinel credential, makes a model call, and asserts the sentinel appears nowhere in the record — including in any error or fallback message

## 2. Wiring into the request path

- [ ] 2.1 Emit a record from `/api/ask` capturing interpretation path, whether the model was configured, and the fallback reason, and verify a test asserts a model-configured request served by rules records a non-empty fallback reason
- [ ] 2.2 Emit records from `/api/quote`, `/api/quote/lines` and the HTML `/ask` fragment, and verify tests assert one record per handled request and that `/api/products`, `/api/health` and `/api/diff` produce none
- [ ] 2.3 Record a failed request with its failure reason, and verify a test asserts a validation error produces a record whose outcome is the failure rather than no record at all
- [ ] 2.4 Record per-stage timings separately (interpret, search, price) and verify a test asserts the three sum to no more than the total and that each is non-negative

## 3. Metrics derivation

- [ ] 3.1 Implement interpretation fallback rate as the proportion of records where the rule path served a model-configured request, and verify a test asserts a known set of records yields the exact expected proportion
- [ ] 3.2 Implement zero-result rate as the proportion of records whose outcome is no-match, and verify a test asserts clarification and refusal outcomes are **not** counted as zero-result, since they are different states
- [ ] 3.3 Implement the review backlog metric by reading `catalog.health()`'s open and carried review counts, and verify a test asserts the value equals what the snapshot reports rather than a cached figure
- [ ] 3.4 Implement p95 latency by nearest-rank over a bounded window of the most recent records, and verify tests assert the nearest-rank choice on a known sequence (including that it returns an observed value, not an interpolated one) and that an empty window reports no data rather than zero
- [ ] 3.5 Implement the metrics read path so that all values are derived from records on read with no counters incremented during handling, and verify a test deletes a record line and asserts the metric changes accordingly — proving the record is the source of truth

## 4. Disagreement metric

- [ ] 4.1 Implement extraction of the stated total from a reply's rendered text, and verify tests assert it parses the actual `Total` line format produced by `assistant.py` for single-item, multi-item, free-delivery and charged-delivery replies
- [ ] 4.2 Implement the comparison against `recompute_totals()` on the same SKUs and quantities, and verify a test asserts the metric reads zero across the whole recorded evaluation set
- [ ] 4.3 Verify the metric is genuinely independent by corrupting a reply's stated total and asserting the count becomes non-zero and names the affected request — without this test, "reads zero" is indistinguishable from "never runs"
- [ ] 4.4 Add a source-inspection test asserting the disagreement computation does not call the pricing engine, mirroring the existing guarantee for `recompute_totals`

## 5. Exposure

- [ ] 5.1 Add `GET /api/metrics` returning the five measures plus `record_count` and `window`, and verify a test asserts an empty record set reports as empty rather than as zero rates
- [ ] 5.2 Add `./run.sh metrics` printing the five measures with the record count they were derived from, and verify the command runs against a fresh repository and states plainly that there is no data
- [ ] 5.3 Verify the disagreement metric reads zero on a real `./run.sh eval` run and record the observed value, so the zero is a measurement rather than an expectation

## 6. Hygiene

- [ ] 6.1 Extend `tests/test_hygiene.py` to scan produced records for credential-shaped strings, and verify the scan runs as part of the normal test suite
- [ ] 6.2 Add a test asserting request text is absent from records by default, and that the digest and length fields are present instead
- [ ] 6.3 Add the opt-in text capture setting with a bounded maximum length, and verify a test asserts it is off by default and that when on the stored text is truncated at the bound
- [ ] 6.4 Verify the full suite still passes under `unshare -rn` with no network and no provider, recording the result

## 7. Documentation

- [ ] 7.1 Write `docs/observability.md` covering the record schema, the five metrics with the threshold at which each would alarm, the derivation-not-counter property, and what records deliberately exclude — and verify every command in it runs as written
- [ ] 7.2 Update `README.md` to add the metrics command and endpoint and to replace the "not built" entry for logging and metrics, and verify the documented run path still holds
- [ ] 7.3 Record the `ANALYZE_01.md` §9a conflict as a defect in `BUG.md`: the analysis specified logging raw request text, which the observability spec forbids, and the spec was followed — verify the entry states which source won and why
- [ ] 7.4 State the logging limitations plainly in `README.md`: no rotation, p95 over a count window rather than a time window, and the digest being a grouping aid rather than anonymisation
