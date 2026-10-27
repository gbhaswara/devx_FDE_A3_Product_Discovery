# Spec Delta

## ADDED Requirements

### Requirement: The age of the catalog is reported

Every surface that reports the state of the catalog SHALL report how old it is, so
that stale data behind a correct engine is visible rather than indistinguishable
from fresh data.

#### Scenario: Health reports the catalog's age
- **WHEN** the health of the running service is inspected
- **THEN** the reported snapshot state includes the age of the catalog and whether it has exceeded a stated staleness threshold

#### Scenario: The age travels with what an answer was computed against
- **WHEN** a response reports the snapshot its figures were computed from
- **THEN** that snapshot description includes when it was built and whether it is stale

#### Scenario: Staleness is reported and does not block
- **WHEN** the catalog is older than the staleness threshold
- **THEN** the staleness is reported as a flag on the surfaces above, and responses continue to be served, because refusing to answer is a worse failure than answering from a catalog whose age is stated

#### Scenario: The threshold is stated and configurable
- **WHEN** the staleness threshold is inspected
- **THEN** it is a named value with a documented default rather than an implicit comparison
