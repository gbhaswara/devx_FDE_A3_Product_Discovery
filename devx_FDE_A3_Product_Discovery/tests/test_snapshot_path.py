"""Snapshot location and catalog freshness.

Two additions, both from the same gap: a live re-ingest of an unseen site must
not overwrite the catalog every recorded expectation is written against, and a
stale catalog must not be indistinguishable from a fresh one.

The resolution tests matter more than they look. `resolve_db_path` was documented
as "one place for the fallback" while five call sites re-spelled it, so a new
environment variable honoured by some readers and not others is a snapshot
mix-up that presents as a wrong price rather than as a configuration error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from paperlane import catalog
from paperlane.catalog import (
    STALE_AFTER_HOURS,
    health,
    resolve_db_path,
    snapshot_meta,
    staleness,
)


# ---------------------------------------------------------------------------
# Which snapshot does a caller mean?
# ---------------------------------------------------------------------------


class TestSnapshotResolution:
    def test_default_is_the_committed_snapshot(self, monkeypatch):
        monkeypatch.delenv(catalog.DB_PATH_ENV, raising=False)
        assert resolve_db_path() == catalog.DEFAULT_DB_PATH

    def test_the_environment_names_an_alternative(self, monkeypatch, tmp_path):
        named = tmp_path / "unseen.duckdb"
        monkeypatch.setenv(catalog.DB_PATH_ENV, str(named))
        assert resolve_db_path() == named

    def test_an_explicit_argument_beats_the_environment(self, monkeypatch, tmp_path):
        monkeypatch.setenv(catalog.DB_PATH_ENV, str(tmp_path / "env.duckdb"))
        explicit = tmp_path / "explicit.duckdb"
        assert resolve_db_path(explicit) == explicit

    def test_every_reader_resolves_the_same_path(self, monkeypatch, tmp_path):
        """The property that makes one definition worth having.

        Each of these previously re-spelled the fallback. If any of them still
        did, it would read the committed catalog while the rest read the named
        one — and an answer computed from one snapshot while reported against
        another is the failure this function exists to prevent.
        """
        named = tmp_path / "unseen.duckdb"
        monkeypatch.setenv(catalog.DB_PATH_ENV, str(named))

        assert catalog.snapshot_exists() is False
        assert health()["path"] == str(named)
        assert catalog.previous_path() == named.with_suffix(".previous.duckdb")
        assert snapshot_meta()["path"] == str(named)
        with pytest.raises(catalog.SnapshotMissing):
            with catalog.open_readonly():
                pass

    def test_an_empty_environment_value_falls_back(self, monkeypatch):
        # An unset-but-present variable is a common shell accident; it must not
        # resolve to the current directory.
        monkeypatch.setenv(catalog.DB_PATH_ENV, "")
        assert resolve_db_path() == catalog.DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Age and staleness
# ---------------------------------------------------------------------------


class TestStoredTimestamp:
    def test_the_zone_less_stored_value_is_read_as_utc(self):
        """The stored string has no zone, and that is not a reason to guess local.

        The crawl stamps with ``datetime.now(timezone.utc)`` and DuckDB returns a
        naive ``TIMESTAMP``. Reading it as local time in a UTC+7 deployment would
        make a nine-hour-old catalog look minutes old — the exact reading the
        freshness signal exists to prevent.
        """
        parsed = catalog.parse_stored_timestamp("2026-10-27 00:25:24.500248")
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)
        assert parsed.hour == 0

    def test_an_iso_string_is_accepted_too(self):
        parsed = catalog.parse_stored_timestamp("2026-10-27T00:25:24")
        assert parsed is not None and parsed.utcoffset() == timedelta(0)

    @pytest.mark.parametrize("value", [None, "", "   ", "None", "not a date"])
    def test_an_unreadable_value_is_unknown_not_zero(self, value):
        # Unknown and "just built" must not read the same.
        assert catalog.parse_stored_timestamp(value) is None
        assert catalog.age_of(value) is None


class TestStaleness:
    def test_age_is_measured_from_the_timestamp(self):
        moment = datetime.now(timezone.utc) - timedelta(hours=5)
        facts = staleness(moment.replace(tzinfo=None), threshold_hours=24)
        assert 4.9 * 3600 < facts["age_seconds"] < 5.1 * 3600
        assert facts["age_human"] == "5h"
        assert facts["stale"] is False

    def test_an_old_catalog_is_flagged_stale(self):
        moment = datetime.now(timezone.utc) - timedelta(days=3)
        assert staleness(moment, threshold_hours=24)["stale"] is True

    def test_the_default_threshold_is_named_and_overridable(self, monkeypatch):
        assert STALE_AFTER_HOURS == 24.0
        monkeypatch.setenv(catalog.STALE_AFTER_ENV, "1")
        assert catalog.stale_after_hours() == 1.0
        recent = datetime.now(timezone.utc) - timedelta(hours=2)
        assert staleness(recent)["stale"] is True

    def test_a_misspelled_threshold_falls_back_rather_than_raising(self, monkeypatch):
        # A bad override must not take down the endpoint whose job is to report
        # that something is wrong.
        for bad in ("yesterday", "0", "-3"):
            monkeypatch.setenv(catalog.STALE_AFTER_ENV, bad)
            assert catalog.stale_after_hours() == STALE_AFTER_HOURS

    def test_an_unknown_age_is_unknown_not_fresh(self):
        facts = staleness(None)
        assert facts["age_seconds"] is None
        assert facts["age_human"] is None
        assert facts["stale"] is None

    def test_clock_skew_is_not_staleness(self):
        ahead = datetime.now(timezone.utc) + timedelta(minutes=30)
        facts = staleness(ahead, threshold_hours=1)
        assert facts["age_human"] == "just now"
        assert facts["stale"] is False


class TestHealthCarriesFreshness:
    def test_health_reports_the_age_of_the_committed_catalog(self):
        info = health()
        assert info["snapshot_present"]
        fresh = info["freshness"]
        assert fresh["built_at"]
        assert isinstance(fresh["age_seconds"], float)
        assert fresh["stale"] in (True, False)

    def test_snapshot_meta_carries_the_age_with_the_figures(self):
        """"Computed against snapshot X" is incomplete without "X is N hours old"."""
        meta = snapshot_meta()
        assert meta["built_at"]
        assert meta["freshness"]["age_seconds"] is not None

    def test_an_absent_snapshot_reports_no_freshness(self, tmp_path):
        # Nothing to be fresh. Not a stale catalog — a missing one.
        info = health(tmp_path / "absent.duckdb")
        assert info == {
            "snapshot_present": False,
            "path": str(tmp_path / "absent.duckdb"),
        }


class TestMetricsReportsTheAge:
    """The catalog's age belongs beside the review backlog.

    Both are facts about the snapshot rather than rates over records, so neither
    depends on traffic and neither is a sixth derived measure. It is reported in
    the empty-record branch too, because how old the catalog is does not stop
    being true when no requests have been served.
    """

    def _render(self, **kwargs):
        import io

        from paperlane import metrics as metrics_mod

        buffer = io.StringIO()
        metrics_mod.render(metrics_mod.derive(**kwargs), out=buffer)
        return buffer.getvalue()

    def test_the_age_is_printed(self):
        text = self._render()
        assert "catalog age:" in text

    def test_it_is_printed_even_with_no_records(self, tmp_path):
        # A log with nothing in it must not hide the snapshot's age.
        from paperlane import metrics as metrics_mod
        from paperlane import records as records_mod

        empty = tmp_path / "records.jsonl"
        empty.write_text("")
        text = self._render(writer=records_mod.RecordWriter(empty))
        assert "catalog age:" in text

    def test_the_stale_flag_is_printed_when_it_applies(self, monkeypatch):
        monkeypatch.setenv(catalog.STALE_AFTER_ENV, "0.001")
        assert "STALE" in self._render()

    def test_the_payload_carries_it_too(self):
        from paperlane import metrics as metrics_mod

        payload = metrics_mod.derive().as_dict()
        fresh = payload["snapshot"]["freshness"]
        assert fresh["age_seconds"] is not None
        assert fresh["stale_after_hours"] == 24.0


class TestFreshnessNeverBlocks:
    def test_a_stale_catalog_still_answers(self, monkeypatch):
        """Reported, never gating.

        The demo round re-ingests a live site and asks for answers immediately; a
        threshold that refused to serve would fail the demonstration in the room.
        """
        monkeypatch.setenv(catalog.STALE_AFTER_ENV, "0.001")
        assert health()["freshness"]["stale"] is True

        from fastapi.testclient import TestClient

        from paperlane.api import create_app

        with TestClient(create_app()) as client:
            assert client.get("/api/health").status_code == 200
            answered = client.post(
                "/api/ask",
                json={"request": "A4 80gsm copy paper, 1 ream", "use_model": False},
            )
            assert answered.status_code == 200, answered.text
            assert answered.json()["outcome"] == "quoted"
            assert answered.json()["figures"]["total"]
