"""The DuckDB catalog store: build-then-swap, read-only per request.

Two properties matter more than anything else here.

**Build then swap.** An ingest writes a complete new snapshot to a temporary
file and only replaces the serving file once that build has fully succeeded. A
crawl that dies half way through therefore cannot damage the catalog that is
currently answering questions — the previous snapshot keeps serving untouched.

**Read-only connections per request.** DuckDB permits many concurrent readers or
one writer, never both, and a connection shared across threads raises
``Resource In Use Error``. So the serving path opens a fresh read-only
connection per request and closes it immediately; the writer only ever runs
during ingest, against a file nobody is serving.

Money is stored as integer satang. No float column exists anywhere in the
schema, and the loader rejects a float before it can reach one.
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import duckdb

from .money import to_satang

#: Where the committed snapshot lives, and where a build is staged.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog.duckdb"

#: An alternative snapshot, named by the environment. The demo round supplies an
#: updated site and asks for a live re-ingest; pointing that at a named snapshot
#: keeps the committed catalog — the one every recorded expectation is written
#: against — from being overwritten by an unreviewed build. Precedence is
#: explicit argument, then this, then :data:`DEFAULT_DB_PATH`.
DB_PATH_ENV = "PAPERLANE_DB"

#: How old a snapshot may be before it is reported stale, in hours. A starting
#: point for a merchant whose prices and stock move daily, not a universal
#: constant — overridable by ``PAPERLANE_STALE_AFTER_HOURS``. Staleness is
#: *reported and never gating*: refusing to answer is a worse failure than
#: answering from a catalog whose age is stated.
STALE_AFTER_HOURS = 24.0
STALE_AFTER_ENV = "PAPERLANE_STALE_AFTER_HOURS"

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE meta (
    key   VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);

CREATE TABLE ingest_runs (
    run_id          VARCHAR PRIMARY KEY,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    base_url        VARCHAR NOT NULL,
    pages_fetched   INTEGER NOT NULL DEFAULT 0,
    skus_found      INTEGER NOT NULL DEFAULT 0,
    tier_docs_found INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR NOT NULL
);

CREATE TABLE products (
    sku                VARCHAR PRIMARY KEY,
    name               VARCHAR NOT NULL,
    brand              VARCHAR,
    category           VARCHAR,
    size_code          VARCHAR,
    width_mm           INTEGER,
    height_mm          INTEGER,
    weight_gsm         INTEGER,
    weight_raw         VARCHAR,
    weight_form        VARCHAR,
    colour_name        VARCHAR,
    colour_mode        VARCHAR,
    sides              VARCHAR,
    finish             VARCHAR,
    pack_sheets        INTEGER,
    unit_word          VARCHAR,
    list_price_satang  BIGINT NOT NULL,
    sale_price_satang  BIGINT,
    on_sale            BOOLEAN NOT NULL DEFAULT FALSE,
    has_volume_pricing BOOLEAN NOT NULL DEFAULT FALSE,
    stock_status       VARCHAR NOT NULL,
    back_in_stock_date VARCHAR,
    description        VARCHAR,
    source_url         VARCHAR NOT NULL,
    source_shape       VARCHAR NOT NULL,
    crawled_at         TIMESTAMP NOT NULL,
    raw_labels         VARCHAR
);

CREATE TABLE price_tiers (
    sku               VARCHAR NOT NULL,
    min_qty           INTEGER NOT NULL,
    unit_price_satang BIGINT NOT NULL,
    source_url        VARCHAR NOT NULL,
    crawled_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (sku, min_qty)
);

CREATE TABLE review_items (
    run_id      VARCHAR NOT NULL,
    kind        VARCHAR NOT NULL,
    url         VARCHAR NOT NULL,
    sku         VARCHAR,
    reason      VARCHAR NOT NULL,
    raw_excerpt VARCHAR,
    resolved    BOOLEAN NOT NULL DEFAULT FALSE,
    carried_from VARCHAR
);
"""

INDEX_SQL = """
CREATE INDEX idx_products_size  ON products(size_code);
CREATE INDEX idx_products_gsm   ON products(weight_gsm);
CREATE INDEX idx_products_stock ON products(stock_status);
"""


