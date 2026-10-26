#!/usr/bin/env bash
# PaperLane dispatcher. Run ./run.sh with no argument to see the subcommands.
set -euo pipefail

cd "$(dirname "$0")"

# Use the project's virtualenv. Bare `python3` cannot work here: the project root
# contains the crawled site under `paperlane/`, which Python picks up as a
# namespace package and which has no `cli` submodule. The venv has the editable
# install, whose regular package takes precedence over that directory.
if [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
elif command -v uv >/dev/null 2>&1; then
    PY="uv run python"
else
    echo "run.sh: no .venv and no uv found; run 'uv sync' first" >&2
    exit 2
fi

usage() {
    cat <<'EOF'
PaperLane product discovery

Usage: ./run.sh <command> [args...]

Commands:
  ingest   Crawl the catalog over HTTP into a new snapshot, then swap it in
  serve    Run the HTTP API and the single page
  ask      Ask one question and print the answer (no server required)
           --conversation ID continues a conversation; --forget discards it
  test     Run unit, extraction and integration tests (offline, no model)
  eval     Run the recorded evaluation cases against a loaded snapshot
  diff     Compare the current snapshot with the previous one
  similarity      Measure the semantic tiebreak against the recorded cases
  metrics  Print the five operational measures derived from request records
  verify-refresh  Mutate a copy of the site, refresh against it, verify the diff

Examples:
  ./run.sh ingest --base-url http://localhost:8000/paperlane/
  ./run.sh serve
  ./run.sh ask "A4 80gsm copy paper, 20 reams"
  ./run.sh ask "make it 50" --conversation demo   # continues the previous turn
  ./run.sh ask --forget --conversation demo       # discards it
  ./run.sh test
  ./run.sh metrics
  ./run.sh metrics --eval      # the most recent evaluation run's records
  PAPERLANE_EMBED_BASE_URL=http://localhost:11434 \
    PAPERLANE_EMBED_MODEL=bge-m3:latest ./run.sh similarity
EOF
}

if [ "$#" -eq 0 ]; then
    usage >&2
    exit 2
fi

cmd="$1"
shift

case "$cmd" in
    ingest) exec $PY -m paperlane.cli ingest "$@" ;;
    serve)  exec $PY -m paperlane.cli serve  "$@" ;;
    ask)    exec $PY -m paperlane.cli ask    "$@" ;;
    test)   exec $PY -m pytest tests -q "$@" ;;
    eval)   exec $PY -m paperlane.cli eval   "$@" ;;
    diff)   exec $PY -m paperlane.cli diff   "$@" ;;
    similarity) exec $PY -m paperlane.cli similarity "$@" ;;
    metrics) exec $PY -m paperlane.cli metrics "$@" ;;
    verify-refresh) exec $PY -m paperlane.cli verify-refresh "$@" ;;
    -h|--help|help) usage; exit 0 ;;
    *)
        echo "run.sh: unknown command '$cmd'" >&2
        echo >&2
        usage >&2
        exit 2
        ;;
esac
