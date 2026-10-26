# Spec Delta

## MODIFIED Requirements

### Requirement: The result of a refresh is reported as a diff

Each refresh SHALL report what changed relative to the previous snapshot, grouped by kind of change.

#### Scenario: All change kinds are reported
- **WHEN** a refresh completes and a previous snapshot exists
- **THEN** the report lists added items, withdrawn items, changed prices with before and after values, changed availability, changed volume pricing, and pages that failed to parse

#### Scenario: No change is reported as no change
- **WHEN** a refresh produces identical data to the previous snapshot
- **THEN** the report states that nothing changed, rather than reporting a failure or an empty success

#### Scenario: A change kind with no live sample is still demonstrable
- **WHEN** the catalog in use contains no item whose volume pricing or availability has changed
- **THEN** the system can still be shown to detect those change kinds, using a catalog constructed to contain them

#### Scenario: Each change is attributed to exactly one kind
- **WHEN** an item changes in more than one respect, or in only one
- **THEN** each change appears under the kind it belongs to, and a change of one kind does not also appear as another

### Requirement: A page that cannot be parsed becomes visible, not absent

A page that fails extraction SHALL appear in the review set and in the refresh report, so that a catalog that has silently shrunk is detectable.

#### Scenario: Parse failure appears in the report
- **WHEN** a page cannot be parsed during a refresh
- **THEN** it is listed in the refresh report as a parse failure and recorded for review

#### Scenario: Shrinkage is detectable
- **WHEN** a refresh yields fewer items than the previous snapshot
- **THEN** the difference is reported explicitly, so a silent loss of products cannot pass unnoticed

#### Scenario: An unparseable page is exercised against real markup
- **WHEN** the extraction ladder meets a page whose markup shape it does not recognise
- **THEN** the resulting review entry is produced from that page, rather than only from a synthetic row constructed in a test
