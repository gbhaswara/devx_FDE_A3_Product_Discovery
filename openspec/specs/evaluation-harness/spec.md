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

Each case SHALL be assessed separately for whether the request was understood as
intended, whether the right products were found, whether the stated justifications
were accurate, whether the figures were correct, and whether the reply was usable.

#### Scenario: Axes are reported independently
- **WHEN** results are reported
- **THEN** interpretation, product selection, justification accuracy, price accuracy, and reply quality are reported separately, so a correct price cannot mask wrong products, and neither can a correct product set mask a misread request

#### Scenario: A wrong reading is scored as a wrong reading
- **WHEN** a case's request implies a requirement that the interpretation does not derive, or derives a requirement the request does not state
- **THEN** the interpretation axis fails for that case, and the remaining axes are scored on what the engine actually did with the criteria it derived

#### Scenario: An axis that cannot be assessed is reported as such
- **WHEN** a case records no expected interpretation
- **THEN** the interpretation axis is reported as not applicable for that case, and is counted as not applicable rather than as a pass

#### Scenario: The axes do not move together
- **WHEN** a single defect is introduced into one part of a case's answer
- **THEN** the axis responsible for that part fails and the others do not, so a failure identifies which part broke

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

### Requirement: A held-out set of requests exists, separate from the recorded set

The system SHALL include a set of requests that was not used to develop the
interpretation rules, scored by the same harness, and kept separate from the
recorded regression set.

#### Scenario: The held-out set is scored by the same harness
- **WHEN** the held-out set is run
- **THEN** it produces the same per-axis results and summary as the recorded set, with no separate reporting path

#### Scenario: The held-out set is not merged into the regression set
- **WHEN** the two sets are inspected
- **THEN** they are separate files, so that tuning against the regression set does not silently consume the held-out one

#### Scenario: A held-out failure is reported, not suppressed
- **WHEN** a held-out case fails because the system misread an unseen request
- **THEN** the failure remains in the results with its expected and actual interpretation, and is counted in the held-out summary
