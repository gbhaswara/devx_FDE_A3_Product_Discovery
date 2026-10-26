"""Aliases: everyday and trade phrasings mapped onto catalog vocabulary.

Customers do not speak in the catalog's field values. They say "letter",
"8½ by 11", "double sided full colour", "4/4", "about 100 gsm". Each of those
must resolve to the same stored value, or the same request selects different
items depending on how it was worded.

Every alias table here is keyed on the *normalised* form (lowercased, collapsed
whitespace) and resolves to a catalog value. The tables are deliberately
explicit rather than fuzzy: a wrong fuzzy match silently returns the wrong
product, which is worse than returning nothing.
"""

from __future__ import annotations

import re
from decimal import Decimal

from .normalize import HALF, MULT_SIGN, SizeError, parse_size

# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------

#: Trade names and imperial dimensions, all resolving to a size code.
SIZE_ALIASES: dict[str, str] = {
    # codes themselves
    "a3": "A3", "a4": "A4", "a5": "A5",
    # US names
    "letter": "LTR",
    "us letter": "LTR",
    "letter size": "LTR",
    "letter-size": "LTR",
    "legal": "LGL",
    "us legal": "LGL",
    "legal size": "LGL",
    # imperial dimensions, both spellings and both separators
    "8.5 x 11": "LTR",
    "8.5x11": "LTR",
    "8.5 x 11 in": "LTR",
    "8.5x11 in": "LTR",
    "8.5 by 11": "LTR",
    "8.5 by 11 in": "LTR",
    "8½ x 11": "LTR",
    "8½x11": "LTR",
    "8½ x 11 in": "LTR",
    "8½ by 11": "LTR",
    "8.5 x 14": "LGL",
    "8.5x14": "LGL",
    "8.5 by 14": "LGL",
    "8.5 x 14 in": "LGL",
}

#: ISO dimensions in millimetres.
SIZE_BY_MM: dict[tuple[int, int], str] = {
    (297, 420): "A3",
    (210, 297): "A4",
    (148, 210): "A5",
    (216, 279): "LTR",
    (216, 356): "LGL",
}

_SIZE_PATTERN = re.compile(
    r"\b(a[345])\b"
    r"|\b(ltr|lgl)\b"
    r"|\b(letter|legal)\b(?:\s*size)?"
    r"|(\d+(?:\.\d+)?|\d*" + HALF + r")\s*(?:x|by|" + MULT_SIGN + r"|\*)\s*"
    r"(\d+(?:\.\d+)?|\d*" + HALF + r")\s*(in|inch|inches|mm)?",
    re.IGNORECASE,
)

#: ISO size codes that exist as paper but are not stocked by this catalog.
#: Recognising them is what turns "B5" into a reported gap rather than a
#: silent no-op that would return A4 items as though they matched.
_UNSTOCKED_SIZE_CODES = re.compile(r"\b([ABC]\d{1,2})\b", re.IGNORECASE)


def resolve_size(text: str) -> str | None:
    """Find a size code anywhere in a request.

    Handles ``A4``, ``letter``, ``8.5 x 11``, ``8½ by 11 in`` and
    ``210 x 297 mm``. Returns ``None`` when nothing size-like is present, and
    raises ``SizeError`` when something size-like is present but unmappable —
    so "B5" becomes a reported gap rather than a silent no-op.
    """
    if not text:
        return None

    # A code or trade name is unambiguous; check those first.
    for match in _SIZE_PATTERN.finditer(text):
        if match.group(1):
            return match.group(1).upper()
        if match.group(2):
            # The catalog's own stored codes: a structured caller sends these.
            return match.group(2).upper()
        if match.group(3):
            return SIZE_ALIASES[match.group(3).lower()]

    # Then dimensions.
    for match in _SIZE_PATTERN.finditer(text):
        first, second, unit = match.group(4), match.group(5), match.group(6)
        if first is None or second is None:
            continue
        a = _number(first)
        b = _number(second)
        if unit and unit.lower() == "mm":
            key = (int(a), int(b))
            if key in SIZE_BY_MM:
                return SIZE_BY_MM[key]
            raise SizeError(f"{a} x {b} mm matches no known size")
        # Inches (or unspecified, which in this catalog means inches).
        try:
            return parse_size(f"{first} {MULT_SIGN} {second} in")[0]
        except SizeError as exc:
            raise SizeError(str(exc)) from exc

    # A paper-size code this catalog does not stock.
    m = _UNSTOCKED_SIZE_CODES.search(text)
    if m:
        raise SizeError(
            f"{m.group(1).upper()} is a paper size this catalog does not stock"
        )

    return None


