"""Size and weight normalisation.

The catalog states the same facts in several ways, and the obvious string
comparison silently misses rows. Verified against the real site:

Weight arrives in four published forms:

    "80 gsm"                  grammage              (16 pages)
    "90g/m²"                  grams per square metre, superscript 2   (1 page, prose)
    "20 lb bond (75 gsm)"     pounds with grammage  (2 pages)
    "20 lb bond"              pounds alone          (2 pages)

Size arrives with two encodings of the same value, and one of them uses unicode:

    "8.5 × 11 in"   9 occurrences   multiplication sign is U+00D7, not ASCII 'x'
    "8½ × 11 in"    2 occurrences   ½ is U+00BD VULGAR FRACTION ONE HALF

Both spellings appear on the *same* two flyer pages, so a filter written as a
string match can pass or fail depending on which occurrence it reads.
Normalising to a code at ingest removes that class of bug entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# ---------------------------------------------------------------------------
# Weight
# ---------------------------------------------------------------------------

#: The conversion table from the brief, treated as the agreed specification:
#: "20 lb = 75 gsm, 24 lb = 90 gsm, 28 lb = 105 gsm, 32 lb = 120 gsm."
#:
#: Only 20 lb and 24 lb actually appear in the reference site (and both appear
#: *with* their grammage stated, which cross-checks the table). 28 lb and 32 lb
#: are implemented from the agreed table but are unexercised by v1 data.
POUND_TO_GSM: dict[int, int] = {
    20: 75,
    24: 90,
    28: 105,
    32: 120,
}


class WeightError(ValueError):
    """Raised when a weight string cannot be normalised."""


@dataclass(frozen=True)
class Weight:
    """A normalised paper weight.

    ``gsm`` is always populated. ``raw`` keeps the source string so a
    conversion can be defended in the interview, and ``form`` records which of
    the four published shapes it came from.
    """

    gsm: int
    raw: str
    form: str  # gsm | g_per_m2 | lb_with_gsm | lb_only

    def __str__(self) -> str:
        return f"{self.gsm} gsm"


#: U+00B2 SUPERSCRIPT TWO, which the site uses in "90g/m²".
_SUPER2 = "\u00b2"

# Patterns are ordered: the most specific first, so "20 lb bond (75 gsm)"
# is not mistaken for a plain "75 gsm" reading.
_RE_LB_WITH_GSM = re.compile(
    r"(\d+(?:\.\d+)?)\s*lb\b[^()]*\(\s*(\d+(?:\.\d+)?)\s*gsm\s*\)", re.IGNORECASE
)
_RE_LB_ONLY = re.compile(r"(\d+(?:\.\d+)?)\s*lb\b", re.IGNORECASE)
_RE_G_PER_M2 = re.compile(r"(\d+(?:\.\d+)?)\s*g\s*/\s*m" + _SUPER2 + r"|(\d+(?:\.\d+)?)\s*g/m2", re.IGNORECASE)
_RE_GSM = re.compile(r"(\d+(?:\.\d+)?)\s*gsm\b", re.IGNORECASE)


def pounds_to_gsm(pounds: Decimal | int | str) -> int:
    """Convert a US bond pound weight to grammage using the agreed table.

    An unlisted pound value raises rather than extrapolating. Guessing a
    conversion would put a number in a quote that no source supports, and the
    brief's table is explicitly the agreed specification.
    """
    value = Decimal(str(pounds))
    if value != value.to_integral_value():
        raise WeightError(
            f"non-integer pound weight {value!r} has no entry in the agreed "
            f"conversion table {sorted(POUND_TO_GSM)}"
        )
    key = int(value)
    if key not in POUND_TO_GSM:
        raise WeightError(
            f"{key} lb has no entry in the agreed conversion table "
            f"{sorted(POUND_TO_GSM)}; refusing to extrapolate"
        )
    return POUND_TO_GSM[key]


def parse_weight(raw: str) -> Weight:
    """Normalise any of the four published weight forms to grammage.

    Raises :class:`WeightError` when the string carries no recognisable weight,
    so that an unparsed page becomes a visible review row rather than a silently
    missing attribute.
    """
    if raw is None:
        raise WeightError("weight is None")
    text = " ".join(str(raw).split())
    if not text:
        raise WeightError("weight is empty")

    # 1. pounds with grammage stated in parentheses — the source cross-check.
    #    If both forms are present they must agree, so we verify rather than
    #    trust the grammage blindly.
    m = _RE_LB_WITH_GSM.search(text)
    if m:
        pounds, stated = Decimal(m.group(1)), int(Decimal(m.group(2)))
        derived = pounds_to_gsm(pounds)
        if derived != stated:
            raise WeightError(
                f"weight source disagrees with the agreed table: {text!r} states "
                f"{stated} gsm but {int(pounds)} lb converts to {derived} gsm"
            )
        return Weight(gsm=stated, raw=text, form="lb_with_gsm")

    # 2. grams per square metre, either with a superscript 2 or written g/m2.
    m = _RE_G_PER_M2.search(text)
    if m:
        value = m.group(1) or m.group(2)
        return Weight(gsm=int(Decimal(value)), raw=text, form="g_per_m2")

    # 3. pounds alone — no grammage given, so the table is the only source.
    m = _RE_LB_ONLY.search(text)
    if m:
        pounds = Decimal(m.group(1))
        return Weight(gsm=pounds_to_gsm(pounds), raw=text, form="lb_only")

    # 4. plain grammage.
    m = _RE_GSM.search(text)
    if m:
        return Weight(gsm=int(Decimal(m.group(1))), raw=text, form="gsm")

    raise WeightError(f"no recognisable weight in {text!r}")


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------

#: U+00D7 MULTIPLICATION SIGN, which the site uses between dimensions.
MULT_SIGN = "\u00d7"

#: U+00BD VULGAR FRACTION ONE HALF.
HALF = "\u00bd"

#: Canonical size codes, with their millimetre dimensions. The brief's example
#: request is Letter; the catalog also carries A3/A4/A5 and US Legal.
SIZE_DIMENSIONS_MM: dict[str, tuple[int, int]] = {
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "LTR": (216, 279),   # US Letter, 8.5 x 11 in
    "LGL": (216, 356),   # US Legal, 8.5 x 14 in
}

#: Alternate names customers and the site use for a size code.
SIZE_ALIASES: dict[str, str] = {
    "letter": "LTR",
    "us letter": "LTR",
    "8.5x11": "LTR",
    "8.5 x 11": "LTR",
    "8.5x11 in": "LTR",
    "8.5 x 11 in": "LTR",
    "8½x11": "LTR",
    "8½ x 11": "LTR",
    "8½ x 11 in": "LTR",
    "8½x11 in": "LTR",
    "legal": "LGL",
    "us legal": "LGL",
    "8.5x14": "LGL",
    "8.5 x 14": "LGL",
    "8.5 x 14 in": "LGL",
}

_SIZE_CODE_RE = re.compile(r"\b(A[345])\b", re.IGNORECASE)
# Dimension pairs, tolerating either a multiplication sign or ASCII x/X/*.
_DIM_RE = re.compile(
    r"(\d+(?:\.\d+)?|\d*" + HALF + r")\s*[" + MULT_SIGN + r"xX*]\s*(\d+(?:\.\d+)?|\d*" + HALF + r")"
)

_INCH_TO_MM = Decimal("25.4")


class SizeError(ValueError):
    """Raised when a size string cannot be normalised to a code."""


def _number(token: str) -> Decimal:
    """Parse a dimension token, understanding the vulgar fraction half."""
    token = token.strip()
    if token.endswith(HALF):
        head = token[: -len(HALF)]
        return (Decimal(head) if head else Decimal(0)) + Decimal("0.5")
    return Decimal(token)


def parse_size(raw: str) -> tuple[str, int, int]:
    """Normalise a size string to ``(code, width_mm, height_mm)``.

    Handles all three spellings seen in the catalog: an explicit code ("A4"),
    decimal inches ("8.5 × 11 in"), and vulgar-fraction inches ("8½ × 11 in").
    Raises :class:`SizeError` when nothing maps, so the page surfaces as a
    review row instead of an unmatchable NULL.
    """
    if raw is None:
        raise SizeError("size is None")
    text = " ".join(str(raw).split())
    if not text:
        raise SizeError("size is empty")

    # 1. An explicit code, optionally followed by dimensions.
    m = _SIZE_CODE_RE.search(text)
    if m:
        code = m.group(1).upper()
        if code in SIZE_DIMENSIONS_MM:
            width, height = SIZE_DIMENSIONS_MM[code]
            return code, width, height

    # 2. Dimensions in inches — covers both 8.5 and 8½.
    m = _DIM_RE.search(text)
    if m:
        a, b = _number(m.group(1)), _number(m.group(2))
        if "mm" in text.lower():
            return _match_mm(a, b, text)
        return _match_inches(a, b, text)

    # 3. A known alias such as "letter" or "legal".
    key = text.lower().strip()
    if key in SIZE_ALIASES:
        code = SIZE_ALIASES[key]
        width, height = SIZE_DIMENSIONS_MM[code]
        return code, width, height

    raise SizeError(f"no recognisable size in {text!r}")


def _match_inches(a: Decimal, b: Decimal, raw: str) -> tuple[str, int, int]:
    for code, (width, height) in SIZE_DIMENSIONS_MM.items():
        if (
            abs(Decimal(width) / _INCH_TO_MM - a) < Decimal("0.05")
            and abs(Decimal(height) / _INCH_TO_MM - b) < Decimal("0.05")
        ):
            return code, width, height
    raise SizeError(f"inches {a} x {b} match no known size ({raw!r})")


def _match_mm(a: Decimal, b: Decimal, raw: str) -> tuple[str, int, int]:
    for code, (width, height) in SIZE_DIMENSIONS_MM.items():
        if abs(Decimal(width) - a) <= 2 and abs(Decimal(height) - b) <= 2:
            return code, width, height
    raise SizeError(f"mm {a} x {b} match no known size ({raw!r})")
