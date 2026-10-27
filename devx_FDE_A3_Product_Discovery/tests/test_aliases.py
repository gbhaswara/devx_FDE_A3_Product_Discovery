"""Alias tests: everyday and trade phrasings resolve to catalog vocabulary.

The requirement is paired: two different phrasings of one requirement must
select the same items. So most tests here assert equality between two
resolutions rather than a hard-coded value.
"""

from __future__ import annotations

import pytest

from paperlane.aliases import (
    POUND_TO_GSM,
    bare_grammage,
    resolve_category,
    resolve_colour,
    resolve_finish,
    resolve_printing,
    resolve_size,
    resolve_weight,
)
from paperlane.normalize import SizeError


class TestSizeAliases:
    @pytest.mark.parametrize(
        "text",
        [
            "A4", "a4", "A4 paper",
            "210 x 297 mm",
            "210 by 297 mm",
        ],
    )
    def test_a4_phrasings(self, text):
        assert resolve_size(text) == "A4"

    @pytest.mark.parametrize(
        "text",
        [
            "letter", "Letter", "US Letter", "letter size",
            "8.5 x 11", "8.5x11", "8.5 by 11", "8.5 x 11 in",
            "8½ x 11", "8½ x 11 in", "8½ by 11",
        ],
    )
    def test_letter_phrasings_all_resolve_to_ltr(self, text):
        assert resolve_size(text) == "LTR"

    def test_decimal_and_vulgar_fraction_agree(self):
        assert resolve_size("8.5 x 11 in") == resolve_size("8½ x 11 in")

    def test_legal(self):
        assert resolve_size("legal") == "LGL"
        assert resolve_size("8.5 x 14 in") == "LGL"

    def test_unicode_multiplication_sign(self):
        assert resolve_size("8.5 × 11 in") == "LTR"

    def test_a5_and_a3(self):
        assert resolve_size("A5") == "A5"
        assert resolve_size("A3") == "A3"

    def test_no_size_returns_none(self):
        assert resolve_size("some paper please") is None

    def test_unmappable_size_raises(self):
        # B5 is a real paper size the catalog does not stock. Silently ignoring
        # it would return A4 items as though they matched.
        with pytest.raises(SizeError):
            resolve_size("B5")

    def test_unmappable_mm_dimensions_raise(self):
        with pytest.raises(SizeError):
            resolve_size("176 x 250 mm")


class TestWeightAliases:
    def test_plain_grammage(self):
        assert resolve_weight("100 gsm") == (100, None, None)

    def test_grams_per_square_metre(self):
        assert resolve_weight("90 g/m²") == (90, None, None)

    def test_grams_per_square_metre_ascii(self):
        assert resolve_weight("90 g/m2") == (90, None, None)

    def test_spelled_out(self):
        assert resolve_weight("100 grams per square metre") == (100, None, None)

    def test_pounds_converted_from_table(self):
        assert resolve_weight("20 lb") == (75, None, None)
        assert resolve_weight("24 lb bond") == (90, None, None)

    def test_all_four_table_values(self):
        for pounds, gsm in POUND_TO_GSM.items():
            assert resolve_weight(f"{pounds} lb") == (gsm, None, None)

    def test_unlisted_pounds_yield_nothing(self):
        # No defensible conversion exists, so the requirement is dropped rather
        # than invented.
        assert resolve_weight("26 lb") == (None, None, None)

    def test_at_least_is_a_floor(self):
        assert resolve_weight("at least 100 gsm") == (None, 100, None)

    def test_under_is_a_ceiling(self):
        assert resolve_weight("under 130 gsm") == (None, None, 130)

    def test_no_weight_returns_nothing(self):
        assert resolve_weight("nice paper") == (None, None, None)