def _number(token: str) -> Decimal:
    token = token.strip()
    if token.endswith(HALF):
        head = token[: -len(HALF)]
        return (Decimal(head) if head else Decimal(0)) + Decimal("0.5")
    return Decimal(token)


# ---------------------------------------------------------------------------
# Weight
# ---------------------------------------------------------------------------

#: "100 gsm", "100 g/m²", "100 grams per square metre".
_WEIGHT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:gsm|g/m\u00b2|g/m2|g\s*/\s*m\u00b2"
    r"|grams?\s+per\s+square\s+met(?:re|er))",
    re.IGNORECASE,
)

#: "20 lb", "24 lb bond", "20-pound".
_POUND_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds|-pound)\b", re.IGNORECASE
)

#: Grammages that actually exist in the catalog.
#:
#: Used to read a bare number as a weight ("A5 gloss 130") without guessing: a
#: number is only treated as a grammage if it is one the catalog stocks. That
#: makes the reading verifiable rather than plausible, and it cannot invent a
#: weight. `test_aliases.py` asserts this set matches the loaded catalog, so it
#: cannot drift from the data.
CATALOG_GRAMMAGES: frozenset[int] = frozenset(
    {70, 75, 80, 90, 100, 130, 160, 170, 180, 200, 230, 250}
)

#: Unit words that make a nearby number a quantity, never a grammage.
_QUANTITY_UNITS = (
    "ream", "reams", "pack", "packs", "sheet", "sheets", "box", "boxes",
    "roll", "rolls", "unit", "units", "piece", "pieces", "pcs",
)

#: A bare number standing alone as a possible grammage.
_BARE_NUMBER = re.compile(r"(?<![\w.])(\d{2,3})(?![\w.])")

#: Context that makes a nearby number a price rather than a grammage.
#:
#: *"under 250 a pack"* is a budget. 250 is also a grammage the catalog stocks,
#: so without this guard the budget's "under" would be read as a weight ceiling
#: and the search would filter on 250 gsm — returning the wrong items for the
#: brief's own example.
_MONEY_CONTEXT = re.compile(
    r"(?:฿|\bthb\b|\bbaht\b|\bbudget\b|\bprice\b|\bcost\b|\bspend\b|\bunder\b"
    r"|\bless than\b|\bmax(?:imum)?\b|\bat most\b|\bper\s+(?:pack|ream|unit|box|piece)\b"
    r"|\ba\s+(?:pack|ream|unit|box|piece)\b|\beach\b)",
    re.IGNORECASE,
)

#: The brief's agreed table.
POUND_TO_GSM: dict[int, int] = {20: 75, 24: 90, 28: 105, 32: 120}


def resolve_weight(text: str) -> tuple[int | None, int | None, int | None]:
    """Return ``(exact_gsm, min_gsm, max_gsm)`` from a request.

    "100 gsm" is exact; "at least 100 gsm" is a floor; "under 130 gsm" is a
    ceiling; "around 100 gsm" is treated as exact because the catalog has no
    tolerance concept and silently widening a range would return items the
    customer did not ask for.
    """
    if not text:
        return None, None, None

    lower = text.lower()

    m = _POUND_PATTERN.search(text)
    if m:
        pounds = int(Decimal(m.group(1)))
        if pounds in POUND_TO_GSM:
            gsm = POUND_TO_GSM[pounds]
            bound = _weight_bound(text, m)
            if bound == "min":
                return None, gsm, None
            if bound == "max":
                return None, None, gsm
            return gsm, None, None
        # Unlisted pound value: no conversion is defensible.
        return None, None, None

    m = _WEIGHT_PATTERN.search(text)
    if not m:
        return _resolve_bare_grammage(text)

    gsm = int(Decimal(m.group(1)))

    bound = _weight_bound(text, m)
    if bound == "min":
        return None, gsm, None
    if bound == "max":
        return None, None, gsm
    return gsm, None, None


