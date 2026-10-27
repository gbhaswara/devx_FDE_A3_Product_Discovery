# Spec Delta

## MODIFIED Requirements

### Requirement: Re-ingest requires no code changes

Ingesting an updated version of the site SHALL require only running the ingest
operation again, with no modification to the system.

#### Scenario: Changed site is absorbed without edits
- **WHEN** the site changes its prices, adds products, withdraws products, or alters markup within the supported shapes
- **THEN** a new ingest reflects those changes without any code modification

#### Scenario: Source location is configurable
- **WHEN** the site is served at a different address
- **THEN** the ingest accepts that address as an argument rather than requiring an edit

#### Scenario: Snapshot location is configurable
- **WHEN** an ingest of a different site must not disturb the committed catalog
- **THEN** the snapshot to build is named as an argument or an environment variable, and the committed catalog is left untouched

#### Scenario: A named snapshot can be served and evaluated
- **WHEN** the service or the evaluation is pointed at a named snapshot
- **THEN** it reads that snapshot rather than the committed one, and reports which snapshot it used
