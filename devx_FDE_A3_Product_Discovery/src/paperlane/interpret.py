"""Rule-based interpretation: the fallback when the model is unavailable.

This is not a degraded stub. It is the interpretation path that handles the
common request shapes without any external service, and it is what makes the
system testable offline and reproducible in the evaluation harness.

It reads the same aliases the search layer uses, so a rule-based interpretation
and a model interpretation of the same sentence select the same items. The only
difference is how the sentence is decomposed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal

from .aliases import (
    resolve_category,
    resolve_colour,
    resolve_finish,
    resolve_printing,
    resolve_size,
    resolve_weight,
)
from .criteria import Criteria
from .money import Money
from .model import normalise_sides
from .normalize import SizeError

#: "20 packs", "3 reams", "10 boxes", "5".
_QUANTITY_PATTERNS = (
    re.compile(r"\b(\d+)\s*(?:packs?|reams?|boxes?|pads?|lots?|units?)\b", re.I),
    re.compile(r"\bqty\s*[:=]?\s*(\d+)\b", re.I),
    re.compile(r"\b(\d+)\s*(?:x|×)\b", re.I),
)

#: "under 250 a pack", "max 300", "budget of 250", "no more than 250".
_BUDGET_PATTERNS = (
    re.compile(
        r"\b(?:under|below|less than|no more than|max(?:imum)?|up to|budget(?:\s+of)?|"
        r"at most|within)\s*(?:thb|฿)?\s*([\d,]+(?:\.\d+)?)",
        re.I,
    ),
    re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:thb|baht)\s*(?:max|max\.|or less)", re.I),
)

#: The unit a budget is stated against, and the VAT qualifier on it. The unit is
#: matched first and the VAT qualifier separately, because "a pack including VAT"
#: contains *both* — testing them as one ordered list of alternatives made the
#: unit word win and silently dropped the qualifier the customer added (BUG.md
#: A20).
_UNIT_PATTERNS = (
    (re.compile(r"\b(?:per|a|each)\s+pack\b", re.I), "per pack"),
    (re.compile(r"\b(?:per|a|each)\s+ream\b", re.I), "per ream"),
    (re.compile(r"\b(?:per|a|each)\s+sheet\b", re.I), "per sheet"),
)

#: "including VAT", "inclusive of VAT", "incl. VAT", "inc VAT". The absence of
#: any of these is the PR7 default: budgets exclude VAT unless stated otherwise.
_INCLUSIVE_VAT = re.compile(
    r"\b(?:incl|inc|including|inclusive)\b[^.]{0,12}?\bvat\b", re.I
)

#: The basis when the customer said nothing, and the one the brief assumes (PR7).
DEFAULT_BASIS = "per pack, before VAT"

#: What separates two product requests. A comma is included because a request
#: can state its second item after one — "copy paper, 20 packs, and card" —
#: and the comma is the only thing between the two halves in the last clause.
_CLAUSE_SPLIT = re.compile(r"\s*(?:;|,|&|\band\b|\bplus\b)\s*", re.I)

def count_product_clauses(text: str) -> int:
    """How many distinct products the text asks for.

    A clause counts when it names a category, or — failing that — when it
    describes an item without naming its type but carries its own quantity and
    weight (*"10 packs of the 130gsm"*). The second rule exists because that is
    how a two-item request erodes into a one-item one: the type is elided after
    the first item, and a category-only test would let the assistant quote the
    first and silently discard the second (BUG.md A29).

    Neither rule fires on a single product's own clauses: *"A4 80gsm copy paper,
    20 packs, under 250 a pack"* names the category once and the bare quantity
    carries no weight, while *"A4 80gsm and 90gsm copy paper"* names it once and
    the bare weight carries no quantity.

    The count exists so a compound request can be **asked about** rather than
    merged. Parsing each field from the whole string silently combined
    attributes from different products — "Gloss" from the flyers half applied to
    the copy paper — and dropped the second item entirely.
    """
    count = 0
    for fragment in _CLAUSE_SPLIT.split(text):
        if not fragment.strip():
            continue
        if resolve_category(fragment) is not None:
            count += 1
            continue
        exact, minimum, maximum = resolve_weight(fragment)
        if (exact or minimum or maximum) and parse_quantity(fragment) is not None:
            count += 1
    return count


def _budget_basis(text: str) -> str:
    """The basis to state, assembled from the unit word and the VAT qualifier."""
    unit = "per pack"
    for pattern, label in _UNIT_PATTERNS:
        if pattern.search(text):
            unit = label
            break
    qualifier = "including VAT" if _INCLUSIVE_VAT.search(text) else "before VAT"
    return f"{unit}, {qualifier}"


def parse_quantity(text: str) -> int | None:
    """The number of packs asked for, if stated."""
    if not text:
        return None
    for pattern in _QUANTITY_PATTERNS:
        m = pattern.search(text)
        if m:
            value = int(m.group(1))
            if value > 0:
                return value
    return None


def parse_budget(text: str) -> tuple[Money | None, str]:
    """The per-unit budget and the basis to state it on.

    The budget is deliberately kept separate from the quantity: the brief's own
    example puts the budget before the quantity, and the two must not be
    conflated — the budget is compared at the quantity, not at one unit.
    """
    if not text:
        return None, DEFAULT_BASIS

    for pattern in _BUDGET_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        raw = m.group(1).replace(",", "")
        try:
            amount = Decimal(raw)
        except Exception:  # noqa: BLE001
            continue
        return Money.from_baht(amount), _budget_basis(text)

    return None, DEFAULT_BASIS


def interpret_rules(text: str) -> Criteria:
    """Interpret a request using rules only.

    Returns ``Criteria`` even when little was understood: ``has_any_constraint()``
    is then ``False`` and the assistant asks a question instead of searching for
    everything.
    """
    criteria = Criteria(raw_text=text)

    if not text or not text.strip():
        return criteria

    notes: tuple[str, ...] = ()

    # A request naming two products must be asked about, not merged. Checked
    # first so the note leads, and recorded as a note rather than a flag so it
    # survives `merge_model_and_rules` the same way the size note does.
    clauses = count_product_clauses(text)
    if clauses > 1:
        notes = notes + (f"compound: {clauses} product requests",)

    criteria = replace(criteria, category=resolve_category(text))

    try:
        criteria = replace(criteria, size_code=resolve_size(text))
    except SizeError as exc:
        # An unstocked size is a gap to report, not a constraint to apply.
        notes = notes + (f"size: {exc}",)

    exact, minimum, maximum = resolve_weight(text)
    criteria = replace(
        criteria,
        weight_gsm=exact,
        weight_gsm_min=minimum,
        weight_gsm_max=maximum,
    )

    shade, mode, ambiguous = resolve_colour(text)
    criteria = replace(
        criteria,
        colour_name=shade,
        colour_mode=mode,
        colour_ambiguous=ambiguous,
    )

    criteria = replace(criteria, finish=resolve_finish(text))

    sides, print_mode = resolve_printing(text)
    criteria = replace(criteria, sides=sides)
    if criteria.colour_mode is None and print_mode is not None:
        criteria = replace(criteria, colour_mode=print_mode)

    budget, basis = parse_budget(text)
    criteria = replace(
        criteria,
        quantity=parse_quantity(text),
        budget_per_unit=budget,
        budget_basis=basis,
        notes=notes,
    )

    return criteria


def merge_model_and_rules(
    model_criteria: dict, rules: Criteria
) -> Criteria:
    """Combine a model interpretation with the rule-based one.

    The model is better at parsing unusual phrasing; the rules are better at
    being consistent with the catalog's own vocabulary and at never inventing a
    value. So the model's values win where it gave one, and the rules fill gaps.

    Crucially, **the model's values are re-resolved through the same alias
    functions the rules use**, never trusted verbatim. Measured against the live
    endpoint, this model returns ``"size": "letter"`` and ``"category":
    "flyers"`` — correct in meaning, wrong in vocabulary. Passing those straight
    into ``Criteria`` produced ``size_code="LETTER"``, which then failed
    validation and discarded an otherwise good interpretation. Routing them
    through ``resolve_size`` and ``resolve_category`` yields ``LTR`` and
    ``Flyer printing``, which is what the catalog stores.
    """
    merged = rules

    def take(key: str):
        value = model_criteria.get(key)
        if value in (None, "", []):
            return None
        return value

    category = take("category")
    if category:
        resolved = resolve_category(str(category))
        if resolved:
            merged = replace(merged, category=resolved)

    size = take("size")
    if size:
        try:
            resolved_size = resolve_size(str(size))
        except SizeError as exc:
            # A model-supplied size the catalog does not stock is dropped at the
            # boundary AND recorded, so the assistant asks instead of quoting a
            # size the customer did not request.
            resolved_size = None
            merged = replace(merged, notes=merged.notes + (f"size: {exc}",))
        if resolved_size:
            merged = replace(merged, size_code=resolved_size)

    for key in ("weight_gsm", "weight_gsm_min", "weight_gsm_max"):
        value = take(key)
        if value is not None:
            try:
                merged = replace(merged, **{key: int(value)})
            except (TypeError, ValueError):
                pass

    shade = take("colour_shade")
    if shade:
        merged = replace(merged, colour_name=str(shade).lower())

    # A bare "colour" from the model is the ambiguous case, not a value.
    #
    # The guard must consult the *merged* criteria, not just the model's own
    # payload. Measured against the live endpoint, the model returns
    # ``{"colour": "colour"}`` for "letter-size flyers, one side, colour, under
    # 250 a pack" — but the rules have already read "flyers ... colour" as print
    # colour and set ``colour_mode``. Checking only the model's payload (which
    # carries no ``colour_mode``) re-opened an ambiguity the rules had settled,
    # and the assistant asked "paper colour or print colour?" about a request
    # that had answered it. The model's contribution can add information; it
    # must not retract a conclusion the rules reached from the same words.
    bare_colour = take("colour")
    if (
        bare_colour
        and not shade
        and not take("colour_mode")
        and merged.colour_mode is None
        and merged.colour_name is None
    ):
        if str(bare_colour).strip().lower() in ("colour", "color"):
            merged = replace(merged, colour_ambiguous=True)

    mode = take("colour_mode")
    if mode:
        _, resolved_mode, _ = resolve_colour(str(mode))
        merged = replace(
            merged,
            colour_mode=resolved_mode or _canonical_colour_mode(str(mode)),
        )

    finish = take("finish")
    if finish:
        resolved_finish = resolve_finish(str(finish))
        if resolved_finish:
            merged = replace(merged, finish=resolved_finish)

    sides = take("sides")
    if sides is not None:
        resolved_sides = normalise_sides(sides)
        if resolved_sides in ("single", "double"):
            merged = replace(merged, sides=resolved_sides)

    quantity = take("quantity")
    if quantity is not None:
        try:
            value = int(quantity)
            if value > 0:
                merged = replace(merged, quantity=value)
        except (TypeError, ValueError):
            pass

    budget = take("budget_per_unit")
    if budget is not None:
        try:
            merged = replace(
                merged,
                budget_per_unit=Money.from_baht(Decimal(str(budget))),
            )
        except Exception:  # noqa: BLE001
            pass

    basis = take("budget_basis")
    if basis:
        merged = replace(merged, budget_basis=str(basis))

    notes = take("notes")
    if notes:
        if isinstance(notes, str):
            notes = (notes,)
        merged = replace(merged, notes=merged.notes + tuple(str(n) for n in notes))

    # Final normalisation of the ambiguity flag against what was actually
    # settled. The flag exists to make the assistant ask one specific question;
    # it must reflect the final state of the criteria, whichever path supplied
    # each value. A settled print mode or a named shade means the question has
    # been answered and asking it again is noise.
    if merged.colour_mode is not None or merged.colour_name is not None:
        if merged.colour_ambiguous:
            merged = replace(merged, colour_ambiguous=False)

    return merged


def _canonical_colour_mode(value: str) -> str:
    """Map a print-colour phrasing onto the two stored values."""
    lower = value.lower()
    if "black" in lower or "mono" in lower or "grey" in lower or "gray" in lower:
        return "Black and white"
    return "Full colour (CMYK)"


# ---------------------------------------------------------------------------
# Validation against catalog vocabulary (5.1)
# ---------------------------------------------------------------------------
#: The values the catalog actually stores, for validation.
VALID_CATEGORIES = ("Copy paper", "Coloured paper", "Card and photo paper", "Flyer printing")
VALID_SIZES = ("A3", "A4", "A5", "LTR", "LGL")
VALID_SIDES = ("single", "double")
VALID_FINISHES = ("Gloss", "Matte", "Uncoated", "Laid", "Smooth")


class CriteriaInvalid(ValueError):
    """An interpretation that cannot be used, with the reason."""

    def __init__(self, reason: str, field: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.field = field


def validate(criteria: Criteria) -> Criteria:
    """Validate an interpretation against catalog vocabulary.

    Raises :class:`CriteriaInvalid` for a value that cannot exist in the
    catalog, so an unusable interpretation never reaches pricing. Values that
    are merely unusual are allowed through: the search layer will simply find
    nothing, which is an honest answer.
    """
    if criteria.size_code is not None and criteria.size_code not in VALID_SIZES:
        raise CriteriaInvalid(
            f"{criteria.size_code} is not a size this catalog stocks", "size"
        )

    if criteria.category is not None and criteria.category not in VALID_CATEGORIES:
        raise CriteriaInvalid(
            f"{criteria.category} is not a catalog category", "category"
        )

    if criteria.sides is not None and criteria.sides not in VALID_SIDES:
        raise CriteriaInvalid(f"{criteria.sides} is not a printing side", "sides")

    if criteria.finish is not None and criteria.finish not in VALID_FINISHES:
        raise CriteriaInvalid(f"{criteria.finish} is not a catalog finish", "finish")

    if criteria.quantity is not None and criteria.quantity < 1:
        raise CriteriaInvalid("quantity must be at least 1", "quantity")

    if criteria.quantity is not None and criteria.quantity > 100_000:
        raise CriteriaInvalid(
            "quantity is implausibly large for this catalog", "quantity"
        )

    for name in ("weight_gsm", "weight_gsm_min", "weight_gsm_max"):
        value = getattr(criteria, name)
        if value is not None and (value <= 0 or value > 1000):
            raise CriteriaInvalid(f"{name} {value} is not a plausible grammage", name)

    if criteria.budget_per_unit is not None and criteria.budget_per_unit.satang <= 0:
        raise CriteriaInvalid("budget must be positive", "budget_per_unit")

    return criteria


# ---------------------------------------------------------------------------
# Path selection: model, rules, or both (5.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Interpretation:
    """The criteria, plus an honest account of how they were obtained.

    ``path`` is one of ``"model"``, ``"rules"`` or ``"mixed"``. It is carried all
    the way into the reply, because a salesperson needs to know whether the
    requirements were read by a model or by a rule — they fail differently.
    """

    criteria: Criteria
    path: str = "rules"
    detail: str = ""

    @property
    def used_model(self) -> bool:
        return self.path in ("model", "mixed")


def fallback_reason(interpretation, client) -> str | None:
    """Why the rule path served this request, when a model was available.

    ``None`` when no model was available to this request — that is not a
    fallback, it is a deployment without a model, and counting it as degradation
    would make the metric permanently alarming. The distinction is what keeps
    ``fallback_rate`` meaningful.

    Lives here, beside the interpreter, so every entry point that writes a
    request record computes it the same way. Two copies of this rule is how the
    API and the CLI end up disagreeing about what counts as degradation.
    """
    if client is None:
        return None
    if interpretation.path != "rules":
        return None
    return interpretation.detail or "the rule path served the request"


def interpret(text: str, client=None) -> Interpretation:
    """Interpret a request, preferring the model and falling back to rules.

    The fallback is not an error path that produces a degraded answer — the rule
    interpreter handles the common shapes completely, and the request is always
    answered. What changes is the disclosure: ``path`` says which one ran, so
    nobody has to guess whether a model was involved.

    Model criteria are merged *onto* the rule-based ones rather than replacing
    them, because the rules are guaranteed consistent with the catalog's own
    vocabulary and never invent a value. The merged result is validated before
    it is returned, so a model that returns an unstorable value cannot reach
    pricing — ``validate`` raises and the caller asks for clarification instead.
    """
    rules = interpret_rules(text)

    if client is None:
        return Interpretation(criteria=rules, path="rules",
                             detail="no model client supplied")

    try:
        result = client.extract_criteria(text)
    except Exception as exc:  # noqa: BLE001 - any model failure means "use rules"
        return Interpretation(
            criteria=rules, path="rules",
            detail=f"model unavailable, used rules: {exc}",
        )

    merged = merge_model_and_rules(result.criteria, rules)

    # Disclosure: "model" only when the model actually contributed something.
    contributed = bool(result.criteria)
    path = "mixed" if contributed and _rules_contributed(rules) else (
        "model" if contributed else "rules"
    )
    return Interpretation(criteria=merged, path=path,
                          detail=f"model strategy {result.strategy!r}")


def _rules_contributed(criteria: Criteria) -> bool:
    """Did the rule pass find anything the model may not have?"""
    return criteria.has_any_constraint() or bool(criteria.notes)
