# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
