# Spec Delta

## Purpose

Makes the system's behaviour observable in operation, so that degradation is noticed from records rather than discovered by a customer.

## ADDED Requirements

### Requirement: Each handled request produces a structured record

Every request SHALL produce one structured record capturing what was asked, how it was interpreted, what was returned, and how long each stage took.

#### Scenario: Record captures the interpretation path
- **WHEN** a request is handled
- **THEN** its record states whether interpretation was model-based or rule-based, and why if it fell back

#### Scenario: Record captures outcome and cost
- **WHEN** a request is handled
- **THEN** its record includes the outcome, the number of candidates considered and returned, the quoted total where one exists, the per-stage timings, and the snapshot in use

#### Scenario: Records are machine-readable
- **WHEN** records are written
- **THEN** each is a single structured entry suitable for aggregation, not free-form prose

### Requirement: Metrics that reveal silent degradation are derivable

The system SHALL expose measures that distinguish a working system from one that is quietly answering worse.

#### Scenario: Interpretation fallback is measurable
- **WHEN** metrics are collected
- **THEN** the proportion of requests served by rule-based interpretation is available, because a rising share indicates the model is degrading unnoticed

#### Scenario: Zero-result rate is measurable
- **WHEN** metrics are collected
- **THEN** the proportion of requests that found nothing is available, because it indicates either a catalog gap or a parsing defect

#### Scenario: Extraction review backlog is measurable
- **WHEN** metrics are collected
- **THEN** the count of pages awaiting review is available, because an increase after a refresh indicates the site changed shape

#### Scenario: Latency is measurable
- **WHEN** metrics are collected
- **THEN** end-to-end response latency is available at a high percentile, because an interactive assistant that responds slowly is not usable

#### Scenario: Answer and figure disagreement is measurable
- **WHEN** metrics are collected
- **THEN** the count of replies whose stated figures disagree with the computed figures is available, and is expected to remain zero

### Requirement: Secrets are never recorded

Credentials SHALL NOT appear in logs, records, or any reported output.

#### Scenario: Credentials are absent from records
- **WHEN** records are inspected
- **THEN** no credential, token, or key value appears in them

#### Scenario: Credentials are supplied by environment only
- **WHEN** the system needs a credential to reach an external service
- **THEN** it reads it from the environment, and the value is never written to a file under version control

### Requirement: Recorded conversation content is limited

Conversation content SHALL NOT be retained beyond what the recorded evaluation set requires.

#### Scenario: Arbitrary conversation text is not retained
- **WHEN** a request is handled outside the recorded evaluation set
- **THEN** the full conversation text is not persisted as part of routine operation
