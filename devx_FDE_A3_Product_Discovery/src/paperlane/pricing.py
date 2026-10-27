"""The pricing engine: pure functions implementing PR1-PR8.

This module is the highest-value code in the project. The brief scores "right
products and totals to the satang", and every monetary figure the system ever
shows comes from here.

Design constraints, each enforced structurally:

* **Pure.** No I/O, no network, no clock, no model, no global state. Everything
  it needs arrives as arguments, so a quote can be reproduced exactly.
* **Integer satang.** Arithmetic is on ``Money``, which holds an int. There is
  no float anywhere in this file.
* **One path.** ``/quote``, ``/chat`` and the evaluation harness all call
  ``quote()``. A pricing bug cannot appear in one entry point and not another.

The three lines that actually go wrong, each with a named test:

1. ``best = list_price`` — if the best price starts as ``None``, items whose
   lowest tier is 5+ or 10+ crash or return nothing at qty 1-4. This was a real
   defect found during analysis (BUG.md A8).
2. delivery evaluated on the **summed** subtotal, not per line.
3. VAT on **subtotal + delivery**, not subtotal alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence

from .money import Money, percent_of

# ---------------------------------------------------------------------------
# Published rules (from delivery.html and the brief's PR1-PR8)
# ---------------------------------------------------------------------------

#: PR4: delivery is free at or above this subtotal, otherwise a flat fee.
FREE_DELIVERY_THRESHOLD = Money.from_baht("3000.00")
FLAT_DELIVERY_FEE = Money.from_baht("150.00")

#: PR5: VAT rate on (subtotal + delivery).
VAT_RATE = Decimal("7")


# ---------------------------------------------------------------------------
# Catalog price facts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceTier:
    """One volume-pricing row for a leaf SKU.

    Tiers are keyed by SKU, never by product page: two variants on one page
    (``-40`` single-sided and ``-44`` double-sided) have separate tiers, so 10
    of each does not reach a 20+ tier (PR2, "per item").
    """

    min_qty: int
    unit_price: Money


@dataclass(frozen=True)
class PriceFacts:
    """Everything the engine needs to price one leaf SKU.

    ``sale_price`` is optional. When present it replaces *both* the list price
    and every tier (PR3), and the two cannot be combined.
    """

    sku: str
    list_price: Money
    tiers: tuple[PriceTier, ...] = ()
    sale_price: Money | None = None

    @property
    def on_sale(self) -> bool:
        return self.sale_price is not None


# ---------------------------------------------------------------------------
# Unit price selection
# ---------------------------------------------------------------------------


def unit_price(facts: PriceFacts, quantity: int) -> Money:
    """Return the unit price for ``quantity`` units of one SKU.

    Order of precedence, exactly as the rules state:

    1. **Sale** (PR3) — replaces list and all tiers. A sale item never gets a
       volume discount; the two cannot be combined.
    2. **Highest met tier** (PR2) — the tier with the largest ``min_qty`` that
       is ``<= quantity``.
    3. **List price** — the fallback when no tier is met.

    Step 3 is the one that goes wrong. ``best`` is initialised to the list
    price, never to ``None``, because most SKUs' lowest tier is 5+ or 10+, so
    at quantity 1 no tier matches at all.
    """
    if quantity < 1:
        raise ValueError(f"quantity must be >= 1, got {quantity}")

    if facts.sale_price is not None:
        return facts.sale_price

    best = facts.list_price          # <- must be the list price, not None
    best_min = -1
    for tier in facts.tiers:
        if quantity >= tier.min_qty and tier.min_qty > best_min:
            best = tier.unit_price
            best_min = tier.min_qty
    return best


def applied_tier(facts: PriceFacts, quantity: int) -> PriceTier | None:
    """Return the tier that applied, or ``None`` when the list price was used.

    Used to state provenance in the reply ("20+ tier; list 265.00"), which is
    what makes a quote forwardable rather than suspicious.
    """
    if facts.on_sale:
        return None
    applicable = [t for t in facts.tiers if quantity >= t.min_qty]
    if not applicable:
        return None
    return max(applicable, key=lambda t: t.min_qty)


# ---------------------------------------------------------------------------
# Line and order assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineRequest:
    """One requested line: a SKU and how many units."""

    sku: str
    quantity: int
    facts: PriceFacts

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError(
                f"quantity for {self.sku} must be >= 1, got {self.quantity}"
            )


@dataclass(frozen=True)
class LineQuote:
    """A priced line, with the provenance needed to justify it."""

    sku: str
    quantity: int
    unit_price: Money
    line_total: Money
    list_price: Money
    tier_applied: PriceTier | None
    on_sale: bool

    @property
    def discount_source(self) -> str:
        """Human-readable provenance for the discount applied, if any."""
        if self.on_sale:
            return "sale price (no volume discount on sale items)"
        if self.tier_applied is not None:
            return f"{self.tier_applied.min_qty}+ tier (list {self.list_price.format()})"
        return "list price"


@dataclass(frozen=True)
class OrderQuote:
    """A complete priced order.

    Every component is stated separately so the total can be checked by the
    customer, which is what makes the quote trustworthy.
    """

    lines: tuple[LineQuote, ...]
    subtotal: Money
    delivery: Money
    vat: Money
    total: Money
    free_delivery_threshold: Money = FREE_DELIVERY_THRESHOLD
    vat_rate: Decimal = VAT_RATE

    @property
    def delivery_waived(self) -> bool:
        return self.delivery.satang == 0 and self.subtotal >= FREE_DELIVERY_THRESHOLD


def price_line(request: LineRequest, tier_quantity: int | None = None) -> LineQuote:
    """Price a single line.

    ``tier_quantity`` is the quantity the **tier** is selected from, which is
    the order's total for that SKU rather than this line's own quantity. The
    tier is a property of the item, so a caller that splits one SKU across two
    lines must not thereby lose the tier the order as a whole earns (BUG.md
    A26). The line still reports its own quantity and is still priced at
    ``unit × quantity``; only the tier lookup is shared.
    """
    quantity_for_tier = request.quantity if tier_quantity is None else tier_quantity
    unit = unit_price(request.facts, quantity_for_tier)
    return LineQuote(
        sku=request.sku,
        quantity=request.quantity,
        unit_price=unit,
        line_total=unit * request.quantity,
        list_price=request.facts.list_price,
        tier_applied=applied_tier(request.facts, quantity_for_tier),
        on_sale=request.facts.on_sale,
    )


def quote(requests: Sequence[LineRequest]) -> OrderQuote:
    """Price a whole order.

    Delivery is evaluated **once**, against the summed pre-tax subtotal. That
    is PR4's "per order": an order whose lines individually sit below the
    threshold but whose combined subtotal clears it pays no delivery. Charging
    per line is invisible on every single-item test and only surfaces on a
    mixed basket.

    The same rule applies to a SKU's volume tier: the quantity per SKU is
    summed **before** the tier is chosen, so one SKU split across two lines is
    priced as the total the customer is buying, not per line. One output line
    per requested line is preserved — the caller's line structure is theirs.
    """
    if not requests:
        raise ValueError("cannot quote an empty order")

    ordered_per_sku: dict[str, int] = {}
    for request in requests:
        ordered_per_sku[request.sku] = (
            ordered_per_sku.get(request.sku, 0) + request.quantity
        )

    lines = tuple(
        price_line(r, ordered_per_sku[r.sku]) for r in requests
    )
    subtotal = Money.zero()
    for line in lines:
        subtotal = subtotal + line.line_total

    delivery = (
        Money.zero() if subtotal >= FREE_DELIVERY_THRESHOLD else FLAT_DELIVERY_FEE
    )

    # VAT is charged on subtotal + delivery (PR5), rounded half-up once.
    vat = percent_of(subtotal + delivery, VAT_RATE)
    total = subtotal + delivery + vat

    return OrderQuote(
        lines=lines,
        subtotal=subtotal,
        delivery=delivery,
        vat=vat,
        total=total,
    )


# ---------------------------------------------------------------------------
# Budget comparison (PR6, PR7)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetCheck:
    """The outcome of comparing a per-unit budget with a unit price.

    The basis is carried explicitly because PR7 requires the reply to state
    which assumption was applied when the customer did not say.
    """

    budget: Money
    unit_price: Money
    quantity: int
    within_budget: bool
    basis: str = "per pack, before VAT"

    @property
    def difference(self) -> Money:
        """How far over or under budget, in satang. Negative means under."""
        return self.unit_price - self.budget

    def describe(self) -> str:
        if self.within_budget:
            return (
                f"{self.unit_price.format()} at {self.quantity} "
                f"(within {self.budget.format()}, {self.basis})"
            )
        return (
            f"{self.unit_price.format()} at {self.quantity} "
            f"({self.difference.format()} over {self.budget.format()}, {self.basis})"
        )


def _basis_includes_vat(basis: str) -> bool:
    """Whether a stated basis compares against the VAT-inclusive price.

    PR6 fixes the comparison at *before VAT*; PR7 lets the customer say
    otherwise, and when they do the comparison must honour it rather than merely
    echo the label back (BUG.md A21).
    """
    lowered = basis.lower()
    return "including vat" in lowered or "inclusive" in lowered


def comparable_unit_price(facts: PriceFacts, quantity: int, basis: str) -> Money:
    """The per-unit price a budget should be compared against, given its basis.

    One function, so the pricing engine, the search filter and the clarification
    rule cannot disagree about what "within budget" means. Returning the gross
    price here is what makes the basis a *rule* rather than a footnote.
    """
    unit = unit_price(facts, quantity)
    if _basis_includes_vat(basis):
        return unit + percent_of(unit, VAT_RATE)
    return unit


def check_budget(
    facts: PriceFacts,
    quantity: int,
    budget: Money,
    *,
    basis: str = "per pack, before VAT",
) -> BudgetCheck:
    """Compare a per-unit budget against the unit price **at the requested quantity**.

    This is the assignment's central trap. The brief's own example puts the
    budget before the quantity — "under 250 a pack, 20 packs" — and for
    PL-PR-LTR-GL-130-40 the verdict flips between quantities:

        qty  1 -> 265.00  FAILS "under 250"
        qty 20 -> 233.20  PASSES

    Comparing against the list price gets the brief's own example wrong. The
    bound is inclusive: PR6 says "maximum price per pack", so a unit price
    exactly equal to the budget is within budget.

    When the customer states an inclusive basis the comparison is against the
    gross price, so ``unit_price`` on the result is the number actually compared
    (233.20 before VAT, 249.52 including it).
    """
    unit = comparable_unit_price(facts, quantity, basis)
    return BudgetCheck(
        budget=budget,
        unit_price=unit,
        quantity=quantity,
        within_budget=unit <= budget,
        basis=basis,
    )
