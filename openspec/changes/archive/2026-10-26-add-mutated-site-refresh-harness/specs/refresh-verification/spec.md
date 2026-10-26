# Spec Delta

## Purpose

Makes the refresh path demonstrable rather than merely asserted, by generating a declared mutation of a known catalog site and proving that every injected change is reported under the correct change kind.

## ADDED Requirements

### Requirement: A catalog site can be mutated in a declared way

The system SHALL be able to produce a modified copy of a catalog site in which a known set of changes has been injected, and SHALL record what was injected.

#### Scenario: Mutation is declared before it is applied
- **WHEN** a mutated site is generated
- **THEN** a manifest states every change the generator intends to make, identifying the change kind and the item it affects

#### Scenario: The manifest is the verification's only expectation source
- **WHEN** a refresh against the mutated site is verified
- **THEN** the expected changes are read from the manifest, not reconstructed by inspecting the mutated site or by memory of the edit

#### Scenario: The unmutated site is preserved
- **WHEN** a mutated site is generated from a source site
- **THEN** the source site is left byte-identical, so the same mutation can be regenerated and the original remains available as a baseline

#### Scenario: Generation is repeatable
- **WHEN** the same mutation is generated twice from the same source
- **THEN** the result is identical both times, so a verification failure cannot be caused by non-determinism in the fixture

### Requirement: Every injected change appears in the refresh report

A refresh of a mutated site SHALL report each injected change in the change list that corresponds to its kind.

#### Scenario: Each change kind is reported
- **WHEN** the mutated site differs from the baseline by an addition, a withdrawal, a price change, a tier change, an availability change, and an unparseable page
- **THEN** the report places each one in its own list, with the item identified

#### Scenario: A change is not reported under the wrong kind
- **WHEN** an item's price changes but its tiers do not
- **THEN** it appears in the price change list and not in the tier change list, so the report attributes the change correctly rather than merely noticing something moved

#### Scenario: Values are reported with before and after
- **WHEN** a price or tier changes
- **THEN** the report states both the previous and the new value, so a reader can see the magnitude without consulting either snapshot

#### Scenario: Nothing is reported that was not injected
- **WHEN** a refresh of the mutated site completes
- **THEN** no item appears in a change list unless the manifest declares a change for it, so a spurious report is a failure rather than noise

### Requirement: The mutated catalog exercises behaviours the original cannot

A mutated site SHALL be able to contain data that the original site lacks, so that behaviours depending on such data are exercised rather than only unit-tested.

#### Scenario: A discontinued item becomes reachable
- **WHEN** the mutated site contains an item marked as discontinued
- **THEN** a search for that item reports it as discontinued rather than silently omitting it

#### Scenario: A page carrying an injected instruction is processed safely
- **WHEN** the mutated site contains a product page whose text includes an instruction addressed to an automated reader
- **THEN** that text is treated as product data, and does not alter the assistant's behaviour, its criteria, or its reply

#### Scenario: An unparseable page is surfaced rather than dropped
- **WHEN** the mutated site contains a page in a markup shape the extraction ladder does not recognise
- **THEN** the page appears in the review set and in the refresh report as a parse failure, and the catalog does not silently shrink by that item

#### Scenario: Shrinkage caused by a parse failure is distinguishable from a withdrawal
- **WHEN** an item disappears because its page could not be parsed
- **THEN** the report shows a parse failure for that page, and does not report the item as withdrawn, because the two mean different things to an operator

### Requirement: The demonstration is reproducible in one command

The end-to-end mutation and refresh demonstration SHALL be runnable by a reviewer without manually constructing files or chaining commands.

#### Scenario: One command runs the demonstration
- **WHEN** a reviewer runs the documented command on a clean checkout
- **THEN** it generates the mutated site, ingests it, compares it against the baseline, and reports whether every injected change was detected

#### Scenario: A missed change fails the demonstration
- **WHEN** any injected change is not reported, or is reported under the wrong kind
- **THEN** the command exits non-zero and names the discrepancy

#### Scenario: The demonstration does not require the original site to be served
- **WHEN** the demonstration runs
- **THEN** it serves the mutated copy it generated, so a reviewer is not required to stand up the original site first
