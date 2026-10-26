# Proposal

## Why

The assistant currently answers correctly or incorrectly with **no operational signal either way**. Nothing records which interpretation path served a request, how many candidates were considered, how long each stage took, or whether a reply's stated total matched the computed one. Every one of those is a failure mode that is invisible in the current system:

- The rule interpreter silently takes over when the model degrades. Answers get worse and nothing says so.
- A zero-result request is indistinguishable from a parse defect.
- The extraction review backlog can grow after a re-ingest with nothing surfacing it.
- A reply whose stated total disagrees with the computed total is a bug that the reply contract is *supposed* to make impossible — and "supposed to be impossible" is exactly the kind of claim that should be measured, because it is a one-line assertion if you have the records and a hunt if you do not.

The brief lists logging and metrics as a nice-to-have and asks what you would watch in production. A list of metrics is an opinion; a metric that reads zero on a real run because it is actually computed is evidence.

## What Changes

- A **structured request record**, one per handled request, machine-readable, carrying the interpretation path and why it fell back, the outcome, candidate counts, the quoted total where one exists, per-stage timings, and the snapshot in use.
- **Five metrics** derived from those records: interpretation fallback rate, zero-result rate, extraction review backlog, p95 end-to-end latency, and reply/computed-total disagreement rate.
- An endpoint exposing the metrics, and a command that prints them.
- **The disagreement metric is computed by re-deriving each reply's figures independently**, not by trusting the reply — otherwise it would measure whether the reply agrees with itself.
- **Log hygiene as a checked property**: a test that asserts no credential and no unbounded conversation text appears in records.

**BREAKING:** none. Records are written alongside existing responses; no response shape changes.

## Capabilities

### New Capabilities

- `observability`: the structured record per request, the five derived metrics, and the guarantees about what records must never contain.

### Modified Capabilities

- `observability` as specified in `add-paperlane-product-discovery`: that spec defines the requirements but none are implemented. This change's delta is written as ADDED against the existing capability path, because the target spec does not exist under `openspec/specs/` until the earlier change is archived — see the sequencing note in `design.md`.

## Impact

- **New code:** a records module (structured emission, no third-party logger), a metrics module (derivation from records), and wiring into `api.py` and `assistant.py`.
- **Modified code:** `api.py` gains a metrics endpoint and emits a record per request; `cli.py` gains a `metrics` command.
- **Storage:** records go to a file (JSONL) whose location is configurable; nothing is added to the DuckDB snapshot, because metrics are operational, not catalog, data.
- **Tests:** each metric must be shown derivable from records, and the disagreement metric must be shown to read zero on the evaluation run *and* non-zero when a reply is deliberately corrupted.
- **The load-bearing conflict to resolve:** `ANALYZE_01.md` §9a specifies logging `raw_message`. The `observability` spec's final requirement forbids retaining arbitrary conversation text. **These are incompatible**, and the spec wins: the record carries a bounded, non-identifying summary of the request rather than the text. This is recorded as a defect in the analysis rather than quietly resolved.
- **Risk:** a metrics module that computes from a source it also controls measures nothing. The disagreement metric is the one that matters and the one easiest to fake; it is designed to re-derive independently and is tested against a deliberate corruption.
