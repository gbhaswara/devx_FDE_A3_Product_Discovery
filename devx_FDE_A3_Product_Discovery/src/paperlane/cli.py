"""Command line entry point.

Subcommands are thin wrappers; all real work lives in the modules so that the
evaluation harness and the tests can call it directly without a subprocess.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paperlane",
        description="PaperLane product discovery and quoting assistant.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Crawl the catalog into a new snapshot")
    ingest.add_argument(
        "--base-url",
        default="http://localhost:8000/paperlane/",
        help="Base URL of the served PaperLane site (must be HTTP, not a file path)",
    )
    ingest.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="Requests per second (the site permits 2; default 1)",
    )

    serve = sub.add_parser("serve", help="Run the HTTP API")
    serve.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port to listen on (default 8001; 8000 is the served site)",
    )
    serve.add_argument("--host", default="127.0.0.1")

    evaluate = sub.add_parser("eval", help="Run the recorded evaluation cases")
    evaluate.add_argument("--json", action="store_true", help="Machine-readable output")
    evaluate.add_argument(
        "--cases",
        default=None,
        help="Path to a case file (default: eval/cases.json). "
             "Use eval/negative-control.json to see the harness fail.",
    )
    evaluate.add_argument(
        "--self-check",
        action="store_true",
        help="Verify the scoring detects the defects it claims to",
    )

    sub.add_parser("diff", help="Compare the current snapshot with the previous")

    refresh = sub.add_parser(
        "verify-refresh",
        help="Mutate a copy of the site, refresh against it, and verify the diff",
    )
    refresh.add_argument(
        "--rate",
        type=float,
        default=2.0,
        help=(
            "Requests per second. Capped at 2 by the crawler itself, which "
            "enforces the site's published limit regardless of who is serving."
        ),
    )
    refresh.add_argument(
        "--drop-entry",
        default=None,
        metavar="SKU",
        help="Suppress one declared change to prove the verification can fail",
    )
    refresh.add_argument(
        "--keep",
        action="store_true",
        help="Keep the generated site and snapshot after the run",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "ingest":
        from .ingest import run_ingest

        return run_ingest(args.base_url, args.rate)
    if args.command == "serve":
        from .api import run_server

        return run_server(host=args.host, port=args.port)
    if args.command == "eval":
        from pathlib import Path

        from .evaluate import run_eval, self_check

        if args.self_check:
            return self_check()
        return run_eval(
            as_json=args.json,
            cases_path=Path(args.cases) if args.cases else None,
        )
    if args.command == "diff":
        from .catalog import run_diff

        return run_diff()
    if args.command == "verify-refresh":
        from .refresh_cli import run_verify_refresh

        return run_verify_refresh(
            drop_entry=args.drop_entry, rate=args.rate, keep=args.keep
        )

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
