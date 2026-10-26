# semantic-ranking Specification

## Purpose
Orders results that already satisfy every stated requirement by how closely an item's description matches the customer's wording, so that among equally-valid items the most apt one comes first, without ever changing which items are returned.

## Requirements

### Requirement: Similarity orders results without changing the result set

A similarity score SHALL influence only the order of items that already satisfy every hard requirement. It SHALL NOT cause an item to be included that filtering excluded, nor cause an included item to be dropped.

#### Scenario: An item failing a hard requirement is never introduced
- **WHEN** similarity is enabled and an item does not satisfy a stated requirement
- **THEN** it does not appear in the results, regardless of how similar its description is to the request

#### Scenario: A qualifying item is never excluded
- **WHEN** similarity is enabled and an item satisfies every stated requirement
- **THEN** it appears in the results, regardless of how dissimilar its description is

#### Scenario: Membership is identical with and without the semantic layer
- **WHEN** the same request is run against the same catalog with similarity enabled and disabled
- **THEN** the set of returned items is identical, and only their order may differ

### Requirement: Similarity breaks ties among otherwise equal results

Where items are indistinguishable on the stated requirements and on availability, similarity SHALL decide their order.

#### Scenario: The closest wording ranks first
- **WHEN** several items satisfy every stated requirement and differ in how closely their description matches the request
- **THEN** the closest match is returned first

#### Scenario: Similarity does not override a stated preference for cheaper
- **WHEN** items satisfy every stated requirement and are distinguishable by price, with no preference expressed between them
- **THEN** the cheaper item ranks first, so the existing cheapest-first behaviour is not displaced by similarity

#### Scenario: Similarity is reported per item
- **WHEN** results are returned with similarity enabled
- **THEN** each item carries its similarity score, so the ordering can be inspected rather than taken on trust

### Requirement: Ranking remains deterministic with similarity enabled

Introducing a similarity score SHALL NOT make result order depend on anything other than the request and the catalog snapshot.

#### Scenario: Repeated requests return the same order
- **WHEN** the same request is run twice with similarity enabled against the same snapshot
- **THEN** both runs return the same order

#### Scenario: Equal similarity still resolves totally
- **WHEN** two items have identical similarity, availability and price
- **THEN** a further defined rule orders them, so no result order depends on iteration order

### Requirement: Similarity is optional and its absence is behaviour-preserving

The system SHALL operate with no similarity provider configured, and in that state SHALL behave exactly as it does without the capability.

#### Scenario: No provider configured produces the previous order
- **WHEN** no embedding provider is configured
- **THEN** results are ordered exactly as they were before this capability existed, and no network call is attempted

#### Scenario: A failing provider does not fail the request
- **WHEN** a provider is configured but unreachable or erroring
- **THEN** the request is still answered, using the ordering that applies without similarity, and the degradation is reported rather than silent

#### Scenario: The offline test suite requires no provider
- **WHEN** the test suite runs with no network access and no provider configured
- **THEN** it passes, so the semantic layer never becomes a prerequisite for verifying correctness

### Requirement: The benefit of similarity is measured, not asserted

Any claim that similarity improves result quality SHALL be accompanied by a measurement against the recorded evaluation set.

#### Scenario: Measurement is reported with its method
- **WHEN** the effect of similarity on result ordering is reported
- **THEN** the report states the number of cases affected, how the order changed, and the method used, so the claim can be checked

#### Scenario: No improvement is reported as no improvement
- **WHEN** similarity changes no ordering on the recorded set
- **THEN** that is reported plainly rather than presented as a benefit
