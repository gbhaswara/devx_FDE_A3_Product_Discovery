"""Search criteria: what a customer asked for, in catalog vocabulary.

A ``Criteria`` object is the *only* thing that crosses from the interpretation
layer into the search layer. It contains no prices, no SKUs, and no free text
that could be mistaken for an instruction — just typed requirements, each of
which is either a hard constraint or a soft preference.

Two fields deserve their own explanation, because the catalog is genuinely
ambiguous about them:

``colour_name`` vs ``colour_mode``
    "Colour" means the paper's shade on plain paper and the print colour mode
    on printed goods. They are separate fields and are never inferred from each
    other. When a request says "colour" without a noun to disambiguate it,
    ``colour_ambiguous`` is set and the assistant asks.

``sides``
    Only meaningful for printed goods. ``None`` means "not constrained", which
    is different from "must be single-sided".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .money import Money


@dataclass(frozen=True)
class Criteria:
    """A customer's requirements, typed.

    Every attribute is optional; ``None`` means "not stated", never "false" or
    "zero". That distinction is what keeps a printing constraint from excluding
    plain paper.
    """

    # --- identity ------------------------------------------------------
    raw_text: str = ""
    category: str | None = None

    # --- paper attributes ----------------------------------------------
    size_code: str | None = None
    weight_gsm_min: int | None = None
    weight_gsm_max: int | None = None
    weight_gsm: int | None = None          # exact, when stated exactly
    colour_name: str | None = None         # paper SHADE
    finish: str | None = None

    # --- printing attributes (meaningful only for printed goods) -------
    sides: str | None = None               # "single" | "double"
    colour_mode: str | None = None         # print colour mode

    # --- commercial ----------------------------------------------------
    quantity: int | None = None
    budget_per_unit: Money | None = None
    budget_basis: str = "per pack, before VAT"

    # --- meta ----------------------------------------------------------
    #: Set when "colour" was used and nothing disambiguated it. The assistant
    #: asks rather than guessing.
    colour_ambiguous: bool = False
    #: Preferences that rank but never exclude.
    prefer_cheapest: bool = True
    prefer_in_stock: bool = True
    #: Free-text hints the model produced that are not filterable. Kept for
    #: disclosure only; never used to filter.
    notes: tuple[str, ...] = ()

    def has_any_constraint(self) -> bool:
        """Is there anything to search on at all?"""
        return any(
            value is not None
            for value in (
                self.size_code, self.weight_gsm, self.weight_gsm_min,
                self.weight_gsm_max, self.colour_name, self.finish,
                self.sides, self.colour_mode, self.category,
            )
        )

    def describe(self) -> dict[str, object]:
        """A stable, JSON-safe description of what was understood.

        This is what the reply echoes back, so a customer can see exactly which
        requirements the system applied and correct any it misread.
        """
        described: dict[str, object] = {}
        if self.category:
            described["category"] = self.category
        if self.size_code:
            described["size"] = self.size_code
        if self.weight_gsm is not None:
            described["weight_gsm"] = self.weight_gsm
        if self.weight_gsm_min is not None:
            described["weight_gsm_min"] = self.weight_gsm_min
        if self.weight_gsm_max is not None:
            described["weight_gsm_max"] = self.weight_gsm_max
        if self.colour_name:
            described["colour_shade"] = self.colour_name
        if self.colour_mode:
            described["colour_mode"] = self.colour_mode
        if self.finish:
            described["finish"] = self.finish
        if self.sides:
            described["sides"] = self.sides
        if self.quantity is not None:
            described["quantity"] = self.quantity
        if self.budget_per_unit is not None:
            described["budget_per_unit"] = self.budget_per_unit.format()
            described["budget_basis"] = self.budget_basis
        return described
