# Spec Delta

## Purpose

Turns a customer's stated requirements into a ranked set of catalog items that actually satisfy them, and records why each one was selected so the assistant can justify a match without inventing a reason.

## ADDED Requirements

### Requirement: Stated requirements act as hard constraints

Requirements the customer states as needs SHALL be treated as filters that an item must satisfy to be returned as a match.

#### Scenario: Items violating a stated requirement are excluded
- **WHEN** a customer states a required size, finish, weight, or printing characteristic
- **THEN** items that contradict it are not returned as matches

### Requirement: Constraints on inapplicable attributes do not exclude items

Some attributes are meaningful only for some products. A constraint on such an attribute SHALL apply only to items for which that attribute is meaningful.

#### Scenario: A printing constraint does not exclude plain paper
- **WHEN** a customer's request includes a printing-related constraint and the catalog contains plain paper products that have no printing attributes
- **THEN** those plain paper products remain eligible rather than being excluded for lacking the attribute

#### Scenario: Inapplicable attributes are not silently treated as a match
- **WHEN** an item has no value for a constrained attribute because the attribute does not apply to it
- **THEN** the item is not described as matching that constraint, and the justification does not claim it does

### Requirement: Ambiguous wording is resolved by context, not by guessing

Some words carry different meanings in this catalog. Where a term could refer to more than one attribute, the system SHALL resolve it from the accompanying noun, and SHALL ask when the context is absent.

#### Scenario: The same adjective selects different attributes depending on the goods
- **WHEN** the term for colour is used with plain paper versus with printed goods
- **THEN** it selects the paper shade in the first case and the print colour mode in the second

#### Scenario: Missing context causes a question, not a guess
- **WHEN** the term could refer to either attribute and nothing in the request disambiguates it
- **THEN** the system asks which meaning was intended instead of choosing one

### Requirement: Common phrasings map onto catalog vocabulary

The system SHALL recognise everyday and trade phrasings for the same requirement, including alternative names for paper sizes, alternative names for paper weight systems, and printing notation used on the site.

#### Scenario: Size synonyms resolve to one size
- **WHEN** a customer refers to a paper size by its name, its imperial dimensions, or its common trade name
- **THEN** all resolve to the same size code

#### Scenario: Printing notation resolves to the same item set
- **WHEN** a customer describes two-sided full-colour printing using trade notation or in plain words
- **THEN** both descriptions select the same items

### Requirement: Soft preferences rank results without excluding them

Where a customer expresses a preference rather than a requirement, it SHALL influence ordering and SHALL NOT remove items from the result.

#### Scenario: Preference affects order only
- **WHEN** a customer expresses a preference that no item fully satisfies
- **THEN** items are still returned, ordered by how closely they meet it

#### Scenario: Cheapest qualifying option ranks first
- **WHEN** several items satisfy every stated requirement and no preference distinguishes them
- **THEN** the cheapest at the requested quantity is returned first

### Requirement: Ranking is deterministic

Result order SHALL be fully determined by the request and the catalog snapshot, with no dependence on iteration order or randomness, so that repeated runs and recorded expectations stay stable.

#### Scenario: Repeated identical searches return the same order
- **WHEN** the same request is run twice against the same snapshot
- **THEN** the results appear in the same order both times

#### Scenario: Ties are broken by a defined rule
- **WHEN** two items are equal on every ranking criterion
- **THEN** a defined tiebreak decides their order consistently

### Requirement: Every match carries a machine-readable justification

Each returned item SHALL include a structured record of which stated requirements it satisfies, giving the requested value and the item's actual value for each, so a justification is derived from the filtering that already happened rather than composed afterwards.

#### Scenario: Justification enumerates satisfied requirements
- **WHEN** an item is returned as a match
- **THEN** it carries one entry per stated requirement it satisfies, each naming the attribute, the value requested, and the value found

#### Scenario: Justification reflects the quantity actually priced
- **WHEN** a requirement depends on quantity, such as a per-unit budget
- **THEN** the justification states the quantity used and the resulting unit price, and identifies any tier applied

#### Scenario: Justification is produced without model involvement
- **WHEN** a match set is produced
- **THEN** the justification is generated from the filter evaluation itself, and no language model contributes to it

### Requirement: Unavailable items are identifiable in results

Items that are out of stock or discontinued SHALL be distinguishable from available items in any result set, so the assistant can refuse them rather than offering them.

#### Scenario: Unavailable items are marked
- **WHEN** an item that would otherwise match is unavailable
- **THEN** it is returned with its unavailability recorded, rather than being silently omitted or silently offered

### Requirement: A search that matches nothing reports that plainly

When no item satisfies the stated requirements, the system SHALL report that no match was found rather than returning a partial or loosely related set as though it matched.

#### Scenario: No qualifying item is reported as no match
- **WHEN** every candidate violates at least one stated requirement
- **THEN** the result is reported as no match, and no item is presented as satisfying the request

#### Scenario: Near misses are offered separately and labelled
- **WHEN** no item satisfies every stated requirement
- **THEN** the closest items are offered as alternatives, clearly distinguished from matches, and the requirement that was relaxed is named for each