class SnapshotMissing(RuntimeError):
    """Raised when no snapshot exists yet. The API turns this into a remedy."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"No catalog snapshot at {path}. Build one with: "
            f"./run.sh ingest --base-url http://localhost:8000/paperlane/"
        )
        self.path = path


@dataclass(frozen=True)
class TierRow:
    sku: str
    min_qty: int
    unit_price_satang: int
    source_url: str
    crawled_at: datetime


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _connect_readonly(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Open a read-only connection. Caller must close it."""
    return duckdb.connect(str(db_path), read_only=True)


def resolve_db_path(db_path: Path | None = None) -> Path:
    """The snapshot path a caller means.

    Precedence is an explicit argument, then ``PAPERLANE_DB``, then the committed
    snapshot. This is the *only* place the fallback is spelled: every reader and
    writer routes through it, because two spellings of "which snapshot" is how one
    code path ends up serving from a named snapshot while another reports the
    committed one — a mix-up that presents as a wrong price rather than as a
    configuration error.
    """
    if db_path is not None:
        return Path(db_path)
    named = os.environ.get(DB_PATH_ENV)
    return Path(named) if named else DEFAULT_DB_PATH


@contextmanager
def open_readonly(db_path: Path | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    """A short-lived read-only connection, one per request.

    Never share a connection across threads: DuckDB raises
    ``Resource In Use Error`` when two threads touch one connection at once.
    A fresh read-only connection per request costs milliseconds and removes the
    whole class of failure.
    """
    path = resolve_db_path(db_path)
    if not path.exists():
        raise SnapshotMissing(path)
    con = _connect_readonly(path)
    try:
        yield con
    finally:
        con.close()


def snapshot_exists(db_path: Path | None = None) -> bool:
    return resolve_db_path(db_path).exists()


def snapshot_meta(db_path: Path | None = None) -> dict[str, Any]:
    """A compact statement of what an answer was computed against.

    Lives here rather than in the HTTP layer because every entry point that
    writes a request record needs it — the API, the CLI, and the evaluation
    harness. A per-caller copy is how one of them ends up naming the committed
    snapshot while serving from a temporary one, which points an investigation
    at the wrong file.

    Takes the snapshot path so an injected database is named correctly.
    """
    info = health(db_path)
    last = info.get("last_ingest") or {}
    return {
        "path": info.get("path"),
        "products": info.get("products"),
        "price_tiers": info.get("price_tiers"),
        "built_at": last.get("finished_at"),
        "base_url": last.get("base_url"),
        # Age travels with the figures, because "computed against snapshot X" is
        # not a complete answer without "X is nine hours old".
        "freshness": info.get("freshness"),
    }


def stale_after_hours() -> float:
    """The staleness threshold, from the environment or the documented default.

    A bad value falls back rather than raising: a misspelled override must not
    take down the health endpoint whose job is to report that something is wrong.
    """
    raw = os.environ.get(STALE_AFTER_ENV)
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return STALE_AFTER_HOURS
        if value > 0:
            return value
    return STALE_AFTER_HOURS


def parse_stored_timestamp(value: Any) -> datetime | None:
    """Read an ingest timestamp back as an aware UTC datetime.

    DuckDB returns a ``TIMESTAMP`` as a naive string. The crawl stamps it with
    ``datetime.now(timezone.utc)``, so the value *is* UTC and the zone was lost on
    the way out — not omitted because it was local. Attaching local time here
    would make a nine-hour-old catalog look fresh in a UTC+7 timezone, which is
    precisely the reading the freshness signal exists to prevent.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text or text == "None":
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def stored_timestamp(value: datetime) -> datetime:
    """A timestamp in the form the database stores it: UTC, zone dropped.

    DuckDB's ``TIMESTAMP`` carries no zone, and it converts an aware value into
    the *session* timezone before storing it. Binding ``datetime.now(timezone.utc)``
    directly therefore stored local wall time while every reader treats the
    stored value as UTC (BUG.md A19): the catalog reported itself seven hours
    younger than it was, and a snapshot built moments earlier had a negative
    age — so it could never look stale. Converting here makes the stored value
    UTC by construction, whatever timezone the host or session happens to be in.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def age_of(built_at: Any) -> float | None:
    """Seconds since the catalog was built, or ``None`` when it is unknown."""
    stamped = parse_stored_timestamp(built_at)
    if stamped is None:
        return None
    return (datetime.now(timezone.utc) - stamped).total_seconds()


def humanise_age(seconds: float | None) -> str | None:
    """A short, readable age. ``None`` stays ``None`` rather than "0s"."""
    if seconds is None:
        return None
    if seconds < 0:
        # A clock skew between the ingest host and the reader is not staleness.
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes / 60
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours / 24)}d"


