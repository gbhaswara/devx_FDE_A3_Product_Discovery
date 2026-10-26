"""Search: hard-constraint filtering, deterministic ranking, justification.

The order of operations is the whole design:

1. **Filter.** Every stated requirement is a hard constraint. An item that
   contradicts one is gone. No scoring, no "close enough".
2. **Rank.** Survivors are ordered by a total order with a stable final
   tiebreak, so the same request against the same snapshot always produces the
   same list.
3. **Justify.** Each survivor carries one record per satisfied requirement,
   derived from the filter evaluation that already happened — not composed
   afterwards and never by a model.

The two semantics that are easy to get wrong, and are tested explicitly:

**Not-applicable is not a mismatch.** A plain-paper product has no ``sides``.
A request for double-sided printing must not exclude it, because the attribute
does not apply. But it must also not be *claimed* as matching double-sided. So
the filter passes the item and the justification simply omits that requirement.

**The budget is compared at the requested quantity.** The unit price is chosen
by the pricing engine at the quantity asked for, so an item that fails at qty 1
can pass at qty 20. Filtering on the list price gets the brief's own example
wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from .criteria import Criteria
from .money import Money
from .pricing import PriceFacts, applied_tier, unit_price

#: Ranking criteria, in priority order. The tuple is the sort key, so its order
#: *is* the ranking rule and a test asserts the documented chain matches it.
#: Lower sorts first.
RANKING_ORDER = (
    "availability_penalty",   # available before unavailable
    "budget_margin",          # cheapest first, when no preference distinguishes
    "sku",                    # stable, total, and independent of iteration order
)


@dataclass(frozen=True)
class MatchReason:
    """One satisfied requirement, with the requested and actual values.

    Produced during filtering. The reply never invents a reason; it renders
    these.
    """

    attribute: str
    requested: str
    actual: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        payload = {
            "attribute": self.attribute,
            "requested": self.requested,
            "actual": self.actual,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class Candidate:
    """A catalog item that survived filtering, with its justification."""

    sku: str
    name: str
    product: dict[str, Any]
    facts: PriceFacts
    match_reasons: tuple[MatchReason, ...]
    unit_price: Money
    line_total: Money
    quantity: int
    tier_applied: int | None
    available: bool
    stock_status: str
    back_in_stock_date: str | None

    @property
    def discount_note(self) -> str:
        """Where the price came from, for the reply."""
        if self.facts.on_sale:
            return "sale price (no volume discount on sale items)"
        if self.tier_applied is not None:
            return f"{self.tier_applied}+ tier (list {self.facts.list_price.format()})"
        return "list price"

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "name": self.name,
            "size": self.product.get("size_code"),
            "weight_gsm": self.product.get("weight_gsm"),
            "pack_sheets": self.product.get("pack_sheets"),
            "unit_price": self.unit_price.format(),
            "quantity": self.quantity,
            "line_total": self.line_total.format(),
            "discount": self.discount_note,
            "available": self.available,
            "stock_status": self.stock_status,
            "back_in_stock_date": self.back_in_stock_date,
            "match_reasons": [r.as_dict() for r in self.match_reasons],
        }


@dataclass(frozen=True)
class SearchResult:
    """The outcome of a search: matches, alternatives, or nothing."""

    criteria: Criteria
    matches: tuple[Candidate, ...] = ()
    alternatives: tuple[Candidate, ...] = ()
    relaxed: str | None = None
    unavailable: tuple[Candidate, ...] = ()
    considered: int = 0

    @property
    def is_match(self) -> bool:
        return bool(self.matches)

    @property
    def is_empty(self) -> bool:
        return not self.matches and not self.alternatives

    @property
    def best(self) -> Candidate | None:
        return self.matches[0] if self.matches else None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _normalise(value: str | None) -> str:
    return (value or "").strip().lower()


def _word_set(value: str) -> set[str]:
    """Split a catalog or requested value into comparable whole words."""
    cleaned = re.sub(r"[(),/]", " ", _normalise(value))
    return {word for word in cleaned.split() if word}


def _colour_matches(actual: str | None, requested: str | None) -> bool:
    """Compare shades or print modes, on whole words.

    ``PL-CL-A4-80-BRT`` is "Assorted brights (red, orange, yellow, green,
    blue)"; a request for "red" should not match it by substring accident, but a
    request for "brights" should. So the match is on whole words, and both sides
    are normalised the same way — otherwise ``Full colour (CMYK)`` never equals
    itself because of the parentheses.
    """
    if requested is None:
        return True
    if actual is None:
        return False
    actual_words = _word_set(actual)
    requested_words = _word_set(requested)
    return requested_words <= actual_words


def _finish_matches(actual: str | None, requested: str | None) -> bool:
    if requested is None:
        return True
    if actual is None:
        return False
    return _normalise(requested) in _normalise(actual)


def _weight_matches(product: dict[str, Any], criteria: Criteria) -> bool:
    gsm = product.get("weight_gsm")
    if criteria.weight_gsm is not None:
        return gsm == criteria.weight_gsm
    if criteria.weight_gsm_min is not None and (gsm is None or gsm < criteria.weight_gsm_min):
        return False
    if criteria.weight_gsm_max is not None and (gsm is None or gsm > criteria.weight_gsm_max):
        return False
    return True


def _printing_applies(product: dict[str, Any]) -> bool:
    """Do printing attributes mean anything for this product?

    A plain-paper item has no ``sides`` and no ``colour_mode``. A constraint on
    either must pass it through rather than excluding it for lacking the
    attribute — but it must not be recorded as satisfying the constraint.
    """
    return product.get("sides") is not None or product.get("colour_mode") is not None


def _evaluate(
    product: dict[str, Any],
    facts: PriceFacts,
    criteria: Criteria,
    quantity: int,
) -> tuple[bool, tuple[MatchReason, ...]]:
    """Filter one product. Returns ``(passes, reasons)``.

    ``reasons`` lists only requirements this product genuinely satisfies, so a
    plain-paper item never claims to satisfy a printing constraint.
    """
    reasons: list[MatchReason] = []

    if criteria.category is not None:
        if _normalise(product.get("category")) != _normalise(criteria.category):
            return False, ()
        reasons.append(MatchReason(
            "category", criteria.category, product.get("category") or "",
        ))

    if criteria.size_code is not None:
        if product.get("size_code") != criteria.size_code:
            return False, ()
        reasons.append(MatchReason(
            "size", criteria.size_code, product.get("size_code") or "",
        ))

    if not _weight_matches(product, criteria):
        return False, ()
    if criteria.weight_gsm is not None:
        reasons.append(MatchReason(
            "weight", f"{criteria.weight_gsm} gsm",
            f"{product.get('weight_gsm')} gsm",
        ))
    elif criteria.weight_gsm_min is not None or criteria.weight_gsm_max is not None:
        bound = []
        if criteria.weight_gsm_min is not None:
            bound.append(f">= {criteria.weight_gsm_min}")
        if criteria.weight_gsm_max is not None:
            bound.append(f"<= {criteria.weight_gsm_max}")
        reasons.append(MatchReason(
            "weight", " ".join(bound), f"{product.get('weight_gsm')} gsm",
        ))

    if criteria.colour_name is not None:
        # Paper shade: applies to every product, so a mismatch excludes.
        if not _colour_matches(product.get("colour_name"), criteria.colour_name):
            return False, ()
        reasons.append(MatchReason(
            "colour (paper shade)", criteria.colour_name,
            product.get("colour_name") or "",
        ))

    if criteria.finish is not None:
        if not _finish_matches(product.get("finish"), criteria.finish):
            return False, ()
        reasons.append(MatchReason(
            "finish", criteria.finish, product.get("finish") or "",
        ))

    # --- printing attributes: pass through when not applicable ----------
    if criteria.sides is not None and _printing_applies(product):
        if _normalise(product.get("sides")) != _normalise(criteria.sides):
            return False, ()
        reasons.append(MatchReason(
            "sides", criteria.sides, product.get("sides") or "",
        ))

    if criteria.colour_mode is not None and _printing_applies(product):
        if not _colour_matches(product.get("colour_mode"), criteria.colour_mode):
            return False, ()
        reasons.append(MatchReason(
            "colour (print mode)", criteria.colour_mode,
            product.get("colour_mode") or "",
        ))

    # --- budget at the requested quantity (PR6) ------------------------
    if criteria.budget_per_unit is not None:
        unit = unit_price(facts, quantity)
        if unit > criteria.budget_per_unit:
            return False, ()
        tier = applied_tier(facts, quantity)
        reasons.append(MatchReason(
            "budget per unit",
            criteria.budget_per_unit.format(),
            unit.format(),
            detail=(
                f"at quantity {quantity}"
                + (f", {tier.min_qty}+ tier applied" if tier else ", list price")
                + f", {criteria.budget_basis}"
            ),
        ))

    return True, tuple(reasons)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _availability_penalty(candidate: Candidate) -> int:
    """Available first. Unavailable items are ranked last, never dropped."""
    if candidate.stock_status == "in_stock":
        return 0
    if candidate.stock_status == "out_of_stock":
        return 1
    return 2  # discontinued


def _rank_key(candidate: Candidate) -> tuple:
    """The total order. Mirrors ``RANKING_ORDER`` exactly.

    ``sku`` is the final element, which makes the order total: two items can
    never tie, so the sort is stable regardless of input order or dictionary
    iteration.
    """
    return (
        _availability_penalty(candidate),
        candidate.unit_price.satang,
        candidate.sku,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _make_candidate(
    product: dict[str, Any],
    facts: PriceFacts,
    reasons: Sequence[MatchReason],
    quantity: int,
) -> Candidate:
    unit = unit_price(facts, quantity)
    tier = applied_tier(facts, quantity)
    return Candidate(
        sku=product["sku"],
        name=product["name"],
        product=product,
        facts=facts,
        match_reasons=tuple(reasons),
        unit_price=unit,
        line_total=unit * quantity,
        quantity=quantity,
        tier_applied=tier.min_qty if tier else None,
        available=product.get("stock_status") == "in_stock",
        stock_status=product.get("stock_status", "in_stock"),
        back_in_stock_date=product.get("back_in_stock_date"),
    )


def search(
    criteria: Criteria,
    products: Sequence[dict[str, Any]],
    facts: dict[str, PriceFacts],
    *,
    quantity: int | None = None,
) -> SearchResult:
    """Filter, rank, and justify.

    Returns matches in ranked order. When nothing satisfies every requirement,
    ``matches`` is empty and ``alternatives`` holds the closest items with the
    relaxed requirement named — the two are never mixed.
    """
    qty = quantity or criteria.quantity or 1
    considered = 0
    matched: list[Candidate] = []

    for product in products:
        sku = product["sku"]
        if sku not in facts:
            continue
        considered += 1
        passed, reasons = _evaluate(product, facts[sku], criteria, qty)
        if passed:
            matched.append(_make_candidate(product, facts[sku], reasons, qty))

    matched.sort(key=_rank_key)
    matches = tuple(matched)

    # Unavailable items that otherwise match are reported separately so the
    # assistant can refuse them rather than offering them.
    available = tuple(c for c in matches if c.available)
    unavailable = tuple(c for c in matches if not c.available)

    if available:
        return SearchResult(
            criteria=criteria,
            matches=available,
            unavailable=unavailable,
            considered=considered,
        )

    # Nothing available satisfied everything. If unavailable items matched,
    # say so distinctly rather than offering alternatives.
    if unavailable:
        return SearchResult(
            criteria=criteria,
            unavailable=unavailable,
            considered=considered,
        )

    alternatives, relaxed = _relax(criteria, products, facts, qty)
    return SearchResult(
        criteria=criteria,
        alternatives=alternatives,
        relaxed=relaxed,
        considered=considered,
    )


#: Requirements in the order they are relaxed. Cheapest-to-lose first: a budget
#: is the thing a customer most often has room on, a size almost never.
RELAXATION_ORDER = ("budget", "finish", "weight", "sides", "colour", "size")


def _relax(
    criteria: Criteria,
    products: Sequence[dict[str, Any]],
    facts: dict[str, PriceFacts],
    quantity: int,
) -> tuple[tuple[Candidate, ...], str | None]:
    """Find the closest items by dropping one requirement at a time.

    Each alternative is labelled with the requirement that was relaxed, so it is
    never presented as though it satisfied the original request.
    """
    for attribute in RELAXATION_ORDER:
        relaxed = _drop(criteria, attribute)
        if relaxed is None:
            continue

        found: list[Candidate] = []
        for product in products:
            sku = product["sku"]
            if sku not in facts:
                continue
            passed, reasons = _evaluate(product, facts[sku], relaxed, quantity)
            if passed:
                found.append(_make_candidate(product, facts[sku], reasons, quantity))

        found.sort(key=_rank_key)
        available = [c for c in found if c.available]
        if available:
            return tuple(available[:5]), attribute

    return (), None


def _drop(criteria: Criteria, attribute: str) -> Criteria | None:
    """Return a copy of the criteria with one requirement removed."""
    from dataclasses import replace

    if attribute == "budget" and criteria.budget_per_unit is not None:
        return replace(criteria, budget_per_unit=None)
    if attribute == "finish" and criteria.finish is not None:
        return replace(criteria, finish=None)
    if attribute == "weight" and (
        criteria.weight_gsm is not None
        or criteria.weight_gsm_min is not None
        or criteria.weight_gsm_max is not None
    ):
        return replace(
            criteria, weight_gsm=None, weight_gsm_min=None, weight_gsm_max=None
        )
    if attribute == "sides" and criteria.sides is not None:
        return replace(criteria, sides=None)
    if attribute == "colour" and (
        criteria.colour_name is not None or criteria.colour_mode is not None
    ):
        return replace(criteria, colour_name=None, colour_mode=None)
    if attribute == "size" and criteria.size_code is not None:
        return replace(criteria, size_code=None)
    return None
