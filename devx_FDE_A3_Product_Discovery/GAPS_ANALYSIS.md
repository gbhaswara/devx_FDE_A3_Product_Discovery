# Gap Analysis — PaperLane Product Discovery

## 1. The most important gaps

### 1. Stale or incorrect catalog data

**Severity: Critical**

The pricing engine can calculate perfectly using outdated prices, incorrect stock information, or an incomplete crawl.

**Impact:** customers receive mathematically correct but commercially incorrect quotes.

### 2. API and deployment security

**Severity: Critical**

The document describes API endpoints but does not establish authentication, authorization, rate limiting, or abuse protection.

**Impact:** unauthorized use, resource exhaustion, or exposure of internal data if those controls are absent.

### 3. Catalog consistency across refreshes

**Severity: High**

Atomic replacement prevents readers from seeing a half-written database, but it does not by itself prove that the new catalog is complete, fresh, or semantically correct.

**Impact:** a bad but structurally valid snapshot could replace a good one.

### 4. Incorrect interpretation of customer intent

**Severity: High**

Typed criteria and aliases constrain what the LLM can do, but a valid criterion can still be semantically wrong.

**Impact:** the system can produce a valid quote for the wrong requirements.

### 5. Pricing policy and quote validity

**Severity: High**

The documented pricing rules are deterministic, but the document does not establish whether all supplier-specific exceptions, quote expiry rules, or concurrent price changes are handled.

**Impact:** a correct quote at calculation time may not be a valid price when the customer orders.

These five areas would be my first priorities before treating the system as a production sales assistant.

## 2. Gaps by system layer

Here is the more detailed breakdown of what could go wrong and how I would address it.

### A. Data ingestion and catalog

| Gap | Why it matters | Recommended improvement |
|---|---|---|
| Partial crawl mistaken for a complete catalog | A failed request could leave products or prices missing. | Define completeness checks and block publication when critical thresholds fail. |
| Stale source data | Supplier prices and stock can change between refreshes. | Record freshness, last successful refresh, and source timestamps; alert on stale data. |
| Incorrect extraction without a parsing error | A parser may extract a plausible but incorrect value. | Add schema validation, source-to-field checks, and anomaly detection. |
| Review rows accumulate | Unresolved products may remain unavailable indefinitely. | Track review status, ownership, and resolution time. |
| Catalog rollback is not fully described | An atomic swap does not guarantee that a bad snapshot can be safely rolled back operationally. | Validate before publishing and test automated rollback to the previous known-good snapshot. |
| Source website changes unexpectedly | A changed page layout or pricing document can invalidate assumptions. | Add canary checks, crawl-diff alerts, and refresh failure notifications. |

The document already addresses several of these concerns through review rows, cross-checks, provenance, and snapshot replacement. The main question is whether those mechanisms have sufficiently strong operational acceptance criteria.

Particularly important: distinguish a successful crawl from a complete, trustworthy catalog. HTTP success alone does not establish data correctness.

### B. Search and product matching

The search layer is deliberately strict, but strictness has its own failure modes.

| Gap | Potential failure | Improvement |
|---|---|---|
| Incomplete aliases | A valid customer expression is not recognized. | Expand the alias test set using real or representative customer queries. |
| Ambiguous measurements | A size, weight, or unit is interpreted incorrectly. | Normalize units explicitly and ask when conversion is unsupported. |
| Limited relaxation policy | The system may suggest alternatives that are technically close but commercially unsuitable. | Evaluate alternative quality and show exactly what changed. |
| Missing product attributes | A product might be excluded because its attributes are unknown. | Define field-specific policies for unknown, not applicable, and confirmed mismatch. |
| Ranking by price margin | Cheapest-first may not reflect customer preferences beyond the hard constraints. | Add only measured, explainable preferences and retain hard-filter guarantees. |

One subtle risk is that validating the criteria is not the same as validating the interpretation.

For example, if a customer requests A4 but the LLM mistakenly extracts A3, the criteria may still pass validation. The search engine could then return a perfectly valid A3 quote for the wrong request.

The remedy is to test interpretation accuracy separately from search accuracy, especially for ambiguous and multi-constraint requests.

### C. LLM and conversation memory

The document's biggest strength here is that the LLM cannot directly author authoritative pricing data. However, that does not eliminate errors at the interpretation boundary.

Potential gaps include:

