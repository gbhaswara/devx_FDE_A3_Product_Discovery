"""The assistant: criteria in, a usable reply out.

The reply is **rendered**, not generated. Every product, every figure, and every
justification in it comes from the deterministic layers; the model's only
contribution was the criteria. That is what makes the three guard checks
possible and meaningful:

* ``check_no_invented_products`` — every SKU in the reply must exist in the
  snapshot, so a model cannot smuggle one in.
* ``check_figures_match`` — every amount in the reply text must equal a computed
  amount, so prose cannot drift from arithmetic.
* ``check_no_internal_ids`` — products are described by their catalog name, with
  the SKU available but not used as the description.

Four outcomes, and they are structurally distinct so a caller cannot confuse
them:

    quoted          products matched and priced
    clarified       a needed detail is missing or ambiguous
    no_match        nothing satisfies the request, alternatives offered
    refused         the only suitable item is unavailable
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from .criteria import Criteria
from .money import Money
from .pricing import (
    FLAT_DELIVERY_FEE,
    FREE_DELIVERY_THRESHOLD,
    LineRequest,
    OrderQuote,
    PriceFacts,
    check_budget,
    quote,
)
from .search import Candidate, SearchResult, search

#: The four outcome states.
OUTCOME_QUOTED = "quoted"
OUTCOME_CLARIFIED = "clarified"
OUTCOME_NO_MATCH = "no_match"
OUTCOME_REFUSED = "refused"

#: At most two questions at once — more than that reads as an interrogation.
MAX_QUESTIONS = 2


@dataclass(frozen=True)
class Question:
    """One thing the assistant needs before it can answer."""

    field: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "question": self.text}


@dataclass
class AssistantReply:
    """A complete reply, with the structure the caller and tests inspect."""

    outcome: str
    text: str
    criteria: Criteria
    interpretation: str = "rules"          # "model" | "rules" | "mixed"
    quote: OrderQuote | None = None
    candidates: tuple[Candidate, ...] = ()
    alternatives: tuple[Candidate, ...] = ()
    relaxed: str | None = None
    questions: tuple[Question, ...] = ()
    refused: tuple[Candidate, ...] = ()
    budget_check: Any = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "outcome": self.outcome,
            "reply": self.text,
            "interpretation": self.interpretation,
            "criteria": self.criteria.describe(),
        }
        if self.questions:
            payload["questions"] = [q.as_dict() for q in self.questions]
        if self.candidates:
            payload["candidates"] = [c.as_dict() for c in self.candidates]
        if self.alternatives:
            payload["alternatives"] = [c.as_dict() for c in self.alternatives]
        if self.relaxed:
            payload["relaxed"] = self.relaxed
        if self.refused:
            payload["refused"] = [c.as_dict() for c in self.refused]
        if self.quote is not None:
            payload["breakdown"] = {
                "subtotal": self.quote.subtotal.format(),
                "delivery": self.quote.delivery.format(),
                "vat": self.quote.vat.format(),
                "total": self.quote.total.format(),
                "vat_rate": str(self.quote.vat_rate),
                "lines": [
                    {
                        "sku": line.sku,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price.format(),
                        "line_total": line.line_total.format(),
                        "discount": line.discount_source,
                    }
                    for line in self.quote.lines
                ],
            }
        if self.budget_check is not None:
            payload["budget"] = {
                "within": self.budget_check.within_budget,
                "budget": self.budget_check.budget.format(),
                "unit_price": self.budget_check.unit_price.format(),
                "basis": self.budget_check.basis,
            }
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        if self.errors:
            payload["errors"] = list(self.errors)
        return payload


# ---------------------------------------------------------------------------
# Clarification rule (5.6)
# ---------------------------------------------------------------------------


def decide_questions(criteria: Criteria, products: Sequence[dict[str, Any]]) -> list[Question]:
    """Ask only when the detail is needed, absent, uninferable, and answer-changing.

    Each candidate question is tested against all four conditions. A question
    that fails any of them is not asked — asking about a detail that cannot
    change the answer wastes the customer's time and is explicitly ruled out by
    the spec.
    """
    questions: list[Question] = []

    # --- a requirement was stated but could not be mapped --------------
    # This is asked first because it invalidates every other answer: if the
    # customer asked for B5 and we quietly dropped it, the quote would be for a
    # size they did not ask for. Silence here is the failure the spec forbids,
    # so the unresolvable requirement becomes a question, not a missing filter.
    for note in criteria.notes:
        if note.startswith("size:"):
            questions.append(Question(
                "size",
                "I could not match the size you asked for to anything we stock. "
                "We carry A3, A4, A5, US Letter and US Legal. Which do you need?",
            ))
            break

    # --- ambiguity: two senses, no context ----------------------------
    # Only a genuine ambiguity is asked about. Once the category is known to be
    # plain paper ("coloured paper"), there is no printing sense to confuse it
    # with, so asking which sense was meant would be a question the customer has
    # already answered by naming the product.
    if criteria.colour_ambiguous and not _colour_is_settled_by_category(criteria):
        questions.append(Question(
            "colour",
            "When you say colour, do you mean the paper's own colour (such as "
            "white or ivory), or the colour of printing on it?",
        ))

    # --- missing quantity, when it changes the price -------------------
    # Only asked when a budget was stated, because that is when quantity
    # determines whether the item qualifies. Without a budget, quantity 1 is a
    # perfectly good default and asking would be noise.
    if criteria.quantity is None and criteria.budget_per_unit is not None:
        if _quantity_changes_the_answer(criteria, products):
            questions.append(Question(
                "quantity",
                "How many packs do you need? The per-pack price depends on the "
                "quantity, so I need it to check your budget.",
            ))

    # --- nothing understood at all -------------------------------------
    if not criteria.has_any_constraint() and not questions:
        questions.append(Question(
            "requirements",
            "What are you looking for? For example: A4 copy paper, 80 gsm, "
            "20 reams.",
        ))

    return questions[:MAX_QUESTIONS]


def _quantity_changes_the_answer(
    criteria: Criteria, products: Sequence[dict[str, Any]]
) -> bool:
    """Would a different quantity change whether anything qualifies?

    True when at least one candidate has a volume tier that could bring its unit
    price under the stated budget at some realistic quantity. If no tier could
    ever help, quantity cannot change the verdict and asking is pointless.
    """
    if criteria.budget_per_unit is None:
        return False

    from .pricing import unit_price

    budget = criteria.budget_per_unit

    def qualifies_at(quantity: int) -> set[str]:
        """Which SKUs are within budget at this quantity."""
        passing: set[str] = set()
        for product in products:
            if criteria.size_code and product.get("size_code") != criteria.size_code:
                continue
            if criteria.category and product.get("category") != criteria.category:
                continue
            if criteria.weight_gsm and product.get("weight_gsm") != criteria.weight_gsm:
                continue
            facts = _facts_for(product)
            if facts is None:
                continue
            if unit_price(facts, quantity) <= budget:
                passing.add(product["sku"])
        return passing

    baseline = qualifies_at(1)

    # Quantity changes the answer when it changes *which* items qualify — not
    # merely when some tier happens to be cheap. Comparing the qualifying sets
    # is the honest test: if the set is identical at every plausible quantity,
    # asking "how many?" cannot alter the reply and would be noise.
    for quantity in {tier["min_qty"] for product in products
                     for tier in product.get("tiers", ())}:
        if 1 < quantity <= 500 and qualifies_at(quantity) != baseline:
            return True
    return False


def _facts_for(product: dict[str, Any]) -> PriceFacts | None:
    """Rebuild PriceFacts from a catalog row, if it carries price columns."""
    if "list_price_satang" not in product:
        return None
    from .pricing import PriceTier

    return PriceFacts(
        sku=product["sku"],
        list_price=Money(product["list_price_satang"]),
        tiers=tuple(
            PriceTier(t["min_qty"], Money(t["unit_price_satang"]))
            for t in product.get("tiers", ())
        ),
        sale_price=(
            Money(product["sale_price_satang"])
            if product.get("sale_price_satang") is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Reply rendering (5.5, 5.10)
# ---------------------------------------------------------------------------


def _unit_phrase(candidate: Candidate) -> str:
    """The unit the product is actually sold in, from its sheet count."""
    sheets = candidate.product.get("pack_sheets")
    if sheets:
        return f"pack of {sheets} sheets"
    word = candidate.product.get("unit_word")
    return word or "pack"


def _describe_candidate(candidate: Candidate) -> str:
    """One product line: catalog name, unit price, and why it matches."""
    lines = [
        f"{candidate.name} ({candidate.sku})",
        f"  {candidate.unit_price.format()} per {_unit_phrase(candidate)}"
        f" — {candidate.discount_note}",
    ]
    if candidate.match_reasons:
        reasons = "; ".join(
            f"{r.attribute}: {r.actual}" for r in candidate.match_reasons
        )
        lines.append(f"  Matches — {reasons}")
    if not candidate.available:
        if candidate.stock_status == "out_of_stock":
            detail = f", back {candidate.back_in_stock_date}" if candidate.back_in_stock_date else ""
            lines.append(f"  NOT AVAILABLE — out of stock{detail}")
        else:
            lines.append("  NOT AVAILABLE — discontinued")
    return "\n".join(lines)


def _render_breakdown(order: OrderQuote) -> str:
    """The full cost breakdown, with the discount identified per line."""
    parts = ["Breakdown"]
    for line in order.lines:
        parts.append(
            f"  {line.quantity} × {line.unit_price.format()}"
            f" = {line.line_total.format()}  ({line.discount_source})"
        )
    parts.append(f"  Subtotal      {order.subtotal.format()}")
    if order.delivery.satang == 0:
        parts.append(
            f"  Delivery      0.00  (free from {FREE_DELIVERY_THRESHOLD.format()})"
        )
    else:
        parts.append(f"  Delivery      {order.delivery.format()}")
    parts.append(f"  VAT {order.vat_rate}%        {order.vat.format()}")
    parts.append(f"  Total         {order.total.format()}")
    parts.append("  All prices exclude VAT; VAT is charged on goods plus delivery.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Guards (5.8, 5.9)
# ---------------------------------------------------------------------------


def check_no_invented_products(
    text: str, known_skus: set[str]
) -> tuple[str, list[str]]:
    """Remove any SKU-shaped reference that is not in the snapshot.

    A SKU in this catalog looks like ``PL-XX-X0-...``. Any such token in the
    reply that the snapshot does not contain is stripped and reported, so a
    reply referencing an absent product is never returned as though valid.
    """
    pattern = re.compile(r"\bPL-[A-Z]{2}-[A-Z0-9-]+\b")
    found = set(pattern.findall(text))
    unknown = {sku for sku in found if sku not in known_skus}
    if not unknown:
        return text, []

    cleaned = text
    for sku in sorted(unknown):
        cleaned = re.sub(rf"\s*\(?{re.escape(sku)}\)?", "", cleaned)
    return cleaned, [
        f"removed reference to {sku}, which is not in the current snapshot"
        for sku in sorted(unknown)
    ]


#: A monetary amount in reply text: "1,234.56".
_AMOUNT = re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b|\b\d+\.\d{2}\b")


def check_figures_match(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Every amount in the text must equal a computed amount.

    ``allowed`` is the set of formatted amounts the pricing layer produced. An
    amount in the prose that is not in that set is a discrepancy, and a
    discrepancy is a defect, not a rounding artefact.
    """
    found = set(_AMOUNT.findall(text))
    stray = {amount for amount in found if amount not in allowed}
    if not stray:
        return text, []
    return text, [
        f"amount {amount} appears in the reply but was not computed by the "
        "pricing layer"
        for amount in sorted(stray)
    ]


