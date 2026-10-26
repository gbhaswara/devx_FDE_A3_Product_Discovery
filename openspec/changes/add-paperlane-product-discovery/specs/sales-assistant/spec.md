# Spec Delta

## Purpose

Answers a customer's request with matching products, the reason each one matches, and a complete price breakdown, while knowing when to ask a question, when to admit nothing fits, and when to refuse.

## ADDED Requirements

### Requirement: A request is converted into validated criteria before anything is priced

Free-text requests SHALL be interpreted into a structured set of requirements, and that interpretation SHALL be validated against the catalog's vocabulary before use.

#### Scenario: Valid request becomes criteria
- **WHEN** a customer describes what they need
- **THEN** the system produces a structured set of requirements covering the attributes mentioned

#### Scenario: Unrecognisable interpretation is not acted on
- **WHEN** the interpretation fails validation
- **THEN** the system does not proceed to pricing, and instead asks for clarification

### Requirement: Criteria parsing falls back to rules when the model is unavailable

Interpretation SHALL NOT depend on a single external service. When the language model cannot be reached or does not return usable output, a rule-based interpretation SHALL take over for requests it can handle.

#### Scenario: Model failure does not fail the request
- **WHEN** the language model is unreachable, times out, or returns nothing usable
- **THEN** the request is still handled, and the response states that the interpretation was rule-based

#### Scenario: Rule failure degrades to a question
- **WHEN** both the language model and the rule-based interpretation cannot produce usable criteria
- **THEN** the system asks the customer for the missing detail rather than guessing or erroring

### Requirement: The reply contains matching products, the reason for each match, and a price breakdown

A successful reply SHALL present the matching products together with a per-product justification and a complete cost breakdown.

#### Scenario: Reply states why each product matches
- **WHEN** products are returned
- **THEN** each is accompanied by the specific requirements it satisfies and the values found

#### Scenario: Reply contains a complete breakdown
- **WHEN** a price is presented
- **THEN** the unit price, quantity, subtotal, delivery, tax and total are all stated

#### Scenario: Breakdown identifies any discount applied
- **WHEN** a volume tier or sale price determined the unit price
- **THEN** the breakdown identifies which one applied, so the customer can see why that figure was used

### Requirement: The assistant asks rather than guesses when a missing detail changes the answer

When a requirement is needed to answer correctly, is absent from the request, cannot be inferred from the catalog, and would change the result, the assistant SHALL ask for it. It SHALL NOT ask about details that do not affect the answer.

#### Scenario: Missing quantity is requested when it changes the price
- **WHEN** a request states a per-unit budget but omits the quantity, and quantity determines the unit price
- **THEN** the assistant asks for the quantity before quoting

#### Scenario: Detail that cannot change the answer is not requested
- **WHEN** a requirement is not applicable to the goods requested, or only one value exists in the catalog
- **THEN** the assistant does not ask about it and proceeds

#### Scenario: Questions are limited and specific
- **WHEN** the assistant needs more than one detail
- **THEN** it asks for no more than two at once, and names the details it needs

### Requirement: The assistant never presents a product that is not in the catalog

Every product referenced in a reply SHALL exist in the catalog snapshot in use. This SHALL be enforced structurally, by ensuring the model cannot introduce products, and verified before the reply is returned.

#### Scenario: Model cannot introduce a product
- **WHEN** the assistant composes a reply
- **THEN** products are selected by the deterministic search layer, and the language model supplies only the surrounding prose

#### Scenario: Unknown reference is caught before the reply is sent
- **WHEN** a reply would reference a product absent from the current snapshot
- **THEN** that reference is removed, the event is logged, and the reply is not sent as if valid

### Requirement: Unavailable products are refused, not offered

Products that are out of stock or discontinued SHALL NOT be presented as purchasable.

#### Scenario: Out-of-stock item is refused with its restock information
- **WHEN** the only suitable product is out of stock
- **THEN** the assistant states that it is unavailable, gives any stated return date, and does not quote it as a purchase

#### Scenario: Discontinued item is refused as withdrawn
- **WHEN** a suitable product has been discontinued
- **THEN** the assistant states that it is no longer available, distinctly from a temporary stock shortage

### Requirement: The assistant states when nothing fits, and offers labelled alternatives

When no product satisfies the request, the assistant SHALL say so plainly and SHALL offer alternatives that are clearly presented as not matching, each naming the requirement that was relaxed.

#### Scenario: No match is stated plainly
- **WHEN** no product satisfies the stated requirements
- **THEN** the reply says that nothing matches, rather than presenting a partial match as a match

#### Scenario: Alternatives name what was relaxed
- **WHEN** alternatives are offered
- **THEN** each states which requirement was relaxed and what the difference is, so the customer can judge whether it is acceptable

### Requirement: A stated budget is reported honestly against the computed price

Where a customer states a budget, the reply SHALL state whether the result is within it, based on the computed unit price at the requested quantity, and SHALL make the basis of that comparison explicit.

#### Scenario: Within-budget result says so
- **WHEN** the computed unit price at the requested quantity is within the stated budget
- **THEN** the reply states that it is within budget

#### Scenario: Over-budget result says so, and by how much
- **WHEN** the computed unit price at the requested quantity exceeds the stated budget
- **THEN** the reply states that it exceeds the budget and by how much, and does not present it as satisfying the budget

### Requirement: The assistant's stated figures match the computed figures

Any amount appearing in the reply text SHALL agree with the deterministically computed amounts. A discrepancy SHALL be treated as a defect.

#### Scenario: Stated total equals computed total
- **WHEN** a reply states a total
- **THEN** it equals the total produced by the pricing layer for the same request

#### Scenario: Disagreement is detected and logged
- **WHEN** the reply text and the computed amounts disagree
- **THEN** the discrepancy is detected before the reply is returned and recorded as an error condition

### Requirement: Replies are usable by a salesperson

The reply SHALL be written as something a salesperson could forward to a customer: it SHALL avoid internal identifiers as the primary description, SHALL use the product names and units the catalog uses, and SHALL be free of raw internal structure.

#### Scenario: Products are named as the catalog names them
- **WHEN** a product appears in a reply
- **THEN** it is described by its catalog name, with its identifier available but not presented as the description

#### Scenario: Units match the catalog's unit for the product
- **WHEN** a reply refers to a quantity
- **THEN** it uses the unit the product is actually sold in
