# Spec Delta

## MODIFIED Requirements

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
