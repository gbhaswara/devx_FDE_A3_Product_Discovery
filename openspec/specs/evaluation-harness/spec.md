# Evaluation Harness Specification

## Purpose

Provides a recorded, reproducible measure of how well the assistant actually answers, so that claims about correctness rest on evidence rather than on demonstration.

## Requirements

### Requirement: A recorded set of requests with expected outcomes exists

The system SHALL include a stored set of representative requests, each with the products and totals it should produce, covering the behaviours the assignment requires.

#### Scenario: Set meets the required size
- **WHEN** the recorded set is inspected
- **THEN** it contains at least ten requests, each with expected products and an expected total

#### Scenario: Set covers the difficult behaviours
- **WHEN** the recorded set is inspected
- **THEN** it includes cases for budget-dependent quantity, sale precedence, unavailable items, no-match, clarification, small-order delivery and tax, multi-item orders, synonym and notation handling, and the filter semantics for inapplicable attributes

### Requirement: Each case records expected against actual

Running the set SHALL produce, per case, what was expected and what actually occurred, so that agreement and disagreement are both visible.

#### Scenario: Results show both sides
- **WHEN** the set is run
- **THEN** each case reports its expected products and total alongside the actual products and total

#### Scenario: Totals are compared exactly
- **WHEN** a total is compared
- **THEN** the comparison is exact to the smallest currency subdivision, not approximate

### Requirement: Cases are scored on separate axes

Each case SHALL be assessed separately for whether the right products were found, whether the stated justifications were accurate, whether the figures were correct, and whether the reply was usable.

#### Scenario: Axes are reported independently
- **WHEN** results are reported
- **THEN** product selection, justification accuracy, price accuracy, and reply quality are reported separately, so a correct price cannot mask wrong products

### Requirement: Failing cases are retained and reported

Cases that fail SHALL remain in the recorded results, with an explanation, and SHALL NOT be removed or excluded to improve the summary.

#### Scenario: Failures remain visible
- **WHEN** a case fails
- **THEN** it remains in the results with its expected and actual values and a note on the cause

#### Scenario: Cases that cannot run are recorded as such
- **WHEN** a case depends on data absent from the current catalog
- **THEN** it is recorded as not applicable, with the reason, rather than being silently omitted or counted as a pass

#### Scenario: Applicability is stated per catalog, not permanently
- **WHEN** a case cannot run against one catalog
- **THEN** the reason names the catalog it cannot run against, so that the case is understood to be blocked by absent data rather than known to be broken

#### Scenario: A case becomes runnable when its data exists
- **WHEN** the set is run against a catalog that contains the data a previously inapplicable case requires
- **THEN** that case runs and is scored on its merits, and is no longer reported as not applicable

#### Scenario: Running against a second catalog does not disturb the recorded run
- **WHEN** the set is run against a catalog other than the committed one
- **THEN** the results identify which catalog they were produced against, so the two runs are not conflated

### Requirement: The recorded set runs without manual intervention

Running the set SHALL be a single operation that produces the results, so that it can be re-run after any change.

#### Scenario: One command produces results
- **WHEN** the evaluation is run
- **THEN** it executes every case and produces the results without manual steps

#### Scenario: Evaluation does not require the language model
- **WHEN** the evaluation runs and the language model is unavailable
- **THEN** the cases that depend only on structured quoting still run and report, and the remainder are reported as not run

### Requirement: Interpretation strategies are comparable

Where more than one interpretation strategy is available, the system SHALL allow their results on the same requests to be compared.

#### Scenario: Strategies compared on identical input
- **WHEN** the comparison is run
- **THEN** each strategy is applied to the same requests and their interpretations and outcomes are reported side by side
