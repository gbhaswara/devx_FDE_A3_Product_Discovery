"""Catalog store tests: build-then-swap, read-only reads, provenance, diff.

Every test builds its own snapshot in a temporary directory, so the suite never
touches the committed catalog and can run offline.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from paperlane import catalog
from paperlane.catalog import (
    SnapshotMissing,
    TierRow,
    build_snapshot,
    diff_snapshots,
    health,
    load_price_facts,
    load_products,
    open_readonly,
    swap_into_place,
)
from paperlane.money import Money, to_satang

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def product_row(sku="PL-T-1", *, list_price="129.00", sale=None,
                stock="in_stock", has_tiers=False, size="A4", gsm=80):
    return {
        "sku": sku,
        "name": f"Test {sku}",
        "brand": "Testbrand",
        "category": "Copy paper",
        "size_code": size,
        "width_mm": 210,
        "height_mm": 297,
        "weight_gsm": gsm,
        "weight_raw": f"{gsm} gsm",
        "weight_form": "gsm",
        "colour_name": "White",
        "colour_mode": None,
        "sides": None,
        "finish": "Uncoated",
        "pack_sheets": 500,
        "unit_word": "ream of 500 sheets",
        "list_price_satang": to_satang(list_price),
        "sale_price_satang": to_satang(sale) if sale else None,
        "has_volume_pricing": has_tiers,
        "stock_status": stock,
        "back_in_stock_date": None,
        "description": "Test product.",
        "source_url": "http://localhost:8000/paperlane/product/test.html",
        "source_shape": "table",
        "crawled_at": NOW,
        "raw_labels": {"Item code": sku},
    }


def tier(sku="PL-T-1", min_qty=10, price="122.55"):
    return TierRow(
        sku=sku,
        min_qty=min_qty,
        unit_price_satang=to_satang(price),
        source_url=f"http://localhost:8000/paperlane/api/pricing/{sku}.json",
        crawled_at=NOW,
    )


def build(tmp_path, products=None, tiers=(), reviews=(), name="catalog.duckdb"):
    target = Path(tmp_path) / name
    return build_snapshot(
        products=products if products is not None else [product_row()],
        tiers=list(tiers),
        reviews=list(reviews),
        base_url="http://localhost:8000/paperlane/",
        pages_fetched=10,
        tier_docs_found=1,
        target=target,
    )


class TestBuild:
    def test_writes_a_readable_snapshot(self, tmp_path):
        path = build(tmp_path)
        assert path.exists()
        with open_readonly(path) as con:
            assert con.execute("SELECT count(*) FROM products").fetchone()[0] == 1

    def test_no_wal_file_remains(self, tmp_path):
        # A leftover .wal would make the committed snapshot incomplete.
        path = build(tmp_path)
        assert not Path(str(path) + ".wal").exists()

    def test_provenance_is_stored(self, tmp_path):
        path = build(tmp_path)
        with open_readonly(path) as con:
            row = con.execute(
                "SELECT source_url, crawled_at, source_shape FROM products"
            ).fetchone()
        assert row[0].endswith("/product/test.html")
        assert row[1] is not None
        assert row[2] == "table"

    def test_tier_provenance_is_stored(self, tmp_path):
        path = build(tmp_path, tiers=[tier()])
        with open_readonly(path) as con:
            row = con.execute(
                "SELECT source_url, crawled_at FROM price_tiers"
            ).fetchone()
        assert "api/pricing/PL-T-1.json" in row[0]
        assert row[1] is not None

    def test_a_crawled_at_keeps_its_instant(self, tmp_path):
        # A TIMESTAMP column carries no zone, so the value written must be UTC
        # wall time: that is what every reader assumes. DuckDB converts an aware
        # datetime into the *session* timezone before storing it, so binding one
        # directly stores local time and the instant moves (BUG.md A19).
        stamped = datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=7)))
        row = product_row()
        row["crawled_at"] = stamped
        path = build(tmp_path, products=[row])
        with open_readonly(path) as con:
            stored = con.execute("SELECT crawled_at FROM products").fetchone()[0]
        assert catalog.parse_stored_timestamp(stored) == stamped

    def test_the_two_representations_of_the_build_time_agree(self, tmp_path):
        # The same instant is written twice: as a TIMESTAMP column and as an ISO
        # string with an explicit offset. If they disagree, the column lost a zone.
        path = build(tmp_path)
        with open_readonly(path) as con:
            finished = con.execute(
                "SELECT finished_at FROM ingest_runs"
            ).fetchone()[0]
            built_at = con.execute(
                "SELECT value FROM meta WHERE key = 'built_at'"
            ).fetchone()[0]
        assert (catalog.parse_stored_timestamp(finished)
                == catalog.parse_stored_timestamp(built_at))

    def test_a_snapshot_built_now_does_not_have_a_negative_age(self, tmp_path):
        # The failure that exposed A19: minutes after an ingest the catalog read
        # "just now" and could never be stale, because age was computed as
        # UTC-now minus a local wall time.
        age = health(build(tmp_path))["freshness"]["age_seconds"]
        assert age is not None
        assert -5 <= age < 120

    def test_money_is_stored_as_integer_satang(self, tmp_path):
        path = build(tmp_path)
        with open_readonly(path) as con:
            value = con.execute("SELECT list_price_satang FROM products").fetchone()[0]
        assert value == 12900
        assert isinstance(value, int)

    def test_float_money_is_rejected(self, tmp_path):
        # The whole money path depends on this never getting through.
        bad = product_row()
        bad["list_price_satang"] = 129.0
        with pytest.raises(TypeError, match="integer satang"):
            build(tmp_path, products=[bad])

    def test_sale_price_nullable(self, tmp_path):
        path = build(tmp_path, products=[
            product_row("A"), product_row("B", sale="259.00")
        ])
        with open_readonly(path) as con:
            rows = dict(con.execute(
                "SELECT sku, sale_price_satang FROM products"
            ).fetchall())
        assert rows["A"] is None
        assert rows["B"] == 25900

    def test_reviews_are_stored_unresolved(self, tmp_path):
        path = build(tmp_path, reviews=[{
            "kind": "extraction",
            "url": "http://x/bad.html",
            "sku": None,
            "reason": "unrecognised markup shape",
            "raw_excerpt": "<html>",
        }])
        with open_readonly(path) as con:
            reason, resolved = con.execute(
                "SELECT reason, resolved FROM review_items"
            ).fetchone()
        assert reason == "unrecognised markup shape"
        assert resolved is False


class TestMissingSnapshot:
    def test_reading_a_missing_snapshot_raises_with_remedy(self, tmp_path):
        missing = Path(tmp_path) / "nope.duckdb"
        with pytest.raises(SnapshotMissing) as exc:
            with open_readonly(missing):
                pass
        assert "run.sh ingest" in str(exc.value)

    def test_health_reports_absence_rather_than_failing(self, tmp_path):
        result = health(Path(tmp_path) / "nope.duckdb")
        assert result["snapshot_present"] is False


class TestHealth:
    def test_reports_counts_and_last_ingest(self, tmp_path):
        path = build(tmp_path, products=[product_row("A"), product_row("B")],
                     tiers=[tier("A")])
        result = health(path)
        assert result["snapshot_present"] is True
        assert result["products"] == 2
        assert result["price_tiers"] == 1
        assert result["last_ingest"]["base_url"].endswith("/paperlane/")
        assert result["last_ingest"]["skus_found"] == 2

    def test_names_the_snapshot(self, tmp_path):
        path = build(tmp_path)
        assert str(path) in health(path)["path"]


class TestIngestRunTiming:
    """The ingest_runs row must span the crawl, not just the database build.

    This exists because the committed snapshot once reported 0.37s for 103
    rate-limited requests -- an implied 280 req/s that the crawler's own guard
    forbids. The row was not measuring a fast crawl; it was measuring the time to
    write DuckDB, because the start timestamp was taken inside build_snapshot.

    Note on storage: the columns are TIMESTAMP, so DuckDB drops the tzinfo and
    keeps the local wall-clock rendering of the instant. These assertions are
    therefore written against *durations*, which are unaffected by that, rather
    than against wall-clock equality.
    """

    def _row(self, target):
        with open_readonly(target) as con:
            return con.execute(
                "SELECT started_at, finished_at FROM ingest_runs"
            ).fetchone()

    def test_crawl_start_is_used_when_supplied(self, tmp_path):
        started = datetime.now(timezone.utc) - timedelta(minutes=30)
        target = Path(tmp_path) / "catalog.duckdb"
        build_snapshot(
            products=[product_row()],
            tiers=[],
            reviews=[],
            base_url="http://localhost:8000/paperlane/",
            pages_fetched=103,
            tier_docs_found=59,
            target=target,
            crawl_started_at=started,
        )
        started_at, finished_at = self._row(target)
        assert finished_at > started_at
        # 30 minutes of crawl plus the build must show up in the row. A start
        # stamped inside the build would give microseconds.
        assert (finished_at - started_at) >= timedelta(minutes=30)

    def test_supplied_start_makes_the_duration_cannot_be_a_fast_crawl(self, tmp_path):
        # The defect, stated as a test: a start an hour in the past must produce a
        # duration of at least an hour. Stamping inside the build cannot satisfy
        # this, which is exactly why the parameter exists.
        started = datetime.now(timezone.utc) - timedelta(hours=1)
        target = Path(tmp_path) / "catalog.duckdb"
        build_snapshot(
            products=[product_row()],
            tiers=[],
            reviews=[],
            base_url="http://localhost:8000/paperlane/",
            pages_fetched=103,
            tier_docs_found=59,
            target=target,
            crawl_started_at=started,
        )
        started_at, finished_at = self._row(target)
        assert (finished_at - started_at) >= timedelta(hours=1)

    def test_omitting_the_start_still_works(self, tmp_path):
        # Direct callers (mostly tests) keep the old behaviour rather than being
        # forced to invent a timestamp. The row still records something sane.
        path = build(tmp_path)
        started_at, finished_at = self._row(path)
        assert started_at <= finished_at
        assert (finished_at - started_at) < timedelta(minutes=1)


class TestBuildThenSwap:
    def test_failed_build_leaves_the_serving_snapshot_intact(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        # First a good snapshot, swapped into place.
        good = build(tmp_path, products=[product_row("A")], name="stage1.duckdb")
        swap_into_place(good, serving)
        before = health(serving)["products"]

        # Now a build that fails mid-way. It must not touch the serving file.
        bad = product_row("B")
        bad["list_price_satang"] = 1.5
        with pytest.raises(TypeError):
            build_snapshot(
                products=[bad], tiers=[], reviews=[],
                base_url="http://x/", pages_fetched=1, tier_docs_found=0,
                target=Path(tmp_path) / "stage2.duckdb",
            )

        assert health(serving)["products"] == before
        with open_readonly(serving) as con:
            assert con.execute("SELECT count(*) FROM products").fetchone()[0] == before

    def test_swap_replaces_the_serving_snapshot(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        first = build(tmp_path, products=[product_row("A")], name="s1.duckdb")
        swap_into_place(first, serving)
        assert health(serving)["products"] == 1

        second = build(tmp_path, products=[product_row("A"), product_row("B")],
                       name="s2.duckdb")
        swap_into_place(second, serving)
        assert health(serving)["products"] == 2

    def test_staged_file_is_gone_after_swap(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        staged = build(tmp_path, name="stage.duckdb")
        swap_into_place(staged, serving)
        assert not staged.exists()
        assert serving.exists()


class TestConcurrentReads:
    def test_many_concurrent_reads_succeed(self, tmp_path):
        # A shared connection across threads raises "Resource In Use Error";
        # one read-only connection per request does not.
        path = build(tmp_path, products=[product_row(f"S{i}") for i in range(20)])
        errors: list[Exception] = []
        results: list[int] = []

        def reader():
            try:
                with open_readonly(path) as con:
                    results.append(
                        con.execute("SELECT count(*) FROM products").fetchone()[0]
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], errors
        assert results == [20] * 20

    def test_reads_are_consistent(self, tmp_path):
        path = build(tmp_path, products=[product_row(f"S{i}") for i in range(5)],
                     tiers=[tier(f"S{i}") for i in range(5)])
        with open_readonly(path) as con:
            p = con.execute("SELECT count(*) FROM products").fetchone()[0]
            t = con.execute("SELECT count(*) FROM price_tiers").fetchone()[0]
        assert (p, t) == (5, 5)


class TestLoaders:
    def test_load_products(self, tmp_path):
        path = build(tmp_path, products=[product_row("A"), product_row("B")])
        rows = load_products(path)
        assert [r["sku"] for r in rows] == ["A", "B"]
        assert rows[0]["weight_gsm"] == 80

    def test_load_price_facts_builds_pricing_inputs(self, tmp_path):
        path = build(
            tmp_path,
            products=[product_row("A"), product_row("B", sale="259.00")],
            tiers=[tier("A", 10, "122.55"), tier("A", 50, "116.10")],
        )
        facts = load_price_facts(path)
        assert set(facts) == {"A", "B"}
        assert facts["A"].list_price == Money.from_baht("129.00")
        assert [t.min_qty for t in facts["A"].tiers] == [10, 50]
        assert facts["B"].on_sale is True
        assert facts["B"].sale_price == Money.from_baht("259.00")

    def test_price_facts_feed_the_engine(self, tmp_path):
        # The store and the pricing engine must agree on the same numbers.
        from paperlane.pricing import LineRequest, quote

        path = build(tmp_path, products=[product_row("A")],
                     tiers=[tier("A", 10, "122.55")])
        facts = load_price_facts(path)
        q = quote([LineRequest("A", 10, facts["A"])])
        assert q.subtotal.format() == "1,225.50"


class TestDiff:
    def test_no_previous_snapshot_reports_that(self, tmp_path):
        new = build(tmp_path, name="new.duckdb")
        result = diff_snapshots(Path(tmp_path) / "absent.duckdb", new)
        assert result["comparable"] is False
        assert "no previous snapshot" in result["reason"]
    def test_identical_snapshots_report_no_change(self, tmp_path):
        old = build(tmp_path, products=[product_row("A")], name="old.duckdb")
        new = build(tmp_path, products=[product_row("A")], name="new.duckdb")
        result = diff_snapshots(old, new)
        assert result["comparable"] is True
        assert result["no_change"] is True

    def test_added_and_withdrawn(self, tmp_path):
        old = build(tmp_path, products=[product_row("A"), product_row("B")],
                    name="old.duckdb")
        new = build(tmp_path, products=[product_row("B"), product_row("C")],
                    name="new.duckdb")
        result = diff_snapshots(old, new)
        assert result["added"] == ["C"]
        assert result["withdrawn"] == ["A"]

    def test_price_change_records_before_and_after(self, tmp_path):
        old = build(tmp_path, products=[product_row("A", list_price="129.00")],
                    name="old.duckdb")
        new = build(tmp_path, products=[product_row("A", list_price="135.00")],
                    name="new.duckdb")
        result = diff_snapshots(old, new)
        assert len(result["price_changed"]) == 1
        change = result["price_changed"][0]
        assert change["list_before"] == 12900
        assert change["list_after"] == 13500

    def test_availability_change(self, tmp_path):
        old = build(tmp_path, products=[product_row("A")], name="old.duckdb")
        new = build(tmp_path, products=[product_row("A", stock="out_of_stock")],
                    name="new.duckdb")
        result = diff_snapshots(old, new)
        assert result["availability_changed"][0]["after"] == "out_of_stock"

    def test_tier_change(self, tmp_path):
        old = build(tmp_path, products=[product_row("A", has_tiers=True)],
                    tiers=[tier("A", 10, "122.55")], name="old.duckdb")
        new = build(tmp_path, products=[product_row("A", has_tiers=True)],
                    tiers=[tier("A", 10, "120.00")], name="new.duckdb")
        result = diff_snapshots(old, new)
        assert len(result["tier_changed"]) == 1

    def test_parse_failures_surface_in_the_diff(self, tmp_path):
        old = build(tmp_path, products=[product_row("A")], name="old.duckdb")
        new = build(tmp_path, products=[product_row("A")], name="new.duckdb",
                    reviews=[{"kind": "extraction", "url": "http://x/bad.html",
                              "sku": None, "reason": "unrecognised markup shape",
                              "raw_excerpt": "<html>"}])
        result = diff_snapshots(old, new)
        assert len(result["parse_failed"]) == 1
        assert "unrecognised" in result["parse_failed"][0]["reason"]


# ---------------------------------------------------------------------------
# 7.1 Build-then-swap: a failed ingest never damages the serving catalog
# ---------------------------------------------------------------------------


class TestFailedIngestIsHarmless:
    def test_failure_partway_through_leaves_the_serving_file_unchanged(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        good = build(tmp_path, products=[product_row("A")], name="stage1.duckdb")
        swap_into_place(good, serving)
        before_bytes = serving.read_bytes()

        # Fail on the *second* row, after the first has been inserted, so the
        # staged file is genuinely half-written when the error is raised.
        rows = [product_row("A"), product_row("B")]
        rows[1]["list_price_satang"] = Decimal("1.5")   # not integer satang
        with pytest.raises(TypeError):
            build_snapshot(
                products=rows, tiers=[], reviews=[], base_url="http://x/",
                pages_fetched=1, tier_docs_found=0,
                target=Path(tmp_path) / "stage2.duckdb",
            )

        assert serving.read_bytes() == before_bytes
        assert health(serving)["products"] == 1

    def test_a_failed_build_leaves_no_staging_file_behind(self, tmp_path):
        # A half-written staging file would be swapped in by the next run's
        # swap if it were ever mistaken for a complete build.
        bad = product_row("A")
        bad["list_price_satang"] = "not a number"
        staged = Path(tmp_path) / "stage.duckdb"
        with pytest.raises((TypeError, ValueError)):
            build_snapshot(
                products=[bad], tiers=[], reviews=[], base_url="http://x/",
                pages_fetched=1, tier_docs_found=0, target=staged,
            )
        assert not staged.exists()


# ---------------------------------------------------------------------------
# 7.2 Read-only per-request connections
# ---------------------------------------------------------------------------


class TestReadOnlyConnections:
    def test_reads_succeed_while_a_writer_holds_the_file(self, tmp_path):
        # The serving process reads while an ingest writes its staging file.
        # These are different files, so reads must never block.
        serving = Path(tmp_path) / "catalog.duckdb"
        swap_into_place(build(tmp_path, name="s1.duckdb"), serving)

        import duckdb

        writer = duckdb.connect(str(Path(tmp_path) / "staging.duckdb"))
        try:
            writer.execute("CREATE TABLE t (x INTEGER)")
            # Reads of the serving file still work.
            with open_readonly(serving) as con:
                assert con.execute("SELECT count(*) FROM products").fetchone()[0] == 1
        finally:
            writer.close()

    def test_a_read_only_connection_cannot_write(self, tmp_path):
        path = build(tmp_path)
        with open_readonly(path) as con:
            with pytest.raises(Exception):
                con.execute("INSERT INTO products (sku) VALUES ('X')")

    def test_health_and_loaders_agree(self, tmp_path):
        path = build(tmp_path, products=[product_row("A"), product_row("B")],
                     tiers=[tier("A")])
        report = health(path)
        assert report["products"] == len(load_products(path))
        assert report["price_tiers"] == sum(
            len(f.tiers) for f in load_price_facts(path).values()
        )


# ---------------------------------------------------------------------------
# 7.4 Explicit no-change reporting
# ---------------------------------------------------------------------------


class TestNoChangeReporting:
    def test_identical_reingest_says_no_change_not_empty_success(self, tmp_path):
        old = build(tmp_path, products=[product_row("A"), product_row("B")],
                    tiers=[tier("A")], name="old.duckdb")
        new = build(tmp_path, products=[product_row("A"), product_row("B")],
                    tiers=[tier("A")], name="new.duckdb")
        result = diff_snapshots(old, new)
        # The distinction that matters: "nothing changed" is a *positive*
        # statement, not an absence of findings.
        assert result["comparable"] is True
        assert result["no_change"] is True
        for kind in ("added", "withdrawn", "price_changed",
                     "availability_changed", "tier_changed", "parse_failed"):
            assert result[kind] == [], kind

    def test_a_real_change_is_not_reported_as_no_change(self, tmp_path):
        old = build(tmp_path, products=[product_row("A")], name="old.duckdb")
        new = build(tmp_path, products=[product_row("A", list_price="130.00")],
                    name="new.duckdb")
        result = diff_snapshots(old, new)
        assert result["no_change"] is False

    def test_no_previous_snapshot_is_not_no_change(self, tmp_path):
        new = build(tmp_path, name="new.duckdb")
        result = diff_snapshots(Path(tmp_path) / "absent.duckdb", new)
        # Crucially not "no_change": there is nothing to have changed from.
        assert result["comparable"] is False
        assert "no_change" not in result


# ---------------------------------------------------------------------------
# 7.5 Review-set persistence across refreshes
# ---------------------------------------------------------------------------


def review(url="http://x/bad.html", sku=None, kind="extraction", reason="ambiguous"):
    return {"kind": kind, "url": url, "sku": sku, "reason": reason,
            "raw_excerpt": "<html>"}


class TestReviewPersistence:
    def test_an_unresolved_item_survives_the_next_ingest(self, tmp_path):
        first = build(tmp_path, products=[product_row("A")],
                      reviews=[review()], name="first.duckdb")
        assert health(first)["open_review_items"] == 1

        # The next ingest reports nothing new. The old item must not vanish:
        # that would make a flagged problem look fixed.
        second = build_snapshot(
            products=[product_row("A")], tiers=[], reviews=[],
            base_url="http://x/", pages_fetched=1, tier_docs_found=0,
            target=Path(tmp_path) / "second.duckdb",
            carry_reviews_from=first,
        )
        report = health(second)
        assert report["open_review_items"] == 1
        assert report["carried_review_items"] == 1

    def test_the_carried_item_keeps_its_original_reason(self, tmp_path):
        first = build(tmp_path, products=[product_row("A")],
                      reviews=[review(reason="ambiguous price box")],
                      name="first.duckdb")
        second = build_snapshot(
            products=[product_row("A")], tiers=[], reviews=[],
            base_url="http://x/", pages_fetched=1, tier_docs_found=0,
            target=Path(tmp_path) / "second.duckdb",
            carry_reviews_from=first,
        )
        with open_readonly(second) as con:
            reason, carried = con.execute(
                "SELECT reason, carried_from FROM review_items"
            ).fetchone()
        assert reason == "ambiguous price box"
        assert carried is not None

    def test_a_recurring_item_is_not_duplicated(self, tmp_path):
        first = build(tmp_path, products=[product_row("A")],
                      reviews=[review()], name="first.duckdb")
        # Reported again by the new run: it must appear once, not twice.
        second = build_snapshot(
            products=[product_row("A")], tiers=[], reviews=[review()],
            base_url="http://x/", pages_fetched=1, tier_docs_found=0,
            target=Path(tmp_path) / "second.duckdb",
            carry_reviews_from=first,
        )
        report = health(second)
        assert report["open_review_items"] == 1
        # Freshly reported, so it is not marked as carried.
        assert report["carried_review_items"] == 0

    def test_a_fixed_item_stops_being_reported(self, tmp_path):
        first = build(tmp_path, products=[product_row("A")],
                      reviews=[review()], name="first.duckdb")
        # Mark it resolved in the serving snapshot, as a human would.
        import duckdb

        con = duckdb.connect(str(first))
        con.execute("UPDATE review_items SET resolved = TRUE")
        con.execute("CHECKPOINT")
        con.close()

        second = build_snapshot(
            products=[product_row("A")], tiers=[], reviews=[],
            base_url="http://x/", pages_fetched=1, tier_docs_found=0,
            target=Path(tmp_path) / "second.duckdb",
            carry_reviews_from=first,
        )
        assert health(second)["open_review_items"] == 0

    def test_carrying_from_a_missing_snapshot_is_not_fatal(self, tmp_path):
        # A first-ever ingest has nothing to carry from.
        path = build_snapshot(
            products=[product_row("A")], tiers=[], reviews=[],
            base_url="http://x/", pages_fetched=1, tier_docs_found=0,
            target=Path(tmp_path) / "fresh.duckdb",
            carry_reviews_from=Path(tmp_path) / "absent.duckdb",
        )
        assert health(path)["open_review_items"] == 0

    def test_different_items_are_all_carried(self, tmp_path):
        first = build(tmp_path, products=[product_row("A")],
                      reviews=[review(url="http://x/1.html"),
                               review(url="http://x/2.html")],
                      name="first.duckdb")
        second = build_snapshot(
            products=[product_row("A")], tiers=[], reviews=[],
            base_url="http://x/", pages_fetched=1, tier_docs_found=0,
            target=Path(tmp_path) / "second.duckdb",
            carry_reviews_from=first,
        )
        assert health(second)["open_review_items"] == 2


# ---------------------------------------------------------------------------
# The baseline that makes `diff` usable after a refresh
# ---------------------------------------------------------------------------


class TestPreviousSnapshotBaseline:
    def test_swap_keeps_the_outgoing_snapshot(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        swap_into_place(build(tmp_path, products=[product_row("A")],
                              name="s1.duckdb"), serving)
        swap_into_place(build(tmp_path, products=[product_row("B")],
                              name="s2.duckdb"), serving)

        # Without this baseline `diff` has nothing to compare against after
        # every refresh, which makes it useless exactly when it is wanted.
        assert catalog.previous_path(serving).exists()
        assert health(catalog.previous_path(serving))["products"] == 1
        assert health(serving)["products"] == 1

    def test_first_swap_has_no_baseline(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        swap_into_place(build(tmp_path, name="s1.duckdb"), serving)
        # Nothing was displaced, so there is no baseline to pretend exists.
        assert not catalog.previous_path(serving).exists()

    def test_diff_defaults_compare_previous_against_current(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        swap_into_place(build(tmp_path, products=[product_row("A")],
                              name="s1.duckdb"), serving)
        swap_into_place(build(tmp_path, products=[product_row("A"),
                                                  product_row("B")],
                              name="s2.duckdb"), serving)

        # Point the module defaults at this temporary pair.
        result = diff_snapshots(catalog.previous_path(serving), serving)
        assert result["comparable"] is True
        assert result["added"] == ["B"]
        assert result["no_change"] is False
        assert result["old"].endswith("catalog.previous.duckdb")
        assert result["new"].endswith("catalog.duckdb")

    def test_a_failed_swap_does_not_lose_the_baseline(self, tmp_path):
        serving = Path(tmp_path) / "catalog.duckdb"
        swap_into_place(build(tmp_path, products=[product_row("A")],
                              name="s1.duckdb"), serving)
        swap_into_place(build(tmp_path, products=[product_row("B")],
                              name="s2.duckdb"), serving)
        baseline_before = catalog.previous_path(serving).read_bytes()

        # A later build fails before swapping. The baseline must survive, or the
        # next diff silently reports "no previous snapshot".
        bad = product_row("C")
        bad["list_price_satang"] = "nonsense"
        with pytest.raises((TypeError, ValueError)):
            build_snapshot(products=[bad], tiers=[], reviews=[], base_url="x",
                           pages_fetched=1, tier_docs_found=0,
                           target=Path(tmp_path) / "stage3.duckdb")
        assert catalog.previous_path(serving).read_bytes() == baseline_before