class TestBareGrammage:
    """Did the weight come from a bare number, or from a unit?

    ``resolve_weight`` deliberately collapses both into one value. The merge
    layer cannot: in a refinement a bare number is the quantity, while "100 gsm"
    is a weight correction. This predicate is the distinction, kept next to the
    parser that makes it so the two cannot drift.
    """

    def test_a_bare_catalog_grammage_is_bare(self):
        assert bare_grammage("A5 gloss 130") == 130
        assert bare_grammage("make it 100") == 100
        assert bare_grammage("change it to 160") == 160

    def test_a_number_the_catalog_does_not_stock_is_not_a_grammage(self):
        # 60 is a plausible quantity and not a stocked weight, which is why the
        # reported sequence only went wrong at the turn that said 100.
        assert bare_grammage("change it to 60") is None
        assert bare_grammage("change it to 50") is None

    def test_a_unit_bearing_weight_is_not_bare(self):
        assert resolve_weight("130 gsm") == (130, None, None)
        assert bare_grammage("130 gsm") is None
        assert bare_grammage("100 g/m2") is None

    def test_a_pound_weight_is_not_bare(self):
        assert bare_grammage("20 lb") is None

    def test_a_bounded_bare_number_is_not_bare(self):
        # A bound states a range, so it is a weight requirement and not a
        # restated quantity.
        assert bare_grammage("at least 100") is None
        assert bare_grammage("under 130") is None

    def test_a_quantity_is_not_a_grammage(self):
        assert bare_grammage("20 reams") is None
        # 50 is not a catalog grammage, so the weight parser never claims it.
        assert bare_grammage("make it 50") is None

    def test_a_budget_is_not_a_grammage(self):
        assert bare_grammage("under 250 a pack") is None
        assert bare_grammage("") is None


class TestPrintingNotation:
    def test_trade_notation_matches_plain_words(self):
        # The site's own gloss: "single-sided full colour is often written 4/0,
        # double-sided full colour 4/4".
        assert resolve_printing("4/4") == resolve_printing(
            "double-sided full colour"
        )

    def test_4_0_is_single_sided_colour(self):
        sides, mode = resolve_printing("4/0")
        assert sides == "single"
        assert "colour" in mode.lower()

    def test_4_4_is_double_sided_colour(self):
        sides, mode = resolve_printing("4/4")
        assert sides == "double"
        assert "colour" in mode.lower()

    @pytest.mark.parametrize(
        "text", ["double sided", "double-sided", "two-sided", "both sides", "duplex"]
    )
    def test_double_side_phrasings(self, text):
        assert resolve_printing(text)[0] == "double"

    @pytest.mark.parametrize(
        "text", ["single sided", "single-sided", "one side", "simplex"]
    )
    def test_single_side_phrasings(self, text):
        assert resolve_printing(text)[0] == "single"

    def test_black_and_white(self):
        sides, mode = resolve_printing("black and white single sided")
        assert sides == "single"
        assert mode == "Black and white"

    def test_bw_abbreviation(self):
        assert resolve_printing("b&w")[1] == "Black and white"

    def test_nothing_returns_none(self):
        assert resolve_printing("plain paper") == (None, None)


class TestFinishAliases:
    @pytest.mark.parametrize("text", ["gloss", "glossy", "high gloss", "high-gloss"])
    def test_gloss(self, text):
        assert resolve_finish(text) == "Gloss"

    @pytest.mark.parametrize("text", ["matte", "matt"])
    def test_matte(self, text):
        assert resolve_finish(text) == "Matte"

    @pytest.mark.parametrize("text", ["uncoated", "plain"])
    def test_uncoated(self, text):
        assert resolve_finish(text) == "Uncoated"

    def test_nothing(self):
        assert resolve_finish("nice paper") is None


class TestColourDisambiguation:
    """4.4 — the same adjective selects different attributes by context."""

    def test_colour_with_plain_paper_is_a_shade(self):
        shade, mode, ambiguous = resolve_colour("white paper")
        assert shade == "white"
        assert mode is None
        assert ambiguous is False

    def test_colour_with_printed_goods_is_a_print_mode(self):
        shade, mode, ambiguous = resolve_colour("full colour printing")
        assert mode == "Full colour (CMYK)"
        assert shade is None
        assert ambiguous is False

    def test_bare_colour_is_ambiguous(self):
        # Nothing disambiguates it, so the assistant must ask.
        shade, mode, ambiguous = resolve_colour("colour please")
        assert ambiguous is True
        assert shade is None
        assert mode is None

    def test_named_shade_is_never_ambiguous(self):
        for text in ("pastel blue", "ivory", "cream", "bright red"):
            shade, _, ambiguous = resolve_colour(text)
            assert shade is not None
            assert ambiguous is False

    def test_flyer_plus_colour_is_print_mode(self):
        _, mode, ambiguous = resolve_colour("colour flyers")
        assert mode == "Full colour (CMYK)"
        assert ambiguous is False

    def test_paper_noun_does_not_leak_into_print_mode(self):
        shade, mode, _ = resolve_colour("cream paper sheets")
        assert shade == "cream"
        assert mode is None


