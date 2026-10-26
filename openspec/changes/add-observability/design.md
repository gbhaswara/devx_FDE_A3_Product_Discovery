# Design

## Context

See `proposal.md` — Why. Constraints that shape the approach:

- **`api.py` has six request handlers** (`/api/quote`, `/api/quote/lines`, `/api/ask`, `/api/products`, `/api/health`, `/api/diff`) plus two HTML routes (`/` and `/ask`). Only the three that quote or answer need a record; catalog inspection does not, and recording it would dilute the fallback and zero-result rates with traffic that cannot exhibit them.
- **`_meta()` already returns** `interpretation`, `elapsed_ms`, and `snapshot` for `/api/ask`. Much of the record's content is already computed per request — the record formalises it and adds the rest, rather than duplicating work.
- **`recompute_totals(lines)` already exists** in `evaluate.py` and computes subtotal, delivery, VAT and total by independent integer arithmetic from the catalog, deliberately *not* calling `quote()`. The disagreement metric can reuse this directly, which means the metric inherits the "does not call the pricing engine" property and its source-inspection test.
- **`assistant.py` renders totals** via `Money.format()` into the reply text (`Total         {order.total.format()}`). So a reply's stated total is parseable from the rendered text with a stable pattern, which is what makes an independent comparison possible.
- **`assistant.py` has `_allowed_amounts()`** (line ~371) which collects every amount the pricing layer produced, formatted as the reply formats it. There is already machinery for reasoning about amounts present in a reply.
- **`catalog.health()`** already reports `open_review_items` and `carried_review_items` — the review backlog metric is a read of existing state, not new bookkeeping.
- **The DuckDB connection must be per-request `read_only()`**; a shared connection across threads raises `Resource In Use Error`. Records must not introduce a shared mutable resource in the request path — a file append with a lock, or an append-only queue, is acceptable; a shared DB handle is not.

## Goals / Non-Goals

**Goals:**

- One structured record per handled request, sufficient to derive all five metrics.
- Metrics derived from records, not maintained separately.
- A disagreement metric that is genuinely independent and demonstrably able to fail.
- Log hygiene asserted by test.

**Non-Goals:**

- A full tracing or APM integration. The brief asks for what you would watch, not for OpenTelemetry.
- Retaining conversation text. Explicitly excluded by the spec.
- Dashboards. The endpoint and the command are the deliverable.
- Log rotation and retention policy. Stated as a known limitation instead.

## Decisions

### D1 — JSONL file, not a database table, and not stdout

**Chosen:** append one JSON object per line to a configurable path.

**Why:** metrics must be derivable by re-reading records, so the store must be readable and appendable without a server. JSONL is appendable with a single write, greppable, and trivially loadable. A DuckDB table would put operational writes into the catalog file, mixing two concerns with different lifecycles — and would hit the per-request connection constraint. Stdout is unusable for derivation after the fact unless captured, which pushes work onto the operator.

**Concurrency:** the append happens under a `threading.Lock` on a module-level handle. One lock around a line append is not a throughput concern at this scale and is far simpler than a queue. The lock protects only the write, never the request path.

### D2 — Record only the three quoting/answering endpoints

**Chosen:** `/api/quote`, `/api/quote/lines`, `/api/ask`, and the HTML `/ask` fragment.

**Why:** fallback rate and zero-result rate are meaningful only for requests that interpret and search. Including `/api/products` would dilute both with traffic that structurally cannot contribute. The spec's "each handled request" is read as each request that the assistant handles as a conversation or quote — a health check is not a handled request in the sense the metric needs.

### D3 — The record does not carry the request text by default

**Chosen:** the record carries `request_chars` (a length) and a `request_digest` (a short hash) instead of the text.

**Why:** this is the conflict the proposal names. `ANALYZE_01.md` §9a specifies logging `raw_message`; the observability spec forbids retaining arbitrary conversation text. **The spec is the higher authority** (`AGENTS.md` ranks the OpenSpec change above `ANALYZE_01.md`), so the analysis is wrong here and is recorded as a defect rather than quietly followed.

The digest preserves the one thing text was needed for — grouping repeated identical requests — without storing the text. An opt-in setting captures text when an operator needs it for debugging, bounded by a maximum length.

### D4 — Disagreement is measured by parsing the reply and re-deriving independently

**Chosen:** for each quoted reply, extract the stated total from the reply text, and compare it against `recompute_totals()` run on the same SKUs and quantities.

**Why:** the tempting implementation — compare `reply.total` against `reply.quote.total` — is worthless, because both come from the same object and will always agree. Parsing the rendered text and re-deriving through a different code path is the only version that can detect a rendering bug, which is precisely the class of bug the reply contract is meant to prevent.