def staleness(built_at: Any, *, threshold_hours: float | None = None) -> dict[str, Any]:
    """The age of a snapshot, and whether it exceeds the stated threshold.

    Reported on every surface that describes the catalog. Never a gate: see
    :data:`STALE_AFTER_HOURS`.
    """
    threshold = threshold_hours if threshold_hours is not None else stale_after_hours()
    age = age_of(built_at)
    return {
        "built_at": str(built_at) if built_at is not None else None,
        "age_seconds": round(age, 1) if age is not None else None,
        "age_human": humanise_age(age),
        "stale_after_hours": threshold,
        # ``None`` when the age is unknown: "not stale" and "cannot tell" must not
        # read the same, for the same reason every rate in metrics.py is None on
        # an empty log.
        "stale": (age > threshold * 3600) if age is not None else None,
    }


def health(db_path: Path | None = None) -> dict[str, Any]:
    """Counts, provenance and age for the health endpoint."""
    path = resolve_db_path(db_path)
    if not path.exists():
        return {"snapshot_present": False, "path": str(path)}

    with open_readonly(path) as con:
        products = con.execute("SELECT count(*) FROM products").fetchone()[0]
        tiers = con.execute("SELECT count(*) FROM price_tiers").fetchone()[0]
        reviews = con.execute(
            "SELECT count(*) FROM review_items WHERE resolved = FALSE"
        ).fetchone()[0]
        try:
            carried = con.execute(
                "SELECT count(*) FROM review_items "
                "WHERE resolved = FALSE AND carried_from IS NOT NULL"
            ).fetchone()[0]
        except Exception:  # noqa: BLE001 - a snapshot built before carry-forward
            carried = 0
        last = con.execute(
            "SELECT run_id, finished_at, base_url, pages_fetched, skus_found, "
            "tier_docs_found FROM ingest_runs ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())

    built_at = last[1] if last else None
    return {
        "snapshot_present": True,
        "path": str(path),
        "products": products,
        "price_tiers": tiers,
        "open_review_items": reviews,
        "carried_review_items": carried,
        "schema_version": meta.get("schema_version"),
        "last_ingest": {
            "run_id": last[0],
            "finished_at": str(last[1]),
            "base_url": last[2],
            "pages_fetched": last[3],
            "skus_found": last[4],
            "tier_docs_found": last[5],
        }
        if last
        else None,
        # Age is reported beside the counts because a stale catalog and a fresh
        # one are otherwise indistinguishable here — the exact condition a
        # correct engine cannot detect for itself.
        "freshness": staleness(built_at),
    }


def load_products(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Every product, as plain dicts. Used by search and by the eval harness.

    DuckDB has no ``row_factory``, so the column names are read from the
    cursor's ``description`` and zipped onto each row.
    """
    with open_readonly(db_path) as con:
        cursor = con.execute("SELECT * FROM products ORDER BY sku")
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load_price_facts(db_path: Path | None = None) -> dict[str, Any]:
    """Build ``PriceFacts`` per SKU from the stored rows.

    Imported lazily so this module does not depend on the pricing module at
    import time, keeping the store usable on its own.
    """
    from .money import Money
    from .pricing import PriceFacts, PriceTier

    with open_readonly(db_path) as con:
        product_rows = con.execute(
            "SELECT sku, list_price_satang, sale_price_satang FROM products"
        ).fetchall()
        tier_rows = con.execute(
            "SELECT sku, min_qty, unit_price_satang FROM price_tiers "
            "ORDER BY sku, min_qty"
        ).fetchall()

    tiers: dict[str, list[PriceTier]] = {}
    for sku, min_qty, price in tier_rows:
        tiers.setdefault(sku, []).append(PriceTier(min_qty, Money(price)))

    facts: dict[str, PriceFacts] = {}
    for sku, list_satang, sale_satang in product_rows:
        facts[sku] = PriceFacts(
            sku=sku,
            list_price=Money(list_satang),
            tiers=tuple(tiers.get(sku, ())),
            sale_price=Money(sale_satang) if sale_satang is not None else None,
        )
    return facts


# ---------------------------------------------------------------------------
# Writing (ingest only)
# ---------------------------------------------------------------------------


def _require_int_satang(value: Any, *, field: str) -> int:
    """Reject anything that is not an exact integer satang amount."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{field} must be integer satang, got {type(value).__name__}; "
            "convert with to_satang() at the boundary"
        )
    return value


def build_snapshot(
    *,
    products: Sequence[dict[str, Any]],
    tiers: Sequence[TierRow],
    reviews: Sequence[dict[str, Any]],
    base_url: str,
    pages_fetched: int,
    tier_docs_found: int,
    target: Path | None = None,
    carry_reviews_from: Path | None = None,
    crawl_started_at: datetime | None = None,
) -> Path:
    """Write a complete snapshot to ``target`` (default: a staging file).

    Every row must already carry integer satang and its provenance. Anything
    else raises here, before the swap, so a malformed row can never reach the
    serving catalog.

    ``carry_reviews_from`` names the previously serving snapshot. Its unresolved
    review items are re-inserted unless this run reports them again, so a flagged
    item stays flagged until someone confirms it is fixed. Without this, every
    rebuild silently drops the backlog and the review set is always empty — which
    looks like a clean run and is not.

    ``crawl_started_at`` is when the crawl began, so the ``ingest_runs`` row spans
    the whole ingest rather than only the database build. When it is omitted the
    build stamps its own start, which keeps direct callers working — but a real
    ingest should pass it, because a snapshot whose timing measures only the build
    reports a duration no crawl could have achieved.
    """
    target = Path(target) if target is not None else _staging_path()
    if target.exists():
        target.unlink()

    carried = _unresolved_reviews(carry_reviews_from) if carry_reviews_from else []
    reported = {_review_key(r) for r in reviews}
    outstanding = [r for r in carried if _review_key(r) not in reported]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    started = crawl_started_at or datetime.now(timezone.utc)

    con = duckdb.connect(str(target))
    try:
        con.execute(SCHEMA_SQL)
        con.execute(INDEX_SQL)
        for product in products:
            con.execute(
                """
                INSERT INTO products (
                    sku, name, brand, category, size_code, width_mm, height_mm,
                    weight_gsm, weight_raw, weight_form, colour_name, colour_mode,
                    sides, finish, pack_sheets, unit_word, list_price_satang,
                    sale_price_satang, on_sale, has_volume_pricing, stock_status,
                    back_in_stock_date, description, source_url, source_shape,
                    crawled_at, raw_labels
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    product["sku"],
                    product["name"],
                    product.get("brand"),
                    product.get("category"),
                    product.get("size_code"),
                    product.get("width_mm"),
                    product.get("height_mm"),
                    product.get("weight_gsm"),
                    product.get("weight_raw"),
                    product.get("weight_form"),
                    product.get("colour_name"),
                    product.get("colour_mode"),
                    product.get("sides"),
                    product.get("finish"),
                    product.get("pack_sheets"),
                    product.get("unit_word"),
                    _require_int_satang(product["list_price_satang"], field="list_price_satang"),
                    None
                    if product.get("sale_price_satang") is None
                    else _require_int_satang(
                        product["sale_price_satang"], field="sale_price_satang"
                    ),
                    product.get("sale_price_satang") is not None,
                    bool(product.get("has_volume_pricing")),
                    product.get("stock_status", "in_stock"),
                    product.get("back_in_stock_date"),
                    product.get("description"),
                    product["source_url"],
                    product["source_shape"],
                    stored_timestamp(product["crawled_at"]),
                    json.dumps(product.get("raw_labels") or {}, ensure_ascii=False),
                ],
            )

        for tier in tiers:
            con.execute(
                "INSERT INTO price_tiers (sku, min_qty, unit_price_satang, "
                "source_url, crawled_at) VALUES (?,?,?,?,?)",
                [
                    tier.sku,
                    tier.min_qty,
                    _require_int_satang(tier.unit_price_satang, field="tier price"),
                    tier.source_url,
                    stored_timestamp(tier.crawled_at),
                ],
            )

        for review in reviews:
            con.execute(
                "INSERT INTO review_items (run_id, kind, url, sku, reason, "
                "raw_excerpt, resolved, carried_from) VALUES (?,?,?,?,?,?,?,?)",
                [
                    run_id,
                    review.get("kind", "extraction"),
                    review["url"],
                    review.get("sku"),
                    review["reason"],
                    review.get("raw_excerpt"),
                    False,
                    None,
                ],
            )

        for review in outstanding:
            con.execute(
                "INSERT INTO review_items (run_id, kind, url, sku, reason, "
                "raw_excerpt, resolved, carried_from) VALUES (?,?,?,?,?,?,?,?)",
                [
                    run_id,
                    review["kind"],
                    review["url"],
                    review.get("sku"),
                    review["reason"],
                    review.get("raw_excerpt"),
                    False,
                    review.get("carried_from") or review["run_id"],
                ],
            )

        finished = datetime.now(timezone.utc)
        con.execute(
            "INSERT INTO ingest_runs (run_id, started_at, finished_at, base_url, "
            "pages_fetched, skus_found, tier_docs_found, status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [run_id, stored_timestamp(started), stored_timestamp(finished),
             base_url, pages_fetched,
             len(products), tier_docs_found, "ok"],
        )
        for key, value in (
            ("schema_version", str(SCHEMA_VERSION)),
            ("built_at", finished.isoformat()),
            ("base_url", base_url),
        ):
            con.execute("INSERT INTO meta (key, value) VALUES (?, ?)", [key, value])

        con.execute("CHECKPOINT")
    except BaseException:
        # A failed build must not leave a half-written file behind. `diff` reads
        # the staging path, and a truncated catalog there would be reported as
        # "the new snapshot" — a silently corrupt comparison.
        con.close()
        for leftover in (target, Path(str(target) + ".wal")):
            try:
                leftover.unlink()
            except OSError:
                pass
        raise
    else:
        con.close()

    _checkpoint_clean(target)
    return target


def _review_key(review: dict[str, Any]) -> tuple[str, str, str]:
    """Identify a review item across runs.

    The key is (kind, url, sku) rather than the reason text: a reason often
    carries a measured value ("card claims 'in_stock' but the page claims
    'out_of_stock'"), and the same underlying problem can be reworded. Keying on
    the reason would re-report a known item every run and never recognise it as
    the same one.
    """
    return (
        str(review.get("kind") or ""),
        str(review.get("url") or ""),
        str(review.get("sku") or ""),
    )


def _unresolved_reviews(db_path: Path | None) -> list[dict[str, Any]]:
    """Read the unresolved review items out of a previously serving snapshot.

    Returns an empty list rather than raising when the file is absent or
    unreadable: a missing previous snapshot means there is no backlog to carry,
    not that this ingest should fail.
    """
    if db_path is None:
        return []
    path = Path(db_path)
    if not path.exists():
        return []

    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception:  # noqa: BLE001 - a locked/corrupt old file is not fatal
        return []

    try:
        rows = con.execute(
            "SELECT run_id, kind, url, sku, reason, raw_excerpt, carried_from "
            "FROM review_items WHERE resolved = FALSE"
        ).fetchall()
    except Exception:  # noqa: BLE001 - older schema without carried_from
        try:
            rows = con.execute(
                "SELECT run_id, kind, url, sku, reason, raw_excerpt, NULL "
                "FROM review_items WHERE resolved = FALSE"
            ).fetchall()
        except Exception:  # noqa: BLE001
            rows = []
    finally:
        con.close()

    return [
        {
            "run_id": row[0], "kind": row[1], "url": row[2], "sku": row[3],
            "reason": row[4], "raw_excerpt": row[5], "carried_from": row[6],
        }
        for row in rows
    ]


def _staging_path(db_path: Path | None = None) -> Path:
    return resolve_db_path(db_path).with_suffix(".tmp.duckdb")


def _checkpoint_clean(path: Path) -> None:
    """Remove the WAL so the file is a single self-contained artefact.

    DuckDB writes a ``.wal`` beside the database. Leaving it behind would make
    the committed snapshot incomplete, so it is checkpointed and then removed.
    """
    wal = Path(str(path) + ".wal")
    if wal.exists():
        wal.unlink()


def swap_into_place(staged: Path, db_path: Path | None = None) -> Path:
    """Atomically replace the serving snapshot with a completed build.

    ``os.replace`` is atomic on the same filesystem, so a reader either sees the
    whole old file or the whole new one — never a half-written catalog.

    The outgoing snapshot is kept as ``<name>.previous.duckdb``. Without it there
    is nothing to diff against after a refresh: the staging file is consumed by
    the swap, so ``run.sh diff`` would always answer "no new snapshot to
    compare", which is useless precisely when someone wants to know what changed.
    """
    target = resolve_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        previous = previous_path(target)
        try:
            os.replace(target, previous)
        except OSError:
            # A missing baseline is not a reason to fail a good refresh.
            pass

    os.replace(staged, target)
    return target


def previous_path(db_path: Path | None = None) -> Path:
    """Where the snapshot displaced by the last refresh is kept."""
    return resolve_db_path(db_path).with_suffix(".previous.duckdb")


# ---------------------------------------------------------------------------
# Diff between two snapshots (capability: catalog-refresh)
# ---------------------------------------------------------------------------


def diff_snapshots(
    old_path: Path | None = None, new_path: Path | None = None
) -> dict[str, Any]:
    """Compare the previous snapshot against the serving one.

    Defaults are *previous* vs *current*, which is what someone asking "what
    changed in the last refresh?" means. ``swap_into_place`` keeps the displaced
    file as ``<name>.previous.duckdb`` for exactly this.

    Returns a dict with one list per change kind. When there is no baseline the
    result says so explicitly rather than reporting an empty diff, because
    "nothing changed" and "nothing to compare against" are different answers and
    only one of them is reassuring.
    """
    old = Path(old_path) if old_path is not None else previous_path()
    new = Path(new_path) if new_path is not None else resolve_db_path()

    if not old.exists():
        return {
            "comparable": False,
            "reason": (
                "no previous snapshot to compare against: this is the first "
                "refresh, or the baseline was removed"
            ),
            "added": [],
            "withdrawn": [],
            "price_changed": [],
            "availability_changed": [],
            "tier_changed": [],
            "parse_failed": [],
        }
    if not new.exists():
        return {
            "comparable": False,
            "reason": "no current snapshot to compare; build one with ./run.sh ingest",
            "added": [],
            "withdrawn": [],
            "price_changed": [],
            "availability_changed": [],
            "tier_changed": [],
            "parse_failed": [],
        }

    def snapshot(path: Path) -> tuple[dict[str, tuple], dict[str, list[tuple]]]:
        con = duckdb.connect(str(path), read_only=True)
        try:
            rows = con.execute(
                "SELECT sku, list_price_satang, sale_price_satang, stock_status "
                "FROM products"
            ).fetchall()
            tiers = con.execute(
                "SELECT sku, min_qty, unit_price_satang FROM price_tiers"
            ).fetchall()
        finally:
            con.close()
        by_sku = {r[0]: r for r in rows}
        tiers_by_sku: dict[str, list[tuple]] = {}
        for sku, min_qty, price in tiers:
            tiers_by_sku.setdefault(sku, []).append((min_qty, price))
        for value in tiers_by_sku.values():
            value.sort()
        return by_sku, tiers_by_sku

    old_products, old_tiers = snapshot(old)
    new_products, new_tiers = snapshot(new)

    added = sorted(set(new_products) - set(old_products))
    withdrawn = sorted(set(old_products) - set(new_products))

    price_changed = []
    availability_changed = []
    tier_changed = []
    for sku in sorted(set(old_products) & set(new_products)):
        _, old_list, old_sale, old_stock = old_products[sku]
        _, new_list, new_sale, new_stock = new_products[sku]
        if (old_list, old_sale) != (new_list, new_sale):
            price_changed.append({
                "sku": sku,
                "list_before": old_list,
                "list_after": new_list,
                "sale_before": old_sale,
                "sale_after": new_sale,
            })
        if old_stock != new_stock:
            availability_changed.append({
                "sku": sku, "before": old_stock, "after": new_stock,
            })
        if old_tiers.get(sku, []) != new_tiers.get(sku, []):
            tier_changed.append({
                "sku": sku,
                "before": old_tiers.get(sku, []),
                "after": new_tiers.get(sku, []),
            })

    con = duckdb.connect(str(new), read_only=True)
    try:
        parse_failed = con.execute(
            "SELECT url, reason FROM review_items WHERE resolved = FALSE"
        ).fetchall()
    finally:
        con.close()

    total = (
        len(added) + len(withdrawn) + len(price_changed)
        + len(availability_changed) + len(tier_changed)
    )
    return {
        "comparable": True,
        "no_change": total == 0,
        "old": str(old),
        "new": str(new),
        "added": added,
        "withdrawn": withdrawn,
        "price_changed": price_changed,
        "availability_changed": availability_changed,
        "tier_changed": tier_changed,
        "parse_failed": [{"url": u, "reason": r} for u, r in parse_failed],
    }


def run_diff() -> int:
    """CLI entry point for ``./run.sh diff``."""
    result = diff_snapshots()
    print(json.dumps(result, indent=2, default=str))
    if not result["comparable"]:
        print(f"\n{result['reason']}", flush=True)
        return 0
    if result["no_change"]:
        print("\nNo change: the refreshed snapshot matches the previous one.")
    return 0