class TestCategoryAliases:
    @pytest.mark.parametrize(
        "text", ["copy paper", "copier paper", "office paper", "printer paper"]
    )
    def test_copy_paper(self, text):
        assert resolve_category(text) == "Copy paper"

    @pytest.mark.parametrize(
        "text", ["coloured paper", "colored paper", "colour paper"]
    )
    def test_coloured_paper(self, text):
        assert resolve_category(text) == "Coloured paper"

    @pytest.mark.parametrize("text", ["flyer", "flyers", "leaflets", "printing"])
    def test_flyers(self, text):
        assert resolve_category(text) == "Flyer printing"

    def test_longest_alias_wins(self):
        # "flyer printing" must beat the shorter "printing".
        assert resolve_category("flyer printing") == "Flyer printing"

    def test_card(self):
        assert resolve_category("cardstock") == "Card and photo paper"
        assert resolve_category("photo paper") == "Card and photo paper"

    def test_nothing(self):
        assert resolve_category("something else") is None


# ---------------------------------------------------------------------------
# Regressions found while building the evaluation set
# ---------------------------------------------------------------------------


class TestWeightQualifierScope:
    """A qualifier belongs to its own phrase, not to the whole request.

    Found while writing the eval set. *"A4 80gsm under 250 a pack"* was read as
    "80 gsm or lighter", because the budget's "under" was picked up as a weight
    ceiling by a whole-string search. The search then answered a different
    question from the one asked, and returned eleven items instead of the five
    that are actually 80 gsm.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "A4 80gsm under 250 a pack",
            "A4 80 gsm under 250 a pack",
            "80gsm paper under 250 a pack",
            "A4 80gsm, under 250 a pack",
            "80gsm under 250 a pack, 20 packs",
        ],
    )
    def test_a_budget_does_not_become_a_weight_ceiling(self, text):
        assert resolve_weight(text) == (80, None, None)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("under 130 gsm", (None, None, 130)),
            ("below 130 gsm", (None, None, 130)),
            ("at most 130 gsm", (None, None, 130)),
            ("at least 100 gsm", (None, 100, None)),
            ("over 100 gsm", (None, 100, None)),
            ("130 gsm and above", (None, 130, None)),
            ("100 gsm or heavier", (None, 100, None)),
            ("100 gsm or lighter", (None, None, 100)),
        ],
    )
    def test_a_real_qualifier_still_binds(self, text, expected):
        # The fix must not have broken the qualifiers it was protecting.
        assert resolve_weight(text) == expected

    def test_an_exact_weight_stays_exact(self):
        assert resolve_weight("A4 80gsm") == (80, None, None)

    def test_a_bare_budget_is_not_a_weight_at_all(self):
        assert resolve_weight("letter-size, under 250 a pack") == (None, None, None)


class TestExplicitPrintMode:
    """An explicit print phrase settles the colour sense by itself.

    Found while writing the eval set. "two-sided full colour A5 130gsm gloss"
    was treated as ambiguous and the assistant asked "paper colour or print
    colour?" — a question the words had already answered. The 4/4 notation for
    the same requirement was read correctly, so two spellings of one request
    disagreed.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "two-sided full colour A5 130gsm gloss",
            "double sided full colour A5",
            "full colour flyers",
            "full-colour flyers",
            "CMYK both sides A5 gloss 130",
        ],
    )
    def test_an_explicit_print_phrase_is_not_ambiguous(self, text):
        _, mode, ambiguous = resolve_colour(text)
        assert mode == "Full colour (CMYK)"
        assert ambiguous is False

    def test_black_and_white_is_a_print_mode_not_black_paper(self):
        # The shade pattern would otherwise match the word "black" and send a
        # black-and-white flyer request looking for black stock.
        shade, mode, ambiguous = resolve_colour("black and white flyers")
        assert shade is None
        assert mode == "Black and white"
        assert ambiguous is False

    def test_a_bare_colour_paper_is_still_ambiguous(self):
        # The genuine ambiguity must survive: "colour paper" names a paper, so
        # which sense was meant is still unknown.
        assert resolve_colour("colour paper A4") == (None, None, True)
        assert resolve_colour("I need colour") == (None, None, True)
