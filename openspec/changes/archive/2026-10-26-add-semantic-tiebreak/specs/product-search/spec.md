# Spec Delta

## MODIFIED Requirements

### Requirement: Ranking is deterministic

Result order SHALL be fully determined by the request and the catalog snapshot, with no dependence on iteration order or randomness, so that repeated runs and recorded expectations stay stable.

#### Scenario: Repeated identical searches return the same order
- **WHEN** the same request is run twice against the same snapshot
- **THEN** the results appear in the same order both times

#### Scenario: Ties are broken by a defined rule
- **WHEN** two items are equal on every ranking criterion
- **THEN** a defined tiebreak decides their order consistently

#### Scenario: Determinism survives an optional ranking term
- **WHEN** an optional similarity term is part of the ranking
- **THEN** order remains fully determined, because the term is a pure function of the request text and the snapshot, and the final tiebreak still guarantees a total order

#### Scenario: Ranking order is stated and matches the implementation
- **WHEN** the documented ranking order is compared with the implemented one
- **THEN** they agree, so the ranking rule is not merely implied by the sort key

### Requirement: Soft preferences rank results without excluding them

Where a customer expresses a preference rather than a requirement, it SHALL influence ordering and SHALL NOT remove items from the result.

#### Scenario: Preference affects order only
- **WHEN** a customer expresses a preference that no item fully satisfies
- **THEN** items are still returned, ordered by how closely they meet it

#### Scenario: Cheapest qualifying option ranks first
- **WHEN** several items satisfy every stated requirement and no preference distinguishes them
- **THEN** the cheapest at the requested quantity is returned first

#### Scenario: A similarity preference cannot exclude a qualifying item
- **WHEN** a customer's wording is far from every qualifying item's description
- **THEN** all qualifying items are still returned, because similarity orders them and does not filter them
