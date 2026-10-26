# Spec Delta

## Purpose

Answers a customer's request with matching products, the reason each one matches, and a complete price breakdown, while knowing when to ask a question, when to admit nothing fits, and when to refuse.

## MODIFIED Requirements

### Requirement: A request is converted into validated criteria before anything is priced

Free-text requests SHALL be interpreted into a structured set of requirements, and that interpretation SHALL be validated against the catalog's vocabulary before use.

#### Scenario: Valid request becomes criteria
- **WHEN** a customer describes what they need
- **THEN** the system produces a structured set of requirements covering the attributes mentioned

#### Scenario: Unrecognisable interpretation is not acted on
- **WHEN** the interpretation fails validation
- **THEN** the system does not proceed to pricing, and instead asks for clarification

#### Scenario: A refinement is converted using the earlier requirements
- **WHEN** a customer refines an earlier request in the same conversation
- **THEN** the requirements used for pricing include the earlier requirements the refinement did not contradict

#### Scenario: A refinement is validated as a whole
- **WHEN** requirements are combined from more than one turn
- **THEN** the combined set is validated in full before anything is priced

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

#### Scenario: Remembered requirements are distinguished from current ones
- **WHEN** a reply is produced from requirements that include earlier turns
- **THEN** it states which requirements came from earlier turns

### Requirement: The assistant never presents a product that is not in the catalog

Every product referenced in a reply SHALL exist in the catalog snapshot in use. This SHALL be enforced structurally, by ensuring the model cannot introduce products, and verified before the reply is returned.

#### Scenario: Model cannot introduce a product
- **WHEN** the assistant composes a reply
- **THEN** products are selected by the deterministic search layer, and the language model supplies only the surrounding prose

#### Scenario: Unknown reference is caught before the reply is sent
- **WHEN** a reply would reference a product absent from the current snapshot
- **THEN** that reference is removed, the event is logged, and the reply is not sent as if valid

#### Scenario: Merging does not invent a product
- **WHEN** a reply is produced from requirements combined across turns
- **THEN** every product it presents exists in the catalog snapshot in use