#: Words that turn a stated weight into a floor or a ceiling when they appear
#: *before* the number.
_MIN_WORDS = r"(?:at least|minimum|min\.?|over|above|heavier than|>=)"
_MAX_WORDS = r"(?:at most|maximum|max\.?|under|below|lighter than|<=)"

#: Phrases that make a weight a floor or ceiling when they appear *after* it.
#: These are deliberately a different, narrower set than the "before" words: a
#: trailing "and above" is part of the weight's own phrase, but a trailing
#: "under 250 a pack" is the next requirement and must not be read as a
#: qualifier on this one.
_MIN_AFTER = r"(?:and above|or heavier|or more|\+)"
_MAX_AFTER = r"(?:and below|or lighter|or less)"


def _weight_bound(text: str, match: re.Match) -> str | None:
    """Is this weight a floor, a ceiling, or exact?

    The qualifier is looked for in **the weight's own phrase**, not anywhere in
    the request. Scanning the whole string is how *"A4 80gsm under 250 a pack"*
    became "80 gsm or lighter": the budget's "under" was read as a weight
    ceiling, and the search then quietly answered a different question.

    Two narrow windows, because "before" and "after" are not symmetrical:

    * **before** accepts the full vocabulary — "under 130 gsm" and "at least
      100 gsm" both read naturally;
    * **after** accepts only the forms that bind to the number itself — "130 gsm
      and above", "100 gsm or heavier". A bare "under" after a weight is a new
      requirement, not a modifier of this one.
    """
    before = text[max(0, match.start() - 24):match.start()]
    # Stop at the clause boundary: a qualifier in a previous clause is not this
    # weight's qualifier.
    before = re.split(r"[,;.]|\band\b|\bwith\b|\bfor\b", before)[-1]
    after = text[match.end():match.end() + 20]

    if re.search(_MIN_WORDS, before, re.IGNORECASE) or re.match(
        r"\s*" + _MIN_AFTER, after, re.IGNORECASE
    ):
        return "min"
    if re.search(_MAX_WORDS, before, re.IGNORECASE) or re.match(
        r"\s*" + _MAX_AFTER, after, re.IGNORECASE
    ):
        return "max"
    return None


def _resolve_bare_grammage(text: str) -> tuple[int | None, int | None, int | None]:
    """Read a bare number as a grammage, but only when that reading is safe.

    *"A5 gloss 130"* means 130 gsm to anyone in the trade. But a bare number is
    also how quantities are written — "A4 paper 20" — so reading every number as
    a weight would turn a quantity request into a weight filter and return
    nothing.

    Two guards make the reading safe rather than lucky:

    * the number must be a grammage the catalog actually stocks, so the
      interpretation is checkable against data rather than guessed; and
    * the number must not be adjacent to a quantity unit ("20 reams").

    A number that fails either guard is not treated as a weight at all. That
    keeps the failure mode honest: an unrecognised number is ignored, not
    silently turned into the wrong constraint.
    """
    lower = text.lower()

    for match in _BARE_NUMBER.finditer(text):
        value = int(match.group(1))
        if value not in CATALOG_GRAMMAGES:
            continue

        # Is a quantity unit attached to this number?
        after = lower[match.end():match.end() + 12]
        before = lower[max(0, match.start() - 12):match.start()]
        if any(re.match(rf"\s*{unit}\b", after) for unit in _QUANTITY_UNITS):
            continue
        if any(re.search(rf"\b{unit}\s*$", before) for unit in _QUANTITY_UNITS):
            continue

        # Is it a price? "under 250 a pack" is a budget, not a 250 gsm ceiling.
        # The word window is narrow on purpose: it must be the *same* clause, not
        # any money word anywhere in the request.
        if _MONEY_CONTEXT.search(text[max(0, match.start() - 20):match.end() + 12]):
            continue

        bound = _weight_bound(text, match)
        if bound == "min":
            return None, value, None
        if bound == "max":
            return None, None, value
        return value, None, None

    return None, None, None


