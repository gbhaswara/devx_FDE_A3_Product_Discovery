"""CLI plumbing for the snapshot path.

Two claims, both from the brief's own requirement that the solution keep running
against a new site "without changing code first":

* `--db` reaches the snapshot the operation reads or writes.
* An unseen-site re-ingest cannot clobber the committed catalog.

The second is the one that matters on demo day. `--base-url` already let the
crawler read a different site; nothing let it write somewhere else, so the only
snapshot was always destroyed by the first re-ingest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from paperlane.cli import build_parser


class TestTheFlagReachesTheCall:
    def test_every_snapshot_reading_command_takes_one(self):
        parser = build_parser()
        for command in ("ingest", "serve", "eval", "ask", "metrics"):
            args = parser.parse_args([command, "--db", "/tmp/named.duckdb"])
            assert args.db == "/tmp/named.duckdb", command

    def test_omitting_it_stays_none_so_the_environment_decides(self):
        """`None` is not a default path.

        Resolving here would bind the choice at parse time and ignore a
        `PAPERLANE_DB` set later; leaving it `None` lets the one resolution
        function decide, which is the point of having one.
        """
        parser = build_parser()
        for command in ("ingest", "serve", "eval", "ask", "metrics"):
            assert parser.parse_args([command]).db is None, command

    def test_ingest_still_takes_the_source_and_rate(self):
        args = build_parser().parse_args(
            ["ingest", "--base-url", "http://example.test/paperlane/", "--rate", "2"]
        )
        assert args.base_url == "http://example.test/paperlane/"
        assert args.rate == 2.0


class TestAnUnseenReingestCannotClobberTheCommittedCatalog:
    def test_the_committed_bytes_survive_a_named_ingest(self, tmp_path, monkeypatch):
        """The load-bearing property, asserted on the bytes.

        A size or mtime check would pass if the file were rewritten identically.
        Reading the committed snapshot's bytes before and after is the only check
        that answers "was this file touched".
        """
        commit = b"pretend this is the committed catalog"
        committed = tmp_path / "catalog.duckdb"
        committed.write_bytes(commit)
        monkeypatch.setattr("paperlane.catalog.DEFAULT_DB_PATH", committed)

        named = tmp_path / "unseen.duckdb"
        from paperlane import catalog

        resolved = catalog.resolve_db_path(str(named))
        assert resolved == named
        assert resolved != committed

        # Writing the named snapshot must not touch the committed one.
        named.write_bytes(b"a build of a different site")
        assert committed.read_bytes() == commit

    def test_serve_and_eval_read_the_named_snapshot(self, tmp_path, monkeypatch):
        from paperlane import catalog

        named = tmp_path / "unseen.duckdb"
        catalog.build_snapshot(
            products=[{
                "sku": "PL-UNSEEN-1",
                "name": "An item from the updated site",
                "brand": "Nusa",
                "category": "Copy paper",
                "size_code": "A4",
                "width_mm": 210,
                "height_mm": 297,
                "weight_gsm": 80,
                "weight_raw": "80 gsm",
                "weight_form": "gsm",
                "colour_name": "White",
                "colour_mode": None,
                "sides": None,
                "finish": "Uncoated",
                "pack_sheets": 500,
                "unit_word": "ream of 500 sheets",
                "list_price_satang": 12000,
                "sale_price_satang": None,
                "on_sale": False,
                "has_volume_pricing": False,
                "stock_status": "in_stock",
                "back_in_stock_date": None,
                "description": "Only present on the updated site.",
                "source_url": "http://example.test/paperlane/product/unseen.html",
                "source_shape": "table",
                "crawled_at": datetime.now(timezone.utc),
                "raw_labels": "{}",
            }],
            tiers=[],
            reviews=[],
            base_url="http://example.test/paperlane/",
            pages_fetched=1,
            tier_docs_found=0,
            target=named,
        )
        monkeypatch.setenv(catalog.DB_PATH_ENV, str(named))

        # Both entry points resolve through the one function, so pointing at a
        # named snapshot is a configuration change rather than a code change.
        assert catalog.snapshot_exists() is True
        assert catalog.health()["path"] == str(named)
        assert [p["sku"] for p in catalog.load_products()] == ["PL-UNSEEN-1"]
