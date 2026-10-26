# conversation-memory Specification

## Purpose
Lets a customer refine a request instead of restating it, by remembering the
criteria from earlier turns in the same conversation — while guaranteeing that a
new subject starts fresh, that a correction corrects, that what was remembered
is visible in the reply, and that a request naming no conversation is handled
exactly as it is today.

## Requirements

### Requirement: A turn is merged onto a conversation only when it refines it

A request that names a conversation SHALL be merged onto that conversation's
remembered criteria when the turn is a refinement, and SHALL start a fresh
request when the turn states a new product kind, size, or category.

#### Scenario: A refinement continues the conversation
- **WHEN** the conversation's criteria name A4 copy paper at 20 reams, and the next turn is "make it 50"
- **THEN** the merged criteria name A4 copy paper at 50 reams, and the reply quotes that

#### Scenario: A new subject starts fresh
- **WHEN** the conversation's criteria name flyers, and the next turn is "A4 copy paper"
- **THEN** the request is searched as A4 copy paper, and no flyer constraint is applied

#### Scenario: A stated size starts fresh
- **WHEN** the conversation's criteria name A4 copy paper, and the next turn is "A5 instead"
- **THEN** the request is not merged onto the A4 criteria

#### Scenario: A stated weight is a correction, not a new subject
- **WHEN** the conversation's criteria name A4 copy paper at 80 gsm, and the next turn is "make it 100 gsm"
- **THEN** the merged criteria name A4 copy paper at 100 gsm, and the size is retained

#### Scenario: A turn that understood nothing starts fresh
- **WHEN** the next turn states no requirement at all
- **THEN** the earlier requirements are not silently re-applied

#### Scenario: A budget-only turn continues
- **WHEN** the conversation's criteria name a product at 20 reams, and the next turn is "and under 130 a pack"
- **THEN** the product and quantity are carried and the budget is applied

#### Scenario: A bare number in a refinement is the quantity
- **WHEN** the conversation's criteria name a product at 20 reams, and the next turn is "make it 50"
- **THEN** the merged criteria name 50, and the quantity is not reported as remembered

#### Scenario: A budget number is not read as a quantity
- **WHEN** a refinement states a budget and no unit-bearing quantity
- **THEN** the earlier quantity is retained, and the budget figure is not adopted as the quantity

#### Scenario: Nothing to continue is not a continuation
- **WHEN** a request names a conversation that has no remembered criteria
- **THEN** the turn is treated as a fresh request

### Requirement: An explicit field in the current turn always wins

When merging, each field SHALL take the current turn's value when that turn
states it, and the earlier value only when it does not.

#### Scenario: A correction corrects
- **WHEN** the conversation's criteria name 80 gsm and the next turn states 100 gsm
- **THEN** the merged criteria name 100 gsm

#### Scenario: An unstated field is carried
- **WHEN** the conversation's criteria name A4 and the next turn states only a quantity
- **THEN** the merged criteria still name A4

#### Scenario: A carried quantity is not silently applied
- **WHEN** a quantity is carried from an earlier turn
- **THEN** the reply states that quantity explicitly rather than folding it into the match reasons

### Requirement: The reply discloses which requirements came from earlier turns

A reply produced from merged criteria SHALL name the requirements carried from
earlier turns, so a customer can tell a remembered constraint from a fresh one.

#### Scenario: Carried requirements are named
- **WHEN** a reply is produced from criteria merged with an earlier turn
- **THEN** the reply states which requirements came from earlier turns

#### Scenario: A fresh request discloses nothing carried
- **WHEN** a reply is produced from a request that carried nothing forward
- **THEN** the reply says nothing about earlier turns

#### Scenario: Disclosure is in words, not only in structure
- **WHEN** a reply discloses carried requirements
- **THEN** the disclosure appears in the reply text a salesperson reads, not only in a machine-readable field

### Requirement: A merged request is re-validated in full

Merged criteria SHALL be validated against the catalog's vocabulary before
anything is priced, and an invalid merge SHALL ask rather than quote.

#### Scenario: An invalid merged value does not reach pricing
- **WHEN** merged criteria contain a value the catalog does not stock
- **THEN** the system does not price, and asks instead

#### Scenario: Merging never introduces a product that is not in the catalog
- **WHEN** a reply is produced from merged criteria
- **THEN** every product it presents exists in the catalog

### Requirement: A conversation is bounded in both count and length

The conversation store SHALL hold a bounded number of conversations, each with a
bounded number of turns, and SHALL evict the least recently used when either
bound is reached.

#### Scenario: The conversation count is bounded
- **WHEN** more distinct conversations than the configured maximum are opened
- **THEN** the store holds no more than the maximum, and the least recently used is gone

#### Scenario: The turn count is bounded
- **WHEN** a conversation exceeds the configured maximum turns
- **THEN** the store retains no more than the maximum turns

#### Scenario: The bounds are enforced by tests
- **WHEN** the bounds are inspected
- **THEN** each is asserted by a test rather than left to a comment

### Requirement: A request naming no conversation is unaffected

A request that names no conversation SHALL NOT read or write the conversation
store, and SHALL behave exactly as a request did before conversation memory
existed.

#### Scenario: No conversation means no store access
- **WHEN** a request names no conversation
- **THEN** the store is neither read nor written

#### Scenario: No conversation means no turn index
- **WHEN** a request names no conversation
- **THEN** its record carries no turn index, so single-turn traffic stays distinguishable

#### Scenario: Existing single-turn results are unchanged
- **WHEN** the recorded evaluation cases are run with no conversation
- **THEN** every result is what it was before conversation memory existed

### Requirement: A conversation can be forgotten

The system SHALL provide a way to discard a conversation, after which its
criteria are no longer remembered.

#### Scenario: Forgetting discards the remembered criteria
- **WHEN** a conversation is forgotten and a later turn names it
- **THEN** that turn is treated as a fresh request

#### Scenario: Forgetting an unknown conversation is not an error
- **WHEN** a request forgets a conversation that does not exist
- **THEN** the request succeeds and reports that nothing was forgotten

### Requirement: The conversation store holds criteria, never conversation text

The store SHALL hold only structured criteria and their provenance, and SHALL
NOT hold the customer's request text.

#### Scenario: No request text is stored
- **WHEN** a conversation is inspected
- **THEN** it contains no request text, only structured criteria

#### Scenario: A credential in a turn does not reach the store
- **WHEN** a turn contains a credential
- **THEN** the store does not contain it
