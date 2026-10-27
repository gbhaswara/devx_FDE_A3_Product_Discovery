"""Ingest orchestration tests: discovery, volume-pricing detection, cross-checks.

These exercise the pure helpers in ``ingest.py`` against fixture HTML. The full
crawl is exercised end-to-end by ``./run.sh ingest`` against the served site,
which is not something a unit test should depend on.
"""

from __future__ import annotations

import os

import pytest

from conftest import needs_loopback

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


# ---------------------------------------------------------------------------
# Pre-swap gate (BUG.md A32)
# ---------------------------------------------------------------------------


class TestSwapGate:
    """A refresh that parses almost nothing must not replace the catalog.

    The rule is a count, so it is tested as a count. The crawl that produces the
    count is exercised once, against a loopback site, in :class:`TestCollapsedCrawl`.
    """

    def test_first_ingest_is_never_refused(self):
        from paperlane.ingest import _swap_refusal

        assert _swap_refusal(0, None, accept_shrink=False) is None
        assert _swap_refusal(72, None, accept_shrink=False) is None

    def test_zero_skus_is_refused(self):
        from paperlane.ingest import _swap_refusal

        reason = _swap_refusal(0, 72, accept_shrink=False)
        assert reason is not None
        assert "0 SKUs" in reason and "72" in reason

    def test_under_half_is_refused(self):
        from paperlane.ingest import _swap_refusal

        assert _swap_refusal(35, 72, accept_shrink=False) is not None

    def test_exactly_half_is_allowed(self):
        # A genuine catalog cut is possible; the gate catches a collapse, not a
        # shrink, so the boundary is inclusive.
        from paperlane.ingest import _swap_refusal

        assert _swap_refusal(36, 72, accept_shrink=False) is None

    def test_growth_is_allowed(self):
        from paperlane.ingest import _swap_refusal

        assert _swap_refusal(80, 72, accept_shrink=False) is None

    def test_the_flag_overrides(self):
        from paperlane.ingest import _swap_refusal

        assert _swap_refusal(0, 72, accept_shrink=True) is None


@needs_loopback
class TestCollapsedCrawl:
    """End to end: a site the parser cannot read leaves the serving catalog alone."""

    def row(self, sku: str, price_satang: int) -> dict:
        from datetime import datetime, timezone

        return {
            "sku": sku,
            "name": f"Product {sku}",
            "list_price_satang": price_satang,
            "stock_status": "in_stock",
            "source_url": f"http://x/product/{sku}.html",
            "source_shape": "table",
            "crawled_at": datetime.now(timezone.utc),
        }

    def serving_snapshot(self, tmp_path):
        from paperlane import catalog

        target = tmp_path / "catalog.duckdb"
        return catalog.build_snapshot(
            products=[self.row("PL-T-1", 12900), self.row("PL-T-2", 24500)],
            tiers=[],
            reviews=[],
            base_url="http://x/",
            pages_fetched=1,
            tier_docs_found=0,
            target=target,
        )

    def broken_site(self, tmp_path):
        """Three pages, none of them parseable: a valid crawl, zero SKUs."""
        root = tmp_path / "site"
        (root / "category" / "copy-paper").mkdir(parents=True)
        (root / "product").mkdir()
        (root / "index.html").write_text(
            '<a href="category/copy-paper/index.html">Copy paper</a>', encoding="utf-8"
        )
        (root / "category" / "copy-paper" / "index.html").write_text(
            '<a href="../../product/mystery.html">Mystery</a>', encoding="utf-8"
        )
        (root / "product" / "mystery.html").write_text(
            "<html><body><h1>Mystery</h1><p>Nothing to parse.</p></body></html>",
            encoding="utf-8",
        )
        return root

    def test_the_serving_catalog_survives_a_collapse(self, tmp_path):
        from paperlane import catalog
        from paperlane.ingest import run_ingest
        from paperlane.refresh import serve

        serving = self.serving_snapshot(tmp_path)
        staged = serving.with_suffix(".tmp.duckdb")
        with serve(self.broken_site(tmp_path)) as base_url:
            code = run_ingest(base_url, rate=2.0, db_path=serving)

        assert code != 0
        assert [p["sku"] for p in catalog.load_products(serving)] == ["PL-T-1", "PL-T-2"]
        assert [p["list_price_satang"] for p in catalog.load_products(serving)] == [12900, 24500]
        assert staged.exists(), "the failed build must stay inspectable"

    def test_the_flag_lets_the_same_run_through(self, tmp_path):
        from paperlane import catalog
        from paperlane.ingest import run_ingest
        from paperlane.refresh import serve

        serving = self.serving_snapshot(tmp_path)
        with serve(self.broken_site(tmp_path)) as base_url:
            code = run_ingest(base_url, rate=2.0, db_path=serving, accept_shrink=True)

        assert code == 0
        assert catalog.load_products(serving) == []
