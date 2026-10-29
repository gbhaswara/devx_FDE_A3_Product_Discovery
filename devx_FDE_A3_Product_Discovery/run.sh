#!/usr/bin/env bash
# PaperLane dispatcher. Run ./run.sh with no argument to see the subcommands.
set -euo pipefail

cd "$(dirname "$0")"

# Local configuration, if present. `.env` is git-ignored and holds the model
# endpoint and key, so it is never committed. The test commands deliberately do
# not read it: `./run.sh test-offline` is the run that proves the suite works
# with no model and no embedding server, and a .env would quietly break that.
case "${1:-}" in
    test|test-offline) ;;
    *) if [ -f .env ]; then set -a; . ./.env; set +a; fi ;;
esac

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
  ingest          Crawl the catalog over HTTP into a new snapshot, then swap it in
  serve           Run the HTTP API and the single page
  ask             Ask one question and print the answer (no server required)
                  --conversation ID continues a conversation; --forget discards it
  test            Run the suite (no model needed; an embedding provider is optional)
  test-offline    Run the suite with no external network, loopback up
  eval            Run the recorded evaluation cases against a loaded snapshot
                  --catalog v2 scores the mutated catalog (see verify-refresh --keep)
  diff            Compare the current snapshot with the previous one
  similarity      Measure the semantic tiebreak against the recorded cases
  metrics         Print the five operational measures derived from request records
  verify-refresh  Mutate a copy of the site, refresh against it, verify the diff

Examples:
  ./run.sh ingest --base-url http://localhost:8000/paperlane/
  ./run.sh serve
  ./run.sh ask "A4 80gsm copy paper, 20 reams"
  ./run.sh ask "make it 50" --conversation demo   # continues the previous turn
  ./run.sh ask --forget --conversation demo       # discards it
  ./run.sh test
  ./run.sh test-offline
  ./run.sh eval --catalog v2 --db .refresh-verification/mutated.duckdb
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
    # No extra -q: pyproject already supplies one, and a second suppresses the
    # "N passed, M skipped" line — the line that shows what did not run.
    test)   exec $PY -m pytest tests "$@" ;;
    test-offline)
        # The offline guarantee is a fresh network namespace: it has no route to
        # anything outside itself, so a call to the internet fails. Its loopback
        # starts down, which made the local-server tests skip; bringing `lo` up
        # keeps the guarantee and lets those tests run instead of being covered
        # only by ./run.sh verify-refresh.
        command -v unshare >/dev/null 2>&1 || {
            echo "run.sh: unshare not found; test-offline needs Linux user namespaces" >&2
            exit 2
        }
        command -v ip >/dev/null 2>&1 || {
            echo "run.sh: ip not found; test-offline needs iproute2 to bring lo up" >&2
            exit 2
        }
        # No extra -q: pyproject already supplies one, and a second would
        # suppress the "N passed, M skipped" line this command exists to print.
        exec unshare -rn bash -c 'ip link set lo up && exec "$@"' _ \
            $PY -m pytest tests "$@" ;;
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
