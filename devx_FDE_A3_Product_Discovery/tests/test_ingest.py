"""Ingest orchestration tests: discovery, volume-pricing detection, cross-checks.

These exercise the pure helpers in ``ingest.py`` against fixture HTML. The full
crawl is exercised end-to-end by ``./run.sh ingest`` against the served site,
which is not something a unit test should depend on.
"""

from __future__ import annotations

import os

import pytest

from paperlane.ingest import (
    _advertised_skus,
    _card_stock_claim,
    _card_text,
    _to_row,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


class TestVolumePricingDetection:
    def test_page_with_loader_placeholder_advertises_tiers(self):
        # pl-cp-a4-80-eco has data-sku and no "no volume pricing" sentence.
        assert _advertised_skus(load("pl-cp-a4-80-eco.html")) == {"PL-CP-A4-80-ECO"}

    def test_explicit_no_volume_pricing_sentence(self):
        html = (
            "<div class='pricebox'><div class='big'>฿168.00</div>"
            "<p class='muted'>No volume pricing for this item.</p></div>"
        )
        assert _advertised_skus(html) == set()

    def test_sale_marker_is_not_counted_as_advertising_tiers(self):
        # The sale row carries data-sku with data-sale='1' but has no document.
        skus = _advertised_skus(load("flyers-ltr-gloss.html"))
        assert "PL-PR-LTR-GL-170-40" not in skus
        assert len(skus) == 5           # 6 rows minus the sale row

    def test_all_rows_on_a_variant_page(self):
        skus = _advertised_skus(load("flyers-ltr-gloss.html"))
        assert skus == {
            "PL-PR-LTR-GL-100-40", "PL-PR-LTR-GL-100-44",
            "PL-PR-LTR-GL-130-40", "PL-PR-LTR-GL-130-44",
            "PL-PR-LTR-GL-170-44",
        }


class TestCardStockClaim:
    @pytest.mark.parametrize(
        "card_text,expected",
        [
            ("pack of 250 sheets · out of stock", "out_of_stock"),
            ("pack of 250 sheets · discontinued", "discontinued"),
            ("ream of 500 sheets", None),
            ("per 100 printed sheets · 8 options", None),
            ("", None),
        ],
    )
    def test_claims(self, card_text, expected):
        assert _card_stock_claim(card_text) == expected

    def test_the_real_card_that_says_out_of_stock(self):
        # category/coloured-paper/index.html, card for PL-CL-A4-100-IVY.
        assert _card_stock_claim("pack of 250 sheets · out of stock") == "out_of_stock"

    def test_card_text_uses_the_muted_line(self):
        from selectolax.lexbor import LexborHTMLParser

        html = (
            "<div class='card'><h3><a href='../../product/x.html'>X</a></h3>"
            "<div class='price'>฿168.00</div>"
            "<div class='muted'>pack of 250 sheets &middot; out of stock</div></div>"
        )
        card = LexborHTMLParser(html).css_first("div.card")
        text = _card_text(card)
        assert "out of stock" in text
        assert _card_stock_claim(text) == "out_of_stock"


class TestRowConversion:
    def test_money_becomes_integer_satang(self):
        from datetime import datetime, timezone

        from paperlane.extract import ExtractedProduct

        product = ExtractedProduct(
            sku="PL-T-1", name="T", list_price=__import__("decimal").Decimal("129.00"),
            source_url="u", source_shape="table",
        )
        row = _to_row(product, "u", datetime.now(timezone.utc), has_volume_pricing=False)
        assert row["list_price_satang"] == 12900
        assert isinstance(row["list_price_satang"], int)
        assert row["sale_price_satang"] is None

    def test_sale_price_converted(self):
        from datetime import datetime, timezone
        from decimal import Decimal

        from paperlane.extract import ExtractedProduct

        product = ExtractedProduct(
            sku="PL-T-2", name="T", list_price=Decimal("299.00"),
            sale_price=Decimal("259.00"), source_url="u", source_shape="variant-table",
        )
        row = _to_row(product, "u", datetime.now(timezone.utc), has_volume_pricing=False)
        assert row["list_price_satang"] == 29900
        assert row["sale_price_satang"] == 25900

    def test_provenance_carried(self):
        from datetime import datetime, timezone
        from decimal import Decimal

        from paperlane.extract import ExtractedProduct

        when = datetime(2026, 10, 1, tzinfo=timezone.utc)
        product = ExtractedProduct(
            sku="PL-T-3", name="T", list_price=Decimal("100.00"),
            source_url="http://x/p.html", source_shape="dl",
        )
        row = _to_row(product, "http://x/p.html", when, has_volume_pricing=True)
        assert row["source_url"] == "http://x/p.html"
        assert row["source_shape"] == "dl"
        assert row["crawled_at"] == when
        assert row["has_volume_pricing"] is True
