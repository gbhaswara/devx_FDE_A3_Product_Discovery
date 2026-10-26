# Design

## Context

See `proposal.md` — Why. This document records the technical decisions behind that scope; the behavioural contracts are in the eight specs under `specs/`.

Constraints that shape the approach, all verified during analysis (`ANALYZE_01.md` §12):

- **The reference site is static and small**: 36 product pages, 59 volume-pricing documents, 7 category pages. A full crawl is ~105 requests, ~105 seconds at the permitted rate.
- **Markup is inconsistent, not complex.** Four shapes, three price formats, four weight formats, two size encodings. There is no JavaScript-rendered content to fight except volume pricing, which is fetched from per-SKU documents.
- **Money must be exact and reproducible.** The whole assignment turns on prices being right, and a single wrong satang is a visible failure.
- **The language model is a cloud endpoint that has been observed to fail in specific, non-obvious ways** (see Decisions 6–8).
- **Scope is scored.** The brief plans ~6 hours and explicitly scores judgment about scope, so every component must be separable and the core must stand alone.

## Goals / Non-Goals

**Goals:**

- A single deterministic pricing path that every caller shares, so the assistant, the API, and the evaluation harness cannot disagree.
- Ingestion that degrades to a visible review set instead of dropping data, so a changed site is noticed rather than absorbed silently.
- A guarantee that products and prices cannot be invented, enforced by structure rather than by instruction.
- Tier 1 deliverable that is complete and demonstrable without any Tier 2 component.

**Non-Goals:**

- Multi-turn conversation memory. Single-turn with an explicit clarification step is the deliberate scope cut.
- Real embeddings or a vector store. Semantic similarity is a ranking tiebreak at most, and only if Tier 1 is complete.
- Authentication, authorisation, or multi-tenancy. This is a local demonstration service.
- Supplier onboarding for sites other than PaperLane. The extraction ladder is built for this site's four shapes plus a structured fallback.
- Production deployment topology. It runs locally, from a clean shell, in three commands.

## Decisions

### 1. Python with `Decimal`, integer satang, explicit half-up

All money is stored and computed as integer satang. Any rounding goes through an explicit half-up helper; nothing relies on default float behaviour or on a language's built-in rounding mode.

**Why:** the tax computation produces exact halves in realistic cases, and default rounding is half-even in Python. A silent half-even result would disagree with the customer's expectation and be extremely hard to spot.

**Alternative rejected:** floats with rounding at presentation time. Rejected because accumulated error is invisible until it produces a wrong total, and because it makes exact test expectations fragile.

### 2. DuckDB as the catalog store, rebuilt and swapped

The catalog lives in a DuckDB file. Each ingest builds a complete new file and atomically replaces the serving one.

**Why:** DuckDB permits one writer, and the rebuild-and-swap model removes that constraint instead of working around it. It also gives a failed ingest nowhere to damage a working catalog. It supports reading the site's JSON pricing documents directly, and its rounding functions match the required half-up semantics.

**Alternatives rejected:** SQLite (workable, but loses on exact rounding semantics and on the ergonomics of comparing two snapshots in one query); PostgreSQL (a server, credentials, and migrations for 72 products — and it breaks the "five commands or fewer" submission requirement); an in-memory store rebuilt per request (no snapshot history, so no diff).

### 3. FastAPI with one server-rendered page, same origin

The HTTP surface is FastAPI; the interface is a single page using progressive enhancement, served from the same process and origin.

**Why:** one process, one command, no build step, no cross-origin configuration. The submission requires running in five commands or fewer, and a separate frontend build would consume most of that budget for no scored benefit.

**Alternatives rejected:** a separate React/Next.js frontend (build step, two processes, cross-origin setup, more README commands, nothing the brief scores); a CLI only (the brief permits it, but a page makes the demo and the customer simulation materially easier to run).

### 4. A fallback ladder with a review floor, not a single parser

Extraction attempts each known shape in turn, then a structured model-assisted extraction for unrecognised markup, and finally records the page in a review set.

**Why:** the site's four shapes are stable, so a single shape-specific parser would be fastest — until the updated site in the demo round adds a fifth. The ladder converts "the site changed" from an exception into a review row. The review floor is the property that matters: no page may vanish.

**Alternative rejected:** one parser with LLM extraction for everything. Slower, non-deterministic, and it makes the catalog depend on the model being available — which contradicts the requirement that pricing and quoting work with no model.

### 5. The model emits criteria only; SKUs and prices never pass through it

The language model converts free text into structured requirements. Product selection, pricing, and justification are done by deterministic code. A post-generation assertion rejects any reply referencing a product outside the snapshot.

**Why:** this makes "no invented products" a structural property. The model has no channel through which to introduce a product or a figure, so the guarantee does not depend on prompt wording or on model behaviour.

**Alternative rejected:** letting the model compose the whole reply from tool results. It produces better prose, but it opens a channel for restated or invented figures, and detecting that reliably is harder than not having the channel.