# ---------------------------------------------------------------------------
# Printing notation
# ---------------------------------------------------------------------------

#: Trade notation for sides x colours, as the site itself explains:
#: "single-sided full colour is often written 4/0, double-sided full colour 4/4".
PRINTING_NOTATION: dict[str, tuple[str, str]] = {
    "4/0": ("single", "Full colour (CMYK)"),
    "1/0": ("single", "Black and white"),
    "4/4": ("double", "Full colour (CMYK)"),
    "1/1": ("double", "Black and white"),
}

_NOTATION_PATTERN = re.compile(r"\b([14])/([014])\b")


def resolve_printing(text: str) -> tuple[str | None, str | None]:
    """Return ``(sides, colour_mode)`` from a request.

    Both plain words and trade notation resolve to the same pair, which is what
    makes "double sided full colour" and "4/4" select the same items.
    """
    if not text:
        return None, None

    lower = text.lower()
    sides: str | None = None
    colour_mode: str | None = None

    m = _NOTATION_PATTERN.search(text)
    if m:
        key = f"{m.group(1)}/{m.group(2)}"
        if key in PRINTING_NOTATION:
            sides, colour_mode = PRINTING_NOTATION[key]

    if sides is None:
        if re.search(r"\b(double[- ]?sided|two[- ]sided|both sides|duplex)\b", lower):
            sides = "double"
        elif re.search(r"\b(single[- ]?sided|one[- ]sided|one side|simplex)\b", lower):
            sides = "single"

    if colour_mode is None:
        # A bare "colour" is ambiguous, not automatically CMYK. The two senses
        # (print colour vs paper shade) select disjoint item sets, and
        # `resolve_colour` already decides which was meant — including setting
        # `ambiguous` for "colour paper". Claiming CMYK here would override that
        # and silently turn "colour paper A4" into a CMYK flyer search.
        #
        # Only an explicit print phrase is unambiguous.
        if re.search(r"\b(full[- ]?colou?r|cmyk)\b", lower):
            colour_mode = "Full colour (CMYK)"
        elif re.search(r"\b(black and white|b\s*&\s*w|mono|greyscale|grayscale)\b", lower):
            colour_mode = "Black and white"

    return sides, colour_mode


# ---------------------------------------------------------------------------
# Finish
# ---------------------------------------------------------------------------

#: Finishes that exist in the catalog, with their everyday synonyms.
FINISH_ALIASES: dict[str, str] = {
    "gloss": "Gloss",
    "glossy": "Gloss",
    "high gloss": "Gloss",
    "high-gloss": "Gloss",
    "matte": "Matte",
    "matt": "Matte",
    "uncoated": "Uncoated",
    "plain": "Uncoated",
    "laid": "Laid",
    "smooth": "Smooth",
}

_FINISH_PATTERN = re.compile(
    r"\b(high[- ]gloss|glossy|gloss|matt?e?|uncoated|plain|laid|smooth)\b",
    re.IGNORECASE,
)


def resolve_finish(text: str) -> str | None:
    if not text:
        return None
    m = _FINISH_PATTERN.search(text)
    if not m:
        return None
    return FINISH_ALIASES.get(m.group(1).lower())


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

#: Paper shades the catalog actually stocks.
PAPER_SHADES = (
    "white", "bright white", "cream", "ivory", "black",
    "pastel blue", "pastel green", "pastel pink", "pastel yellow",
    "red", "bright red", "assorted brights", "assorted pastels",
)

#: Words that make "colour" refer to the print mode rather than the paper.
PRINT_NOUNS = (
    "print", "printing", "printed", "flyer", "flyers", "ink", "cmyk",
    "colour print", "color print",
)

