"""Shared test paths.

Only path constants live here. Anything that touches the network belongs in a
test that declares it needs a server, because the suite must also pass under a
bare ``unshare -rn``, where loopback starts down.
"""

from __future__ import annotations

import os

#: The repository's project directory (the one holding ``src/``, ``tests/``).
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The committed, read-only catalog site the crawler reads.
SITE_DIR = os.path.join(PROJECT_DIR, "paperlane")

#: The committed snapshot.
DB_PATH = os.path.join(PROJECT_DIR, "data", "catalog.duckdb")


import pytest


def loopback_available() -> bool:
    """Whether 127.0.0.1 can be bound and reached.

    The suite must also pass under a bare ``unshare -rn``, where the network
    namespace starts with only a down loopback: binding succeeds but
    ``connect()`` fails ENETUNREACH. ``./run.sh test-offline`` brings ``lo`` up
    inside the namespace, so the tests marked :data:`needs_loopback` run there;
    a bare namespace skips them rather than failing.
    """
    import socket

    try:
        with socket.socket() as server_sock:
            server_sock.bind(("127.0.0.1", 0))
            server_sock.listen(1)
            port = server_sock.getsockname()[1]
            with socket.socket() as client:
                client.settimeout(1)
                return client.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


#: Skip marker for tests that need a reachable loopback interface.
needs_loopback = pytest.mark.skipif(
    not loopback_available(),
    reason="loopback is unreachable (no local interface); ./run.sh test-offline runs these",
)


@pytest.fixture(autouse=True)
def isolated_record_path(tmp_path, monkeypatch):
    """Point request recording at a per-test temporary file.

    Without this the suite writes real records into ``data/requests.jsonl``: the
    tests would pollute the operational log, and — worse — the metrics tests
    would then be measuring a mixture of their own fixtures and whatever earlier
    tests happened to leave behind. That is a test that passes for the wrong
    reason, so isolation is autouse rather than opt-in.

    Recording stays *enabled*: disabling it would mean the code path under test
    is never exercised.
    """
    monkeypatch.setenv("PAPERLANE_RECORD_PATH", str(tmp_path / "requests.jsonl"))
    # The harness's log is a separate file, so it needs isolating separately.
    # Without this, a test that runs the eval would append to the real
    # ``data/eval-records.jsonl`` and the metrics tests would then be reading
    # records from someone else's run.
    monkeypatch.setenv(
        "PAPERLANE_EVAL_RECORD_PATH", str(tmp_path / "eval-records.jsonl")
    )
    monkeypatch.delenv("PAPERLANE_RECORD_TEXT", raising=False)
    monkeypatch.delenv("PAPERLANE_RECORD_TEXT_MAX", raising=False)
    monkeypatch.delenv("PAPERLANE_RECORD_WINDOW", raising=False)
    return tmp_path / "requests.jsonl"


@pytest.fixture(scope="session")
def snapshot_products():
    """The committed catalog's products, loaded once.

    Read-only and offline: it opens the snapshot that is committed to the
    repository, so tests using it need no server and no crawl.
    """
    from paperlane.catalog import load_products

    return load_products()


def embedding_provider_reachable() -> bool:
    """Whether a configured embedding provider answers right now.

    Distinct from :func:`loopback_available`: the provider is optional by
    design, so a machine with a working loopback and no Ollama running must skip
    these tests too, and skip them for a different stated reason.
    """
    from paperlane.embeddings import EmbeddingConfig

    config = EmbeddingConfig.from_env()
    if not config.configured or not loopback_available():
        return False
    import httpx

    try:
        response = httpx.post(
            f"{config.base_url}/api/embed",
            json={"model": config.model, "input": ["probe"]},
            timeout=config.timeout,
        )
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False
    return response.status_code == 200


#: Skip marker for tests that need a live embedding provider. The feature is
#: optional, so these must skip rather than fail wherever it is absent — a
#: skip is reported in the summary, not counted as a pass.
needs_embedding = pytest.mark.skipif(
    not embedding_provider_reachable(),
    reason=(
        "no embedding provider reachable; set PAPERLANE_EMBED_BASE_URL and "
        "PAPERLANE_EMBED_MODEL to run the provider-dependent tests"
    ),
)
