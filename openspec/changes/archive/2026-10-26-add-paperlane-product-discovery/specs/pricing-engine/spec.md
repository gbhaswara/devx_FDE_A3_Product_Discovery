# Spec Delta

## Purpose

Decides every monetary figure in the system from catalog data alone, so that prices are reproducible, auditable, and never produced or restated by a language model.

## ADDED Requirements

### Requirement: Money is exact and never floating point

All monetary amounts SHALL be represented as whole units of the smallest currency subdivision, and all rounding SHALL be explicit half-up. No monetary value SHALL be derived through binary floating-point arithmetic.

#### Scenario: Half-up rounding is applied explicitly
- **WHEN** an amount requires rounding to the smallest subdivision
- **THEN** the result is rounded half-up, so an exact half always rounds away from zero

#### Scenario: Accumulated totals are exact
- **WHEN** a total is computed from several line amounts
- **THEN** the result equals the exact arithmetic sum with no representation drift

### Requirement: Unit price is selected at the requested quantity

Volume pricing applies per item, and a price tier applies only when the requested quantity reaches that tier's minimum. The unit price SHALL be evaluated at the quantity actually requested, not at a list price and not at a default quantity.

#### Scenario: A met tier overrides the list price
- **WHEN** the requested quantity is at or above a tier's minimum
- **THEN** that tier's unit price is used, and the highest qualifying tier wins

#### Scenario: A list price applies when no tier is met
- **WHEN** the requested quantity is below the lowest tier's minimum
- **THEN** the list price is used, and no error is raised

#### Scenario: Quantity changes the budget outcome for one product
- **WHEN** the same product and budget are evaluated at a low quantity and at a higher quantity
- **THEN** the budget verdict may differ between the two, and the verdict always reflects the quantity supplied

### Requirement: Sale price takes precedence over all volume pricing

An item on sale is sold at its sale price. The sale price SHALL override both the list price and every volume tier, and the two SHALL NOT be combined.

#### Scenario: Sale item ignores volume tiers
- **WHEN** a quantity that would qualify for a volume tier is requested for an item on sale
- **THEN** the sale price is charged for every unit, regardless of quantity

#### Scenario: Sale item with no volume pricing is not an error
- **WHEN** an item on sale is quoted at a quantity that would normally attract a discount
- **THEN** the quote succeeds at the sale price and states that no volume pricing applies

### Requirement: Volume tiers are evaluated per item, not per product family

Tiers are defined per purchasable item. Quantities of related but distinct items SHALL NOT be combined to reach a tier.

#### Scenario: Similar items do not pool their quantities
- **WHEN** the same quantity of two different items from one product page is requested
- **THEN** each item's unit price is determined from its own tiers alone

### Requirement: Delivery is charged once per order

Delivery SHALL be evaluated against the order subtotal before tax, and charged once for the whole order rather than per line.

#### Scenario: Free delivery above the threshold
- **WHEN** the order subtotal before tax is at or above the free-delivery threshold
- **THEN** delivery is charged at zero

#### Scenario: Flat fee below the threshold
- **WHEN** the order subtotal before tax is below the free-delivery threshold
- **THEN** a single flat delivery fee is added to the order

#### Scenario: Mixed order crossing the threshold only in aggregate
- **WHEN** an order contains several lines, none of which reaches the threshold on its own, but whose combined subtotal does
- **THEN** delivery is charged at zero, and no per-line delivery is added

### Requirement: Tax is charged on subtotal plus delivery

Tax SHALL be computed on the sum of the order subtotal and the delivery charge, at the published rate, and added to produce the total.

#### Scenario: Delivery is included in the taxable amount
- **WHEN** delivery is charged on a small order
- **THEN** the tax is computed on the subtotal plus delivery, and the total reflects that

#### Scenario: Total is the sum of its stated parts
- **WHEN** a quote is presented
- **THEN** subtotal, delivery, tax and total are each stated, and the total equals their sum

### Requirement: Budget comparison uses the unit price at the requested quantity, before tax

A budget stated per unit SHALL be compared against the unit price at the requested quantity, before tax, using an inclusive upper bound. Where the basis is not stated by the customer, the system SHALL state the assumption it applied.

#### Scenario: Inclusive boundary
- **WHEN** a unit price exactly equals the stated budget
- **THEN** the item is treated as within budget

#### Scenario: Assumption is stated when the basis is unstated
- **WHEN** a customer gives a budget without saying whether it includes tax
- **THEN** the reply states which basis was used, so the customer can correct it

### Requirement: Only catalog values may enter a quote

Every figure in a quote SHALL be traceable to a stored catalog price or a value computed from one by these rules. A figure SHALL NOT be introduced, adjusted, or restated by a language model.

#### Scenario: Quote figures trace to catalog data
- **WHEN** a quote is produced
- **THEN** each unit price used corresponds to a stored list, sale, or tier price for that item, and each derived figure is reproducible from those inputs

#### Scenario: Model-supplied figure cannot reach a quote
- **WHEN** a language model returns a price alongside its parsed criteria
- **THEN** that price is discarded, and only the deterministic computation determines the quoted amounts

### Requirement: Pricing is a pure function of catalog data

Given the same catalog snapshot and the same request, pricing SHALL produce identical results, and it SHALL NOT depend on the language model, the network, the current time, or iteration order.

#### Scenario: Repeated evaluation is identical
- **WHEN** the same request is priced twice against the same snapshot
- **THEN** both results are identical in every figure

#### Scenario: Pricing succeeds without any model
- **WHEN** structured criteria are supplied directly and no language model is reachable
- **THEN** a complete, correct quote is still produced
