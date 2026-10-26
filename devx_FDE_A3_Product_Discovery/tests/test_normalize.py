"""Weight and size normalisation tests.

Every value here was taken from the real site, not invented. The four weight
forms and the three size spellings are the ones the catalog actually contains.
"""

from __future__ import annotations

import pytest

from paperlane.normalize import (
    HALF,
    MULT_SIGN,
    POUND_TO_GSM,
    SizeError,
    WeightError,
    parse_size,
    parse_weight,
    pounds_to_gsm,
)


class TestWeightForms:
    """All four published forms must normalise to grammage."""

    def test_form_1_plain_grammage(self):
        w = parse_weight("80 gsm")
        assert w.gsm == 80
        assert w.form == "gsm"

    def test_form_2_grams_per_square_metre_superscript(self):
        # The single prose page that writes 90g/m² (U+00B2).
        w = parse_weight("90g/m\u00b2")
        assert w.gsm == 90
        assert w.form == "g_per_m2"

    def test_form_2_grams_per_square_metre_ascii(self):
        w = parse_weight("90 g/m2")
        assert w.gsm == 90
        assert w.form == "g_per_m2"

    def test_form_3_pounds_with_grammage(self):
        # "20 lb bond (75 gsm)" — pl-cp-ltr-20.html
        w = parse_weight("20 lb bond (75 gsm)")
        assert w.gsm == 75
        assert w.form == "lb_with_gsm"

    def test_form_3_second_instance(self):
        # "24 lb (90 gsm)" — pl-cl-ltr-24-brt.html
        w = parse_weight("24 lb (90 gsm)")
        assert w.gsm == 90
        assert w.form == "lb_with_gsm"

    def test_form_4_pounds_alone(self):
        # "20 lb bond" — pl-cp-lgl-20.html, no grammage stated
        w = parse_weight("20 lb bond")
        assert w.gsm == 75
        assert w.form == "lb_only"

    def test_form_4_pounds_alone_24(self):
        # "24 lb" — pl-cp-ltr-24.html
        w = parse_weight("24 lb")
        assert w.gsm == 90
        assert w.form == "lb_only"

    def test_raw_is_preserved(self):
        # Kept so a conversion can be defended in the interview.
        w = parse_weight("20 lb bond (75 gsm)")
        assert w.raw == "20 lb bond (75 gsm)"


class TestPoundTable:
    """The brief's table is the agreed specification and must be honoured."""

    @pytest.mark.parametrize(
        "pounds,gsm",
        [(20, 75), (24, 90), (28, 105), (32, 120)],
    )
    def test_all_four_conversions(self, pounds, gsm):
        assert pounds_to_gsm(pounds) == gsm

    def test_table_matches_brief(self):
        assert POUND_TO_GSM == {20: 75, 24: 90, 28: 105, 32: 120}

    def test_unlisted_pounds_raise(self):
        # 26 lb is not in the table; guessing would put an unsupported number
        # in a quote.
        with pytest.raises(WeightError, match="no entry"):
            pounds_to_gsm(26)

    def test_non_integer_pounds_raise(self):
        with pytest.raises(WeightError, match="non-integer"):
            pounds_to_gsm("20.5")

    def test_28_and_32_parse_from_pounds_alone(self):
        # Implemented from the table even though v1 has no such product.
        assert parse_weight("28 lb").gsm == 105
        assert parse_weight("32 lb").gsm == 120


class TestSourceCrossCheck:
    """Two pages state both forms; the table must agree with the source."""

    def test_agreement_is_accepted(self):
        assert parse_weight("20 lb bond (75 gsm)").gsm == 75
        assert parse_weight("24 lb (90 gsm)").gsm == 90

    def test_disagreement_raises(self):
        # If a future site says 20 lb (95 gsm) the conflict must surface, not
        # be silently resolved in either direction.
        with pytest.raises(WeightError, match="disagrees"):
            parse_weight("20 lb (95 gsm)")


class TestWeightFailures:
    @pytest.mark.parametrize("bad", ["", "   ", None, "heavy", "unknown"])
    def test_unparseable_raises(self, bad):
        with pytest.raises(WeightError):
            parse_weight(bad)


class TestSizeNormalisation:
    """Three spellings of one size must produce one code."""

    def test_explicit_code(self):
        assert parse_size("A4") == ("A4", 210, 297)

    def test_code_with_dimensions(self):
        # table shape: "A4 (210 × 297 mm)"
        assert parse_size("A4 (210 " + MULT_SIGN + " 297 mm)") == ("A4", 210, 297)

    def test_decimal_inches(self):
        # 9 occurrences across 7 pages
        assert parse_size("8.5 " + MULT_SIGN + " 11 in") == ("LTR", 216, 279)

    def test_vulgar_fraction_inches(self):
        # 2 occurrences, U+00BD — the one the obvious filter misses
        assert parse_size("8" + HALF + " " + MULT_SIGN + " 11 in") == ("LTR", 216, 279)

    def test_both_spellings_agree(self):
        assert parse_size("8.5 " + MULT_SIGN + " 11 in") == parse_size(
            "8" + HALF + " " + MULT_SIGN + " 11 in"
        )

    def test_letter_alias(self):
        assert parse_size("letter")[0] == "LTR"

    def test_legal_dimensions(self):
        assert parse_size("US Legal (8.5 " + MULT_SIGN + " 14 in)") == ("LGL", 216, 356)

    def test_a5(self):
        assert parse_size("A5") == ("A5", 148, 210)

    def test_ascii_x_also_works(self):
        # Customers type 'x'; the site uses U+00D7. Both must land on one code.
        assert parse_size("8.5 x 11 in")[0] == "LTR"

    def test_unmappable_raises(self):
        # Must be reported, not stored as an unmatchable NULL.
        with pytest.raises(SizeError):
            parse_size("B5")

    def test_empty_raises(self):
        with pytest.raises(SizeError):
            parse_size("")


class TestUnicodeFacts:
    """Guard the exact code points, because they are the trap."""

    def test_multiplication_sign_is_u00d7(self):
        assert MULT_SIGN == "\u00d7"
        assert MULT_SIGN != "x"

    def test_half_is_u00bd(self):
        assert HALF == "\u00bd"

    def test_string_match_would_miss(self):
        # Demonstrates why normalisation is required rather than string search.
        raw = "8" + HALF + " " + MULT_SIGN + " 11 in"
        assert "8.5" not in raw           # the obvious filter misses it
        assert parse_size(raw)[0] == "LTR"  # normalisation does not
