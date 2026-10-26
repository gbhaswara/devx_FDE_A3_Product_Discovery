"""Money: integer satang, explicit half-up rounding.

Every monetary amount in this system is an integer number of satang (1/100 of a
baht). Nothing in the money path touches ``float``: binary floating point cannot
represent 0.1 exactly, so 0.1 + 0.2 != 0.3, and a quote that is one satang out is
a visible failure in this assignment.

Rounding happens in exactly one place — :func:`round_half_up` — and is
half-up (away from zero on an exact half) because that is what PR5 specifies.
Python's built-in ``round()`` is half-to-even, so it cannot be used for money.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

#: There are 100 satang in one baht.
SATANG_PER_BAHT = 100

#: The currency subdivision, as a Decimal exponent. Used only for quantising.
_CENT = Decimal("0.01")


def round_half_up(value: Decimal) -> Decimal:
    """Round a Decimal to 2 decimal places, half away from zero.

    This is the single rounding point for the whole system. PR5 requires
    "rounded half-up to 2 decimals", and an exact half must round away from
    zero, which is ``ROUND_HALF_UP`` — not Python's default ``ROUND_HALF_EVEN``.

    ``value`` must already be a Decimal. Passing a float here would reintroduce
    the representation error the whole module exists to avoid.
    """
    if not isinstance(value, Decimal):
        raise TypeError(
            f"money rounding requires Decimal, got {type(value).__name__}; "
            "convert with Decimal(str(x)) at the boundary, never Decimal(float)"
        )
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def to_satang(baht: Decimal | str | int) -> int:
    """Convert a baht amount to integer satang.

    Accepts ``Decimal``, ``str``, or ``int``. A ``float`` is rejected outright:
    the source JSON is parsed with ``parse_float=Decimal`` precisely so that no
    float is ever constructed, and silently accepting one here would undo that.
    """
    if isinstance(baht, float):
        raise TypeError(
            "refusing float in the money path; parse JSON with parse_float=Decimal "
            "and pass a Decimal or str instead"
        )
    if isinstance(baht, int):
        return baht * SATANG_PER_BAHT
    dec = baht if isinstance(baht, Decimal) else Decimal(str(baht))
    return int(round_half_up(dec) * SATANG_PER_BAHT)


def to_baht(satang: int) -> Decimal:
    """Convert integer satang back to a Decimal baht amount, for display only."""
    if not isinstance(satang, int):
        raise TypeError(f"satang must be int, got {type(satang).__name__}")
    return (Decimal(satang) / SATANG_PER_BAHT).quantize(_CENT)


def format_baht(satang: int) -> str:
    """Format satang as a plain grouped amount, e.g. ``4,664.00``.

    Deliberately no currency symbol and no localisation: the reply is pasted
    into a chat client, so the string must be stable and unambiguous.
    """
    value = to_baht(satang)
    return f"{value:,.2f}"


@dataclass(frozen=True, order=True)
class Money:
    """An exact monetary amount, stored as integer satang.

    Frozen and ordered so it can be compared and sorted without surprises.
    There is intentionally no arithmetic that accepts a float.
    """

    satang: int

    def __post_init__(self) -> None:
        if not isinstance(self.satang, int) or isinstance(self.satang, bool):
            raise TypeError(
                f"Money must be constructed from int satang, got "
                f"{type(self.satang).__name__}"
            )

    # --- constructors -------------------------------------------------
    @classmethod
    def from_baht(cls, baht: Decimal | str | int) -> "Money":
        return cls(to_satang(baht))

    @classmethod
    def zero(cls) -> "Money":
        return cls(0)

    # --- arithmetic (integer only) ------------------------------------
    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.satang + other.satang)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.satang - other.satang)

    def __mul__(self, quantity: int) -> "Money":
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise TypeError(
                f"Money may only be multiplied by an int quantity, got "
                f"{type(quantity).__name__}"
            )
        return Money(self.satang * quantity)

    __rmul__ = __mul__

    def __neg__(self) -> "Money":
        return Money(-self.satang)

    # --- presentation --------------------------------------------------
    @property
    def baht(self) -> Decimal:
        return to_baht(self.satang)

    def format(self) -> str:
        return format_baht(self.satang)

    def __str__(self) -> str:
        return self.format()


def percent_of(amount: Money, percent: Decimal, *, rate_denominator: Decimal | None = None) -> Money:
    """Return ``percent``% of ``amount``, rounded half-up to the satang.

    Used for VAT. Computed in Decimal, then rounded once — never accumulated in
    float and never rounded twice, which is how totals drift.
    """
    raw = (Decimal(amount.satang) * percent) / Decimal(100)
    if rate_denominator is not None:
        raw = raw / rate_denominator
    return Money(to_satang(round_half_up(raw / SATANG_PER_BAHT)))
