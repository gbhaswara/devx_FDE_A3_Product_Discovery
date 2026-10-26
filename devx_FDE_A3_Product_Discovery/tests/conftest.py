"""Shared test paths.

Only path constants live here. Anything that touches the network belongs in a
test that declares it needs a server, because the suite must run under
``unshare -rn`` where loopback is down.
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

    The suite must pass under ``unshare -rn``, where the network namespace has
    only a down loopback: binding succeeds but ``connect()`` fails ENETUNREACH.
    Tests that need a local HTTP server are skipped there rather than failing,
    because the behaviour they cover is exercised by ``./run.sh verify-refresh``.
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
    reason="loopback is unreachable (offline run); covered by ./run.sh verify-refresh",
)


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