def computed_amounts(order: OrderQuote | None) -> set[str]:
    """Every amount the pricing layer produced, formatted as the reply formats it."""
    if order is None:
        return set()
    amounts = {
        order.subtotal.format(),
        order.delivery.format(),
        order.vat.format(),
        order.total.format(),
        FREE_DELIVERY_THRESHOLD.format(),
    }
    for line in order.lines:
        amounts.add(line.unit_price.format())
        amounts.add(line.line_total.format())
        amounts.add(line.list_price.format())
    return amounts


def check_no_internal_ids(text: str, skus_in_reply: Sequence[str]) -> tuple[str, list[str]]:
    """A product must be described by its name, not by its SKU.

    The SKU is allowed to appear in parentheses as an identifier; it must not be
    the only description. This checks that every SKU mentioned is accompanied by
    a name on the same line.
    """
    warnings: list[str] = []
    for line in text.splitlines():
        for sku in skus_in_reply:
            if sku in line:
                remainder = line.replace(sku, "").replace("()", "").strip(" ()—-")
                if len(remainder) < 5:
                    warnings.append(
                        f"line describes a product only by its identifier: {sku}"
                    )
    return text, warnings


# ---------------------------------------------------------------------------
# The assistant
# ---------------------------------------------------------------------------


def _known_skus(products: Sequence[dict[str, Any]]) -> set[str]:
    return {p["sku"] for p in products}