- **Incorrect but valid criteria:** The model chooses the wrong size, quantity, budget, or colour meaning.
- **Incomplete fallback coverage:** Rule-based parsing works without an LLM, but it may not understand every supported phrasing.
- **Unclear confidence policy:** The document does not establish a calibrated confidence threshold for automatically accepting interpretations.
- **Conversation context conflicts:** A new request may contradict an earlier requirement, such as changing from A4 to A3.
- **Stale remembered requirements:** A quantity or budget from an earlier turn could unintentionally carry into a new request.
- **Prompt injection:** Customer text may contain instructions intended to alter system behavior. Typed criteria reduce the impact, but input handling and model-client boundaries still require security testing.

The document does describe typed criteria merging and tests designed to preserve single-turn behavior. Those are good safeguards, but they do not prove that every multi-turn conversation is interpreted correctly.

My recommendation: Treat interpretation as a decision requiring validation, not merely a parsing operation. Test whether the system understands the customer's intended requirements before measuring whether it selects the correct product.

### D. Pricing and commercial rules

This is the most important business-logic review after catalog correctness.

The existing design already handles bulk tiers, integer monetary arithmetic, delivery thresholds, VAT, and explicit budget comparisons. The remaining questions concern the boundaries around those rules.

| Potential gap | Question to resolve |
|---|---|
| Tax policy | Is the 7% VAT rule appropriate for the actual supplier, product, and transaction? |
| Discount precedence | Are sale prices always exclusive of volume discounts under the real commercial agreement? |
| Quantity validation | What happens for zero, negative, extremely large, or non-integer quantities? |
| Delivery policy | Are there other delivery zones, fees, exemptions, or order conditions? |
| Quote expiry | How long is a generated quote valid? |
| Price changes | Can the source price change between quote generation and order placement? |
| Multiple lines | Are duplicate SKUs merged or independently calculated? |
| Monetary limits | Can large quantities or many lines overflow limits or cause unreasonable computation costs? |

These are questions for verification, not confirmed defects.

The document's rules are based on the assignment's specified policy. Before commercial deployment, those rules must be reconciled with the real supplier's terms.

### E. API and deployment

The document identifies three endpoints:

- `POST /api/ask`
- `POST /api/quote`
- `POST /api/quote/lines`

It explains their pricing and interpretation behavior, but the document does not establish the following operational controls.

| Area | What should be verified |
|---|---|
| Authentication | Who is allowed to call the API? |
| Authorization | Can different callers access only the operations and data they need? |
| Rate limiting | Can an anonymous or abusive client exhaust resources? |
| Request validation | Are malformed inputs, oversized payloads, and invalid quantities rejected? |
| Timeouts | What happens when the LLM endpoint or source service is slow? |
| Idempotency | If a client retries a request, are duplicate side effects prevented where applicable? |
| API versioning | Can response changes break existing consumers? |
| Secrets | Are API keys and credentials kept out of source control and logs? |
| Network security | Are public endpoints and internal services appropriately separated? |

Not all of these controls are necessary for a small local demo. They become much more important when the API is publicly accessible or integrated with a real ordering workflow.

### F. Observability and evaluation

The project already includes an evaluation harness and a Tier 2 observability enhancement. That is a good foundation, but an evaluation suite and production monitoring solve different problems.

I would verify whether the implementation measures:

- Catalog freshness and crawl completeness.
- Review-row counts and unresolved critical fields.
- Interpretation success, fallback frequency, and clarification rates.
- Product-match accuracy independently of pricing accuracy.
- API latency, error rates, timeouts, and model-provider failures.
- Price or stock discrepancies discovered after quotes are issued.
- Regression rates when the catalog or interpretation logic changes.

A further risk is evaluation-set overfitting. A system may pass its 28 ranking cases while performing poorly on new requests, unfamiliar phrasing, or unusual catalog changes.

To address that, keep separate test sets for routine regression testing, unseen customer requests, and deliberately adversarial edge cases.

## The biggest architectural blind spot

There is one broader issue that connects almost every gap:

PaperLane verifies that its calculations and responses are internally consistent, but internal consistency is not the same as external truth.

For example:

1. The crawler extracts a price of ฿120.
2. The catalog stores ฿120 correctly.
3. The pricing engine calculates a total correctly.
4. The response guards confirm the numbers match the catalog.
5. The supplier had actually changed the price to ฿130 before the crawl completed.

Every internal check might pass, yet the customer receives an outdated quote.

The solution is not to give the LLM more responsibility. It is to strengthen the data freshness, validation, and commercial verification around the deterministic core.