#: Words that make "colour" refer to the paper itself.
PAPER_NOUNS = (
    "paper", "sheet", "sheets", "stock", "shade", "card", "ream", "pad",
)

_SHADE_PATTERN = re.compile(
    r"\b(pastel blue|pastel green|pastel pink|pastel yellow|bright white|"
    r"bright red|assorted brights|assorted pastels|white|cream|ivory|black|red)\b",
    re.IGNORECASE,
)

#: Phrases that can only mean print colour, never a paper shade.
_EXPLICIT_PRINT_MODE = re.compile(r"\b(full[- ]?colou?r|cmyk)\b", re.IGNORECASE)


def resolve_colour(text: str) -> tuple[str | None, str | None, bool]:
    """Return ``(paper_shade, print_mode, ambiguous)``.

    ``ambiguous`` is set when the word "colour" appears with no noun that says
    which sense was meant. The assistant asks rather than choosing, because the
    two senses select completely different item sets.
    """
    if not text:
        return None, None, False

    lower = text.lower()

    # "black and white" is a print mode, not a request for black paper. It must
    # be tested before the shade pattern, which would otherwise match the word
    # "black" and send a black-and-white flyer request looking for black stock.
    if re.search(r"\b(black and white|b\s*&\s*w|mono|greyscale|grayscale)\b", lower):
        return None, "Black and white", False

    # An explicit shade name is never ambiguous.
    m = _SHADE_PATTERN.search(text)
    if m:
        return m.group(1).lower(), None, False

    mentions_colour = bool(re.search(r"\bcolou?r\b", lower))
    mentions_print = any(noun in lower for noun in PRINT_NOUNS)
    mentions_paper = any(noun in lower for noun in PAPER_NOUNS)

    # An explicit print-mode phrase settles it before ambiguity is considered.
    # "full colour", "CMYK" and "black and white" are only ever said about
    # printing — nobody describes a paper shade as "full colour". Treating
    # "two-sided full colour" as ambiguous made the assistant ask a question the
    # customer had already answered, and the 4/4 notation for the same request
    # was read correctly, so the two spellings of one requirement disagreed.
    if _EXPLICIT_PRINT_MODE.search(lower):
        return None, "Full colour (CMYK)", False
    if re.search(r"\b(black and white|b\s*&\s*w|mono|greyscale|grayscale)\b", lower):
        return None, "Black and white", False

    if mentions_colour:
        if mentions_print and not mentions_paper:
            return None, "Full colour (CMYK)", False
        if mentions_paper and not mentions_print:
            # "white paper" was already caught above; a bare "colour paper" is
            # a shade request with an unnamed shade, which the assistant asks
            # about.
            return None, None, True
        return None, None, True

    if mentions_print and re.search(r"\b(full[- ]?colou?r|cmyk)\b", lower):
        return None, "Full colour (CMYK)", False

    return None, None, False


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

CATEGORY_ALIASES: dict[str, str] = {
    "copy paper": "Copy paper",
    "copier paper": "Copy paper",
    "office paper": "Copy paper",
    "printer paper": "Copy paper",
    "laser paper": "Copy paper",
    "inkjet paper": "Copy paper",
    "coloured paper": "Coloured paper",
    "colored paper": "Coloured paper",
    "colour paper": "Coloured paper",
    "color paper": "Coloured paper",
    "card": "Card and photo paper",
    "cardstock": "Card and photo paper",
    "card stock": "Card and photo paper",
    "photo paper": "Card and photo paper",
    "photo": "Card and photo paper",
    "flyer": "Flyer printing",
    "flyers": "Flyer printing",
    "flyer printing": "Flyer printing",
    "printing": "Flyer printing",
    "leaflet": "Flyer printing",
    "leaflets": "Flyer printing",
}


def resolve_category(text: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    # Longest alias first, so "flyer printing" beats "printing".
    for alias in sorted(CATEGORY_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", lower):
            return CATEGORY_ALIASES[alias]
    return None
