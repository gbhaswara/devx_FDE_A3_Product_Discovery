"""Command line entry point.

Subcommands are thin wrappers; all real work lives in the modules so that the
evaluation harness and the tests can call it directly without a subprocess.
"""

from __future__ import annotations

import argparse
import json
import sys


def _is_conversation_file(path) -> bool:
    """Is this case file a conversation set rather than a request set?

    Decided by the file's own shape, not by a flag or a filename: one command
    (``./run.sh eval --cases <file>``) should run whichever harness the file is
    written for. A separate flag would mean a conversation file passed without
    it silently scores as a request file and reports nonsense — a failure mode
    that is invisible in the output.

    Anything unreadable or unrecognised is treated as a request set, so the
    error a caller sees comes from the real loader rather than from here.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(raw, dict) and "conversations" in raw and "cases" not in raw


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
    ingest.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help=(
            "Snapshot to build (default: PAPERLANE_DB, else data/catalog.duckdb). "
            "Point an unseen-site re-ingest here so the committed catalog — the "
            "one the recorded expectations are written against — is not overwritten."
        ),
    )

    serve = sub.add_parser("serve", help="Run the HTTP API")
    serve.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port to listen on (default 8001; 8000 is the served site)",
    )
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Snapshot to serve (default: PAPERLANE_DB, else data/catalog.duckdb)",
    )

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
    evaluate.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Snapshot to score against (default: PAPERLANE_DB, else the committed one)",
    )
    evaluate.add_argument(
        "--catalog",
        choices=("v1", "v2"),
        default="v1",
        help="Which catalog the case expectations are written for. "
             "The default is the committed snapshot; v2 is the mutated one "
             "`verify-refresh --keep` builds.",
    )

    sub.add_parser("diff", help="Compare the current snapshot with the previous")

    ask = sub.add_parser(
        "ask",
        help="Ask one question and print the answer (no server required)",
    )
    ask.add_argument(
        "request",
        nargs="?",
        default="",
        help=(
            "The customer's sentence, e.g. \"A4 80gsm copy paper, 20 reams\". "
            "Omit only with --forget."
        ),
    )
    ask.add_argument(
        "--quantity",
        type=int,
        default=None,
        help="Override the quantity the request implies",
    )
    ask.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable output, the same shape as POST /api/ask",
    )
    ask.add_argument(
        "--verbose",
        action="store_true",
        help="Also print how the request was interpreted",
    )
    ask.add_argument(
        "--no-model",
        action="store_true",
        help="Use the rule interpreter only, even when a model is configured",
    )
    ask.add_argument(
        "--conversation",
        metavar="ID",
        default=None,
        help=(
            "Continue a conversation across invocations. The id is a label, "
            "not an authenticated session. Kept in data/conversations.jsonl."
        ),
    )
    ask.add_argument(
        "--forget",
        action="store_true",
        help="Discard the conversation named by --conversation, then exit",
    )
    ask.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Snapshot to read (default: PAPERLANE_DB, else the committed one)",
    )

    similarity = sub.add_parser(
        "similarity",
        help="Measure the semantic tiebreak against the recorded cases",
    )
    similarity.add_argument(
        "--json", action="store_true", help="Machine-readable output"
    )
    similarity.add_argument(
        "--cases",
        default=None,
        help="Path to a case file (default: eval/cases.json)",
    )

    metrics = sub.add_parser(
        "metrics",
        help="Print the five operational measures derived from request records",
    )
    metrics.add_argument(
        "--json", action="store_true", help="Machine-readable output"
    )
    metrics.add_argument(
        "--records",
        default=None,
        help="Record file to read (default: the configured PAPERLANE_RECORD_PATH)",
    )
    metrics.add_argument(
        "--eval",
        action="store_true",
        help="Report over the evaluation harness's records instead of live traffic",
    )
    metrics.add_argument(
        "--run",
        default=None,
        help="With --eval: the run id to report (default: the most recent run)",
    )
    metrics.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help="Snapshot to describe (default: PAPERLANE_DB, else the committed one)",
    )

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

        return run_ingest(args.base_url, args.rate, db_path=args.db)
    if args.command == "serve":
        from .api import run_server

        return run_server(host=args.host, port=args.port, db_path=args.db)
    if args.command == "eval":
        from pathlib import Path

        from .evaluate import run_eval, self_check

        if args.self_check:
            return self_check()

        cases_path = Path(args.cases) if args.cases else None
        if cases_path is not None and _is_conversation_file(cases_path):
            from .conversation_eval import run_conversation_eval

            # The conversation cases were authored against v1 and carry no
            # per-catalog expectation. Refusing is better than running them
            # under a label that would be wrong: an ignored flag looks like it
            # was applied.
            if args.catalog != "v1":
                print(
                    f"{cases_path} is a conversation set, and its expectations "
                    f"are written for v1; --catalog {args.catalog} cannot be "
                    f"applied to it.",
                    file=sys.stderr,
                )
                return 2
            return run_conversation_eval(
                as_json=args.json, cases_path=cases_path, db_path=args.db
            )
        from . import catalog

        # v2 expectations describe the mutated catalog. Pairing them with the
        # committed snapshot is a mislabel, not a result. The reverse (v1
        # expectations against a newer snapshot) stays allowed: that compares
        # what changed against the recorded set.
        if args.catalog == "v2" and (
            Path(catalog.resolve_db_path(args.db)).resolve()
            == Path(catalog.DEFAULT_DB_PATH).resolve()
        ):
            print(
                "--catalog v2 scores expectations written for the mutated "
                "catalog, but the snapshot is the committed v1 one. Build it "
                "with `./run.sh verify-refresh --keep` and pass "
                "`--db .refresh-verification/mutated.duckdb`.",
                file=sys.stderr,
            )
            return 2
        return run_eval(
            as_json=args.json,
            cases_path=cases_path,
            db_path=args.db,
            catalog_name=args.catalog,
        )
    if args.command == "diff":
        from .catalog import run_diff

        return run_diff()
    if args.command == "ask":
        from .ask_cli import run_ask

        return run_ask(
            args.request,
            quantity=args.quantity,
            use_model=not args.no_model,
            as_json=args.json,
            verbose=args.verbose,
            conversation_id=args.conversation,
            forget=args.forget,
            db_path=args.db,
        )
    if args.command == "similarity":
        from pathlib import Path

        from .similarity import run_measure

        return run_measure(
            as_json=args.json,
            cases_path=Path(args.cases) if args.cases else None,
        )
    if args.command == "metrics":
        from pathlib import Path

        from . import records
        from .metrics import run_metrics

        writer = records.RecordWriter(Path(args.records)) if args.records else None
        return run_metrics(
            as_json=args.json, writer=writer,
            source="eval" if args.eval else "live",
            run_id=args.run,
            db_path=args.db,
        )
    if args.command == "verify-refresh":
        from .refresh_cli import run_verify_refresh

        return run_verify_refresh(
            drop_entry=args.drop_entry, rate=args.rate, keep=args.keep
        )

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