def answer(
    criteria: Criteria,
    products: Sequence[dict[str, Any]],
    facts: dict[str, PriceFacts],
    *,
    interpretation: str = "rules",
    product_tiers: dict[str, list[dict[str, int]]] | None = None,
) -> AssistantReply:
    """Turn validated criteria into one of the four outcomes."""
    # --- clarification first: never price on a guess -------------------
    # Tier data is needed to decide whether an unstated quantity could change
    # the verdict, so it must reach the question logic. ``facts`` already holds
    # it — the tiers are loaded from the snapshot alongside the list prices —
    # so it is derived here rather than demanded from every caller. Requiring a
    # separate ``product_tiers`` argument meant the API path never supplied one
    # and the quantity question silently never fired, which is exactly the kind
    # of dead branch a passing test suite hides.
    tier_map = product_tiers
    if tier_map is None:
        tier_map = {
            sku: [
                {"min_qty": tier.min_qty,
                 "unit_price_satang": tier.unit_price.satang}
                for tier in price_facts.tiers
            ]
            for sku, price_facts in facts.items()
        }
    enriched = [
        {**p, "tiers": tier_map.get(p["sku"], [])} for p in products
    ]

    questions = decide_questions(criteria, enriched)
    if questions:
        return AssistantReply(
            outcome=OUTCOME_CLARIFIED,
            text=_render_clarification(questions, criteria),
            criteria=criteria,
            interpretation=interpretation,
            questions=tuple(questions),
        )

    quantity = criteria.quantity or 1
    result = search(criteria, products, facts, quantity=quantity)

    # --- refusal: matched but unavailable ------------------------------
    if not result.matches and result.unavailable:
        return _refuse(criteria, result, interpretation, quantity)

    # --- no match ------------------------------------------------------
    if not result.matches:
        return _no_match(criteria, result, interpretation)

    # --- quoted --------------------------------------------------------
    return _quote_reply(criteria, result, interpretation, quantity, products)


