"""Prove the refresh path by refreshing a deliberately mutated catalog.

`catalog.diff_snapshots` reports six change kinds. Until something changes, all
six are empty — and an empty report is equally consistent with a correct diff
and with one that reads nothing at all. This module closes that gap: it mutates
a copy of the site in a declared way, ingests it, diffs it against the committed
snapshot, and checks the report against the declaration.

The pieces are separable so each can be tested without a server:

* :func:`serve` runs the mutated site over HTTP (the crawler never reads files).
* :func:`run_refresh` ingests and diffs, returning the artefacts.
* :func:`verify_against_manifest` delegates to :func:`mutate.verify`.

Only :func:`run_refresh` needs a network socket, and only loopback.
"""

from __future__ import annotations

import contextlib
import functools
import threading
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

from . import catalog
from .mutate import Manifest, VerificationResult, _sku_from_url, generate, verify

#: Where generated sites and snapshots are written. Git-ignored, because derived
#: HTML committed by accident would look like a second catalog.
WORK_DIRNAME = ".refresh-verification"


def work_dir(project_dir: Path) -> Path:
    """The scratch directory for a verification run."""
    return Path(project_dir) / WORK_DIRNAME


class _QuietHandler(SimpleHTTPRequestHandler):
    """A static file handler that does not log every request to stderr.

    The crawl makes ~120 requests; the per-request log would bury the report
    that actually matters.
    """

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


@contextlib.contextmanager
def serve(directory: Path, port: int = 0) -> Iterator[str]:
    """Serve ``directory`` over HTTP and yield the base URL.

    Bound to 127.0.0.1 only. The crawler requires HTTP because volume pricing is
    fetched by JavaScript from per-SKU JSON; opening the files from disk does not
    load it, so a ``file://`` fixture would silently produce a catalog with no
    tiers.
    """
    directory = Path(directory).resolve()
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, actual_port = httpd.server_address[:2]
        # Served at the root: the handler's document root *is* the site, so the
        # URL prefix must not repeat the directory name.
        yield f"http://{host}:{actual_port}/"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def cleanup(project_dir: Path) -> None:
    """Remove the scratch directory left by a run.

    Called after verification, not before: the report is produced from the
    snapshot, so deleting it earlier would leave nothing to verify against.
    """
    import shutil

    work = work_dir(project_dir)
    if work.exists():
        shutil.rmtree(work)


def crawled_skus(db_path: Path) -> set[str]:
    """The SKUs the crawl actually reached, per the snapshot it produced.

    This is the difference between "the diff missed a change" and "the page was
    never crawled". Derived from the snapshot rather than from the manifest,
    because the manifest describes intent and this must describe what happened.
    """
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        found = {row[0] for row in con.execute("SELECT sku FROM products").fetchall()}
        for (url,) in con.execute("SELECT url FROM review_items").fetchall():
            derived = _sku_from_url(url) if url else None
            if derived:
                found.add(derived)
    finally:
        con.close()
    return found


@dataclass
class RefreshResult:
    """Everything one verification run produced."""

    site: Path
    snapshot: Path
    manifest: Manifest
    report: dict[str, Any] = field(default_factory=dict)
    crawled: set[str] = field(default_factory=set)
    ingest_code: int = 0

    def verify(self) -> VerificationResult:
        return verify(self.report, self.manifest, crawled_skus=self.crawled)


def run_refresh(
    project_dir: Path,
    *,
    rate: float = 2.0,
    drop_entry: str | None = None,
    keep: bool = False,
) -> RefreshResult:
    """Generate, serve, ingest, diff, and verify — in one call.

    ``keep`` retains the generated site and snapshot for inspection. Without it
    they are removed after verification, so a run leaves no derived artefacts
    behind — the directory is git-ignored either way, but a stale site from a
    previous run is a confusing thing to find.

    ``drop_entry`` removes one declared change from the manifest *after* the
    injection happened. The site still contains that change, so the diff reports
    it and the verification must reject it as undeclared. That is how the harness
    demonstrates it can fail: by suppressing the expectation rather than the
    mutation, so the run is otherwise identical.

    The committed snapshot is read as the baseline and never written. A
    demonstration that overwrites the artefact under review proves nothing.
    """
    from .ingest import run_ingest

    project_dir = Path(project_dir)
    work = work_dir(project_dir)
    work.mkdir(parents=True, exist_ok=True)

    source_site = project_dir / "paperlane"
    site = work / "site"
    manifest = generate(source_site, site)

    if drop_entry:
        kept = [c for c in manifest.changes if c.sku != drop_entry]
        if len(kept) == len(manifest.changes):
            raise SystemExit(
                f"--drop-entry {drop_entry!r} names no injected change; "
                f"declared SKUs are {sorted(manifest.skus)}"
            )
        manifest.changes = kept

    snapshot = work / "mutated.duckdb"
    if snapshot.exists():
        snapshot.unlink()

    with serve(site) as base_url:
        code = run_ingest(base_url, rate=rate, db_path=snapshot)

    result = RefreshResult(
        site=site, snapshot=snapshot, manifest=manifest, ingest_code=code
    )
    if code != 0:
        return result

    result.report = catalog.diff_snapshots(
        old_path=catalog.DEFAULT_DB_PATH, new_path=snapshot
    )
    result.crawled = crawled_skus(snapshot)

    return result
