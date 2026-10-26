# Spec Delta

## Purpose

Makes the assistant's behaviour observable in operation, so that quiet degradation is noticed from records rather than discovered by a customer, and so that claims about reply correctness are measured rather than asserted.

## MODIFIED Requirements

### Requirement: Each handled request produces a structured record

Every handled request SHALL produce exactly one structured record capturing how it was interpreted, what it returned, and how long each stage took.

#### Scenario: One record per request
- **WHEN** a request is handled successfully
- **THEN** exactly one record is written for it

#### Scenario: A failed request is also recorded
- **WHEN** a request fails validation or errors
- **THEN** a record is written stating that it failed and why, so failures are countable rather than invisible

#### Scenario: Record captures the interpretation path
- **WHEN** a request is handled
- **THEN** its record states whether interpretation was model-based or rule-based, and names a reason when the rule path served a request the model was configured to handle

#### Scenario: Record captures outcome and cost
- **WHEN** a request is handled
- **THEN** its record includes the outcome, the number of candidates considered, the number returned, the quoted total where one exists, the per-stage timings, and the identity of the snapshot in use

#### Scenario: Records are machine-readable
- **WHEN** records are written
- **THEN** each is a single structured entry suitable for aggregation, not free-form prose

#### Scenario: A multi-turn request is distinguishable from a single-turn one
- **WHEN** a request is handled as part of a conversation
- **THEN** its record states the turn's position in that conversation and which requirements were carried from earlier turns

#### Scenario: A single-turn request carries no conversation fields
- **WHEN** a request names no conversation
- **THEN** its record carries no turn position and no carried requirements, so single-turn traffic stays separable from multi-turn traffic