def _render_clarification(questions: Sequence[Question], criteria: Criteria) -> str:
    understood = criteria.describe()
    lines = []
    if understood:
        lines.append(
            "So far I have: "
            + ", ".join(f"{k} {v}" for k, v in understood.items())
            + "."
        )
    if len(questions) == 1:
        lines.append(questions[0].text)
    else:
        lines.append("I need two things before I can quote:")
        for index, question in enumerate(questions, start=1):
            lines.append(f"{index}. {question.text}")
    return "\n".join(lines)


def _refuse(
    criteria: Criteria, result: SearchResult, interpretation: str, quantity: int
) -> AssistantReply:
    """Refuse, distinguishing a temporary shortage from a withdrawal."""
    lines = []
    refused_items = []
    for candidate in result.unavailable:
        if candidate.stock_status == "discontinued":
            lines.append(
                f"{candidate.name} ({candidate.sku}) has been discontinued and is "
                "no longer available."
            )
        else:
            detail = (
                f" It is expected back {candidate.back_in_stock_date}."
                if candidate.back_in_stock_date
                else ""
            )
            lines.append(
                f"{candidate.name} ({candidate.sku}) is out of stock, so I cannot "
                f"quote it as a purchase today.{detail}"
            )
        refused_items.append(candidate)

    lines.append(
        "I have not quoted it, because I can only price items you can actually order."
    )
    return AssistantReply(
        outcome=OUTCOME_REFUSED,
        text="\n".join(lines),
        criteria=criteria,
        interpretation=interpretation,
        refused=tuple(refused_items),
        candidates=tuple(refused_items),
    )


