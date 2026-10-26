# Quote API Specification

## Purpose

Exposes the assistant and the pricing engine over HTTP with a stable contract, so that a user interface, an evaluation harness, and a demo can all drive the same behaviour without depending on internal structure.

## Requirements

### Requirement: A natural-language entry point returns a complete answer

The service SHALL accept a free-text request and return the reply together with the structured interpretation, the candidates considered, and the figures used.

#### Scenario: Request returns reply and structure
- **WHEN** a request is posted to the conversational endpoint
- **THEN** the response contains the reply text, the interpreted requirements, the candidates with their justifications and prices, and metadata describing the snapshot and timings

#### Scenario: Interpretation is visible for auditing
- **WHEN** a response is returned
- **THEN** the interpreted requirements are included, so a wrong answer can be traced to interpretation or to filtering

### Requirement: A structured entry point prices without interpretation

The service SHALL expose an endpoint that accepts already-structured requirements and returns the same candidate and price structure, without invoking a language model.

#### Scenario: Structured request bypasses the model
- **WHEN** structured requirements are posted to the quoting endpoint
- **THEN** the response is produced without any language-model call, and no reply prose is generated

#### Scenario: Structured quoting works with no model configured
- **WHEN** the quoting endpoint is used and no language-model credentials are available
- **THEN** it returns complete results rather than an error

### Requirement: Every response declares one of four outcomes

Each response SHALL declare exactly one outcome: a successful answer, a request for clarification, a report that nothing matched, or a refusal on availability grounds. Each outcome SHALL carry the fields its consumers need.

#### Scenario: Successful outcome carries candidates
- **WHEN** the outcome is a successful answer
- **THEN** the response includes at least one candidate with justification and price

#### Scenario: Clarification outcome carries the question
- **WHEN** the outcome is a request for clarification
- **THEN** the response includes the specific detail being requested

#### Scenario: No-match outcome carries alternatives
- **WHEN** the outcome reports that nothing matched
- **THEN** the response includes alternatives, each naming the requirement that was relaxed

#### Scenario: Refusal outcome carries the reason
- **WHEN** the outcome is a refusal
- **THEN** the response identifies the product and whether it is out of stock or discontinued

### Requirement: Invalid input is reported as a client error, never as a server failure

Malformed requests, implausible quantities, and requirements that fail validation SHALL be reported with a client error identifying the problem, and SHALL NOT produce an unhandled server error.

#### Scenario: Malformed request is a client error
- **WHEN** a request body cannot be parsed or is structurally invalid
- **THEN** the response is a client error naming the problem, and no stack trace is exposed

#### Scenario: Implausible quantity is rejected
- **WHEN** a quantity is missing, not a positive integer, or implausibly large
- **THEN** the response is a client error identifying the quantity as the problem

#### Scenario: Missing catalog is reported with a remedy
- **WHEN** a request arrives and no catalog snapshot is loaded
- **THEN** the response states that no snapshot is available and how to load one

### Requirement: An unavailable language model degrades the answer, not the service

If the language model cannot be reached, the service SHALL continue to serve requests, and SHALL indicate which interpretation path was used.

#### Scenario: Model outage yields a usable response
- **WHEN** the language model is unreachable and a request is posted
- **THEN** the response is still a normal outcome, produced by rule-based interpretation or a clarification request, not a server error

#### Scenario: Interpretation path is disclosed
- **WHEN** any response is returned
- **THEN** its metadata states whether the interpretation was model-based or rule-based

### Requirement: Catalog contents are inspectable

The service SHALL expose the normalised catalog for inspection, so that a disputed answer can be checked against the stored data.

#### Scenario: Products can be listed and filtered
- **WHEN** the catalog endpoint is queried, optionally with filters
- **THEN** the matching stored products are returned with their normalised attributes and provenance

### Requirement: Service state is reportable

The service SHALL report the state it is operating on, so that a failure can be attributed to the data or to the service.

#### Scenario: Health report identifies the snapshot in use
- **WHEN** the health endpoint is queried
- **THEN** it reports the snapshot identifier, the number of products loaded, whether the catalog is readable, and whether the language model is reachable

### Requirement: Changes between snapshots are reportable

The service SHALL expose the difference between the current catalog snapshot and the preceding one.

#### Scenario: Differences are reported by category
- **WHEN** the comparison endpoint is queried and a previous snapshot exists
- **THEN** the response reports added items, withdrawn items, changed prices, changed availability, and pages that failed to parse

#### Scenario: First snapshot is not an error
- **WHEN** the comparison endpoint is queried and no previous snapshot exists
- **THEN** the response reports that there is nothing to compare against rather than failing