**Reuse:** `recompute_totals()` already exists and is already asserted (by source inspection) not to call `quote()`. Reusing it means the metric cannot accidentally become a self-check.

**Testability:** the metric must be shown non-zero on a deliberately corrupted reply. Without that test, "reads zero" is indistinguishable from "never runs".

### D5 — p95 computed over a bounded window, and stated as such

**Chosen:** p95 over the most recent N records (N configurable, default 1000), using nearest-rank.

**Why:** p95 over all history is not a production metric — it stops responding to current behaviour. A bounded window is what an operator actually watches. Nearest-rank is chosen over interpolation because with small N an interpolated p95 is a number that no request experienced.

**Stated limitation:** the window is a count, not a time window, so a burst can flush history. Recorded as a known limitation rather than papered over.

### D6 — Metrics endpoint reports its own basis

**Chosen:** the response includes `record_count` and `window` alongside the five values.

**Why:** a rate of 0.0 over zero records looks identical to a healthy system. The spec requires an empty set to report as empty; including the count is how that is made visible rather than inferred.

### D7 — Metrics are derived on read, not accumulated

**Chosen:** no counters are incremented during request handling. The metrics command and endpoint read the records and compute.

**Why:** a counter and its log can disagree, and when they do, you no longer know which is true. Deriving on read makes the record the single source of truth and makes the spec's "computed from records, not from counters" scenario true by construction. The cost is O(n) per read, which at this scale is microseconds.

## Risks / Trade-offs

- **The metrics measure a system that is not the one being scored** (e.g. records from the eval harness rather than live traffic) → the record includes the snapshot identity and the interpretation path, and the eval run and the live run are distinguishable by it; the README states which produced the reported zero.
- **The disagreement metric silently never runs** because replies in the recorded set are all single-item and the parse pattern misses them → the corruption test is the guard, and it uses a real reply from the recorded set, not a synthetic one.
- **The record write becomes a failure source** — a full disk breaks the assistant → the write is wrapped so that a record failure logs and continues rather than failing the request. Losing a record is bad; failing a customer's quote is worse.
- **p95 over 1000 records is unstable on a small run** → the basis is reported alongside, and the limitation is stated.
- **Log growth is unbounded** → stated as a known limitation with a documented manual remedy; automatic rotation is out of scope and named as such rather than half-built.
- **The digest could be treated as a privacy guarantee it is not** → the digest is documented as a grouping aid, not as anonymisation, since a short hash of a short string is brute-forceable. Stated plainly.

## Migration Plan

Additive. Existing responses are unchanged; the metrics endpoint is new; the record file is created on first write at a configurable path, defaulting to a git-ignored location. Rollback is unsetting the path and disabling recording — no schema or data migration either way.

**Sequencing constraint (from `add-mutated-site-refresh-harness` design, restated because it applies here too):** `openspec/specs/` is empty until `add-paperlane-product-discovery` is archived, so this delta is written as ADDED against the `observability` capability path. After the first change is archived, this delta's requirements merge into the existing `observability` spec. If the earlier change is archived first, re-check this delta for duplicate requirement names before archiving.

**Resolved — the earlier change was archived first, and this delta was repaired.** The note above anticipated the problem and it arrived. When written, this delta was ADDED-only, because there was no main spec to modify. `add-paperlane-product-discovery` was then archived, creating `openspec/specs/observability/spec.md` with four requirements — three of which this delta independently declared as ADDED. `openspec validate` flagged only one (`Secrets are never recorded`, an exact name collision); the other three would have archived as silent near-duplicates under different names:

| Existing requirement | Was declared as |
|---|---|
| `Each handled request produces a structured record` | `...produces **one** structured record` |
| `Metrics that reveal silent degradation are derivable` | `The five degradation metrics are derivable from records` |
| `Recorded conversation content is limited` | `Conversation content is not retained beyond what evaluation requires` |

All four are now **MODIFIED**, keeping the existing header names, with each block carrying the union of the existing scenarios and this change's new ones — a MODIFIED requirement replaces the whole block, so anything omitted would be dropped at archive. Two requirements remain genuinely ADDED: the independent disagreement metric, and metrics reachable without reading a log file.

The merge also fixes a contradiction the main spec shipped with: its record requirement said a record captures *"what was asked"*, while its retention requirement said conversation text is not retained. The MODIFIED text resolves this to "how it was interpreted", and the retention scenarios state the digest-and-length position explicitly.

## Open Questions

None that would change the specs or the task breakdown. Log rotation is deliberately out of scope and recorded as a limitation.
