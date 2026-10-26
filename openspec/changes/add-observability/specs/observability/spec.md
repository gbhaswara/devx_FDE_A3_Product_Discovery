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

### Requirement: Metrics that reveal silent degradation are derivable

The system SHALL expose measures that distinguish a working system from one quietly answering worse, and each SHALL be derivable from the records rather than maintained by a separate counter.

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
- **THEN** end-to-end response latency is available at the 95th percentile, because an interactive assistant that responds slowly is not usable

#### Scenario: Answer and figure disagreement is measurable
- **WHEN** metrics are collected
- **THEN** the count of replies whose stated figures disagree with the computed figures is available, and is expected to remain zero

#### Scenario: Metrics are computed from records, not from counters
- **WHEN** a metric is compared against the records it is derived from
- **THEN** it equals what those records imply, so the metric cannot drift from the events it claims to summarise

#### Scenario: An empty record set reports as empty
- **WHEN** metrics are requested and no requests have been handled
- **THEN** the response states that there is no data, rather than reporting zero rates that would look like a healthy system

### Requirement: Secrets are never recorded

Credentials SHALL NOT appear in logs, records, or any reported output.

#### Scenario: Credentials are absent from records
- **WHEN** records are inspected
- **THEN** no credential, token, or key value appears in them, and this is asserted by a test rather than by inspection

#### Scenario: Credentials are supplied by environment only
- **WHEN** the system needs a credential to reach an external service
- **THEN** it reads it from the environment, and the value is never written to a file under version control

#### Scenario: A configured credential does not leak into a record
- **WHEN** a model call is made with a credential configured and the resulting record is inspected
- **THEN** the credential's value does not appear in the record, even in an error or fallback message

### Requirement: Recorded conversation content is limited

Conversation content SHALL NOT be retained beyond what the recorded evaluation set requires.

#### Scenario: Arbitrary conversation text is not retained
- **WHEN** a request is handled outside the recorded evaluation set
- **THEN** the full conversation text is not persisted as part of routine operation

#### Scenario: Request text is not persisted by default
- **WHEN** a request is handled
- **THEN** its full text is not written to the record, so routine operation does not accumulate customer conversations

#### Scenario: The record still supports the metrics without the text
- **WHEN** request text is withheld from the record
- **THEN** every required metric remains derivable, because the metrics depend on path, outcome, counts and timing rather than on wording

#### Scenario: Recording text is an explicit opt-in
- **WHEN** an operator chooses to capture request text for debugging
- **THEN** that requires an explicit configuration setting, and the record's content is bounded rather than unbounded

## ADDED Requirements

### Requirement: Reply and computed figure disagreement is measured independently

The system SHALL measure how often a reply's stated figures disagree with the figures computed for that reply, and SHALL derive the comparison independently of the reply's own rendering.

#### Scenario: Disagreement reads zero on a correct run
- **WHEN** the recorded evaluation set is run
- **THEN** the disagreement count is zero, and this is reported as a measured result rather than an expectation

#### Scenario: A corrupted reply is detected
- **WHEN** a reply's stated total is deliberately altered
- **THEN** the disagreement count becomes non-zero and identifies the affected request, so the metric is shown to be capable of failing

#### Scenario: The comparison is not the reply checking itself
- **WHEN** the disagreement metric is computed
- **THEN** the stated figure is parsed from the reply text and compared against an independently computed total, so a reply that consistently mis-states a figure cannot agree with itself

### Requirement: The metrics are reachable without reading a log file

Operational measures SHALL be available through the running service, so that they can be watched rather than mined.

#### Scenario: Metrics are served
- **WHEN** the service is running
- **THEN** the metrics are available from an endpoint without filesystem access

#### Scenario: Metrics can be printed
- **WHEN** an operator runs the metrics command
- **THEN** the five measures are printed with the record count they were derived from