### 6. The model endpoint is treated as unreliable by design

A rule-based interpretation path handles the common request shapes, and is used whenever the model is unreachable, slow, or returns unusable output. The response discloses which path was taken.

**Why:** the endpoint was measured failing in ways that return HTTP 200 with no usable content. Treating model availability as a hard dependency would mean an outage takes down quoting — which is unnecessary, because quoting never needed the model.

**Alternative rejected:** failing the request when the model fails. It converts a degraded answer into no answer, for a system whose most important output is deterministic anyway.

### 7. Model responses are sanitised before parsing

The endpoint appends a stray stream-terminator to otherwise valid JSON, so responses are stripped of that suffix before parsing. Requests set a generous output-token budget because the model spends tokens on internal reasoning before emitting content, and a small budget yields an empty result with a success status.

**Why:** both failure modes were reproduced and are silent — they look like "the model had nothing to say" rather than "the client is misconfigured". Structured-output request flags were also tested and made results worse, so they are not used.

**Alternative rejected:** a different model from the same gateway. Measured: one was rate-limited, the other took an order of magnitude longer and produced a wrong weight conversion.

### 8. Money never leaves the deterministic layer, so the API has two entry points

`POST /quote` accepts structured requirements and never calls the model; `POST /chat` accepts free text and does. Both share one pricing implementation.

**Why:** it separates interpretation failures from pricing failures. When an evaluation case fails, the entry point used tells you which layer is at fault. It also means the pricing tests and most of the evaluation set run with no model and no network.

### 9. Absent attributes are a filter-semantics concern, resolved at query time

Attributes that do not apply to a product are stored as not-applicable, and a constraint on such an attribute does not exclude the product.

**Why:** the naive implementation silently returns the wrong product set — right prices, wrong products — which no total-based assertion catches. Making this explicit at the query layer is the only place it can be fixed once.

### 10. `match_reasons` is a by-product of filtering, not a second computation

Each satisfied constraint appends its own record as the filter evaluates it. There is no separate justification step.

**Why:** a justification computed separately can disagree with the filter that produced the result. Deriving it from the evaluation makes disagreement impossible and costs nothing.

### 11. Justification and ranking are deterministic and totally ordered

Ranking has a defined order with a stable final tiebreak.

**Why:** an unstable order makes recorded expectations flaky and the demo non-reproducible. The evaluation set stores expected products, so order instability would show up as intermittent failures.

### 12. Two tiers, with the core gated

The build order is fixed: pricing before assistant, core before extras. Tier 2 items are independently droppable.

**Why:** the brief scores scope judgment. A complete, tested core is worth more than a broader, shakier system, and if the assistant slips the deterministic engine still stands.

## Risks / Trade-offs

- **A three-day build against a six-hour brief reads as scope indiscipline.** → Mitigation is structural, not rhetorical: two explicit tiers, every extra separable, and the README and customer summary state which is which. Framing reduces the risk; it does not eliminate it, and that is accepted.
- **The demo round ships an updated site, which may add a fifth markup shape.** → The ladder plus review floor means an unknown shape becomes a visible review row rather than a missing product. A self-built mutated site is exercised before the demo.
- **Two of the four required weight conversions have no example in the reference site.** → They are implemented from the agreed table, marked as unverified in the README, and exercised by the self-built mutated site. An unrecognised value raises rather than extrapolates.
- **Rule-based interpretation will miss paraphrases that the model handles.** → Accepted: the model path is tried first, rules are the fallback, and the fallback rate is measured so the degradation is visible rather than assumed.
- **Semantic search is a tiebreak only, so a purely descriptive request with no structured terms can miss.** → Documented as a known limitation; the structured path covers the request shapes the brief describes.
- **Single-turn only, so a follow-up correction starts over.** → Deliberate. An explicit clarification step is more reliable than half-built memory, and the trade-off is stated in the README.
- **A single writer store means concurrent ingests are not supported.** → Rebuild-and-swap makes this a non-issue: the serving file is only replaced, never written in place, and reads use a separate read-only connection per request.
- **The language model may change behaviour without notice.** → The rule path, the disclosed interpretation source, and the fallback-rate metric mean a change shows up as a metric movement rather than as a quiet quality drop.
- **The evaluation set encodes expectations, and a wrong expectation is worse than no test.** → Every expected total is recomputed from source data with exact arithmetic rather than transcribed, and cases that depend on absent data are recorded as not applicable rather than counted as passing.

## Migration Plan

Greenfield, so there is no migration in the compatibility sense. The deployment sequence is:

1. Stand up the package, the store, and the pricing layer; load a snapshot; verify the hand-computed totals in `ANALYZE_01.md` §5.
2. Add search, then the assistant, then the API surface.
3. Add the refresh path and the diff report; rebuild from source and confirm the snapshot reproduces.
4. Run the evaluation set and record results, including failures.
5. Only then add Tier 2 items.

Rollback is inherent: the previous snapshot file is untouched by a failed ingest, and the committed snapshot can be restored by reverting one file.
