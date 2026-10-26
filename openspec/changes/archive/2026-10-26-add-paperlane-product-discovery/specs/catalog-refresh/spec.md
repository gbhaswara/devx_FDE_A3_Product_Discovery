# Spec Delta

## Purpose

Makes re-ingesting an updated catalog a routine operation rather than a code change, and makes the result of that re-ingest visible and auditable.

## ADDED Requirements

### Requirement: Re-ingest requires no code changes

Ingesting an updated version of the site SHALL require only running the ingest operation again, with no modification to the system.

#### Scenario: Changed site is absorbed without edits
- **WHEN** the site changes its prices, adds products, withdraws products, or alters markup within the supported shapes
- **THEN** a new ingest reflects those changes without any code modification

#### Scenario: Source location is configurable
- **WHEN** the site is served at a different address
- **THEN** the ingest accepts that address as an argument rather than requiring an edit

### Requirement: A new snapshot is built separately and swapped in atomically

Ingestion SHALL build a complete new catalog snapshot and replace the serving snapshot only after the build succeeds, so that a failed ingest cannot leave a partially written or corrupted catalog in use.

#### Scenario: Failed ingest leaves the working catalog intact
- **WHEN** an ingest fails partway through
- **THEN** the previously serving catalog remains readable and unchanged

#### Scenario: Readers are unaffected by a swap
- **WHEN** a new snapshot replaces the current one while the service is serving requests
- **THEN** in-flight and subsequent reads continue to succeed against a consistent snapshot

### Requirement: The result of a refresh is reported as a diff

Each refresh SHALL report what changed relative to the previous snapshot, grouped by kind of change.

#### Scenario: All change kinds are reported
- **WHEN** a refresh completes and a previous snapshot exists
- **THEN** the report lists added items, withdrawn items, changed prices with before and after values, changed availability, and pages that failed to parse

#### Scenario: No change is reported as no change
- **WHEN** a refresh produces identical data to the previous snapshot
- **THEN** the report states that nothing changed, rather than reporting a failure or an empty success

### Requirement: A page that cannot be parsed becomes visible, not absent

A page that fails extraction SHALL appear in the review set and in the refresh report, so that a catalog that has silently shrunk is detectable.

#### Scenario: Parse failure appears in the report
- **WHEN** a page cannot be parsed during a refresh
- **THEN** it is listed in the refresh report as a parse failure and recorded for review

#### Scenario: Shrinkage is detectable
- **WHEN** a refresh yields fewer items than the previous snapshot
- **THEN** the difference is reported explicitly, so a silent loss of products cannot pass unnoticed

### Requirement: The review set persists across refreshes until resolved

Items recorded for review SHALL remain visible until they are resolved, rather than being discarded at the next ingest.

#### Scenario: Unresolved review items remain listed
- **WHEN** a subsequent ingest runs while earlier review items remain unresolved
- **THEN** those items are still reported until they are resolved or explicitly cleared

### Requirement: A usable snapshot is available without crawling

The system SHALL be able to start from a stored catalog snapshot, so that the service can be examined without first performing a crawl.

#### Scenario: Service starts from a stored snapshot
- **WHEN** the service is started and a stored snapshot exists
- **THEN** it serves from that snapshot without requiring an ingest

#### Scenario: Rebuilding from source remains possible
- **WHEN** the stored snapshot is absent or the operator chooses to rebuild
- **THEN** the catalog can be reconstructed from the site by running the ingest
