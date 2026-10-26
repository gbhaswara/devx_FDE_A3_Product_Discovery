"""CLI wrapper for ``./run.sh verify-refresh``.

Kept apart from :mod:`paperlane.refresh` so the harness itself has no printing
and no exit codes — it returns data, and this decides how to render it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .refresh import WORK_DIRNAME, cleanup, run_refresh

#: The project directory (the one holding ``src/`` and ``paperlane/``).
PROJECT_DIR = Path(__file__).resolve().parents[2]


def run_verify_refresh(
    *,
    drop_entry: str | None = None,
    rate: float = 2.0,
    keep: bool = False,
) -> int:
    """Run the refresh verification. Returns a process code.

    Exit codes are distinct so a caller can tell the failures apart:
    ``0`` verified, ``1`` a discrepancy was found, ``2`` the run could not be
    performed at all (ingest failed, unknown ``--drop-entry``).
    """
    try:
        result = run_refresh(
            PROJECT_DIR, rate=rate, drop_entry=drop_entry, keep=keep
        )
    except SystemExit as exc:
        print(exc)
        return 2

    if result.ingest_code != 0:
        print(f"ingest of the mutated site failed (exit {result.ingest_code})")
        return 2

    print("injected changes (from the manifest):")
    for change in result.manifest.changes:
        print(f"  {change.kind:<22} {change.sku}")
    print()

    print("refresh report (from the diff):")
    for kind in ("added", "withdrawn", "price_changed", "availability_changed",
                 "tier_changed", "parse_failed"):
        entries = result.report.get(kind, [])
        print(f"  {kind:<22} {len(entries)}")
    print()

    verdict = result.verify()
    print(verdict.report())

    if keep:
        print(f"\nmutated site: {result.site}")
        print(f"snapshot:     {result.snapshot}")
    else:
        cleanup(PROJECT_DIR)
        print(f"\n({WORK_DIRNAME}/ removed; pass --keep to inspect the site and snapshot)")

    if verdict.ok:
        return 0

    print("\n--- report as JSON ---")
    print(json.dumps(result.report, indent=2, default=str))
    return 1