def _no_match(
    criteria: Criteria, result: SearchResult, interpretation: str
) -> AssistantReply:
    lines = ["Nothing in the catalog satisfies every requirement you gave."]

    if result.alternatives and result.relaxed:
        readable = {
            "budget": "the budget",
            "finish": "the finish",
            "weight": "the weight",
            "sides": "the printing sides",
            "colour": "the colour",
            "size": "the size",
        }.get(result.relaxed, result.relaxed)
        lines.append(
            f"If you could relax {readable}, these are the closest options — "
            "they do not match your original request:"
        )
        for candidate in result.alternatives:
            lines.append(
                f"  {candidate.name} ({candidate.sku}) — "
                f"{candidate.unit_price.format()} per {_unit_phrase(candidate)} "
                f"[relaxed: {readable}]"
            )
    else:
        lines.append(
            "I also could not find anything close, so I would rather ask than "
            "offer you something that does not fit."
        )
        lines.append(
            "Could you tell me the size, weight, or quantity you need?"
        )

    return AssistantReply(
        outcome=OUTCOME_NO_MATCH,
        text="\n".join(lines),
        criteria=criteria,
        interpretation=interpretation,
        alternatives=tuple(result.alternatives),
        relaxed=result.relaxed,
    )


def _quote_reply(
    criteria: Criteria,
    result: SearchResult,
    interpretation: str,
    quantity: int,
    products: Sequence[dict[str, Any]],
) -> AssistantReply:
    """Quote the best match, with justification and a full breakdown."""
    best = result.matches[0]
    order = quote([LineRequest(best.sku, quantity, best.facts)])

    lines = [f"Best match — {best.name} ({best.sku})"]
    lines.append(f"  {best.unit_price.format()} per {_unit_phrase(best)}"
                 f" — {best.discount_note}")
    if best.match_reasons:
        reasons = "; ".join(
            f"{r.attribute}: {r.actual}" for r in best.match_reasons
        )
        lines.append(f"  Matches — {reasons}")

    if criteria.budget_per_unit is not None:
        check = check_budget(
            best.facts, quantity, criteria.budget_per_unit,
            basis=criteria.budget_basis,
        )
        lines.append("")
        lines.append(check.describe())

    if len(result.matches) > 1:
        lines.append("")
        lines.append("Other options that also match:")
        for candidate in result.matches[1:4]:
            lines.append(
                f"  {candidate.name} ({candidate.sku}) — "
                f"{candidate.unit_price.format()} per {_unit_phrase(candidate)}"
            )

    lines.append("")
    lines.append(_render_breakdown(order))

    text = "\n".join(lines)

    # --- guards, run before the reply is returned ----------------------
    errors: list[str] = []
    warnings: list[str] = []

    known = _known_skus(products)
    text, invented = check_no_invented_products(text, known)
    errors.extend(invented)

    # Every amount in the reply must be one the pricing layer produced —
    # including the unit prices of the other options that are also quoted.
    allowed = computed_amounts(order)
    for candidate in result.matches:
        allowed.add(candidate.unit_price.format())
        allowed.add(candidate.line_total.format())
        allowed.add(candidate.facts.list_price.format())
    if criteria.budget_per_unit is not None:
        allowed.add(criteria.budget_per_unit.format())
        check = check_budget(
            best.facts, quantity, criteria.budget_per_unit, basis=criteria.budget_basis
        )
        allowed.add(check.difference.format().lstrip("-"))
    text, mismatches = check_figures_match(text, allowed)
    errors.extend(mismatches)

    text, id_warnings = check_no_internal_ids(
        text, [c.sku for c in result.matches]
    )
    warnings.extend(id_warnings)

    budget = None
    if criteria.budget_per_unit is not None:
        budget = check_budget(
            best.facts, quantity, criteria.budget_per_unit, basis=criteria.budget_basis
        )

    return AssistantReply(
        outcome=OUTCOME_QUOTED,
        text=text,
        criteria=criteria,
        interpretation=interpretation,
        quote=order,
        candidates=result.matches,
        budget_check=budget,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _colour_is_settled_by_category(criteria) -> bool:
    """Does the stated category already decide which sense of "colour" applies?

    Only printed goods have a print-colour sense. Naming "Coloured paper" or
    "Copy paper" settles it: the customer wants a paper shade, so asking which
    sense they meant would re-ask a question their own words answered.

    "Flyer printing" is the opposite case — there, "colour" can only mean print
    colour, and it has already been read that way.
    """
    if criteria.category is None:
        return False
    return criteria.category != "Flyer printing"
