"""Optional semantic similarity, over a local embedding server.

This module is **optional by construction**, and that is the load-bearing
property rather than a convenience. The test suite runs under ``unshare -rn``,
where loopback is DOWN and ``connect()`` to ``127.0.0.1`` fails ``ENETUNREACH``.
An embedding call on the default path would therefore break the guarantee that
the suite verifies correctness with no network and no model.

So: no provider configured means :func:`scorer_for` returns ``None``, and the
caller omits the similarity term from the sort key *entirely*. It does not
insert a constant. A constant ``0.0`` would be equivalent in ordering but not
identical in effect — it would still occupy a position in the tuple, so a later
edit that made the term non-constant would silently change the unconfigured
path too. Omitting it keeps that path provably identical to the pre-semantic
one.

Three measured facts shape the receipt checks, all verified against
``bge-m3:latest`` on Ollama 0.34.4 rather than assumed:

1. **Vectors are L2-normalised, but only to float32 precision.** Across 72
   products the norm ranged 0.99999935 to 1.00000057 — a maximum deviation of
   6.5e-7 from 1.0. Cosine similarity is therefore a plain dot product, and the
   normalisation check has to allow float tolerance. Demanding ``norm == 1.0``
   would reject every real response.
2. **Responses are deterministic.** Two identical calls returned bit-identical
   vectors (max difference 0.0), which is what lets the ordering be total.
3. **One call embeds the whole catalog.** 72 products in 944ms, so the cost is
   paid once per snapshot rather than once per request.

No credential is read and none is sent: the endpoint is local, so the client
adds no ``Authorization`` header at all. There is no API-key setting to leak.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: An embedding call is a local matrix multiply, not a generation, so the
#: timeout is short by generation standards — but it is **not** 2s, which is what
#: the design originally proposed. Measured on this machine: a *cold* model load
#: costs 2.0s for one text and 2.8s for all 72, while warm calls cost 0.02s and
#: 0.64s. A 2s timeout therefore failed the very first request after a restart,
#: every time — the feature would have degraded on first use and looked broken.
#: 10s covers a cold load with headroom and still fails fast on a dead provider.
DEFAULT_TIMEOUT = 10.0

#: How far a vector's L2 norm may sit from 1.0 before the response is rejected.
#: Measured worst case on the real model is 6.5e-7, so 1e-3 is ~1500x the
#: observed error while still catching a provider that returns un-normalised
#: vectors (whose norms run to 10s or 100s).
NORM_TOLERANCE = 1e-3

#: What the ordering reports about whether similarity participated.
SEMANTIC_OFF = "off"                  # no provider configured
SEMANTIC_APPLIED = "applied"          # similarity decided part of the order
SEMANTIC_UNAVAILABLE = "unavailable"  # provider configured but failed; degraded


class EmbeddingUnavailable(RuntimeError):
    """The embedding provider could not be reached, or returned something unusable.

    Messages deliberately carry no request text: this exception can surface in a
    response, and the request may be a customer's own words.
    """


@dataclass(frozen=True)
class EmbeddingConfig:
    """Where the embedding server lives. Environment only, never hard-coded."""

    base_url: str = ""
    model: str = ""
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        return cls(
            base_url=(os.environ.get("PAPERLANE_EMBED_BASE_URL") or "").rstrip("/"),
            model=os.environ.get("PAPERLANE_EMBED_MODEL") or "",
            timeout=float(
                os.environ.get("PAPERLANE_EMBED_TIMEOUT", DEFAULT_TIMEOUT)
            ),
        )

    @property
    def configured(self) -> bool:
        """Both settings are required. Half-configured counts as unconfigured.

        Guessing a default model name would mean scoring against a model the
        operator did not choose, which is worse than not scoring at all.
        """
        return bool(self.base_url and self.model)


# ---------------------------------------------------------------------------
# What gets embedded
# ---------------------------------------------------------------------------


def product_text(product: dict[str, Any]) -> str:
    """The searchable text for one product.

    Built from the fields a customer actually uses to describe paper — name,
    category, finish, grammage, size, and the two colour fields. Colour is
    included beyond the design's original five because a request for "pastel
    blue" or "colour flyers" is discriminated by nothing else, and a text
    without it would score every shade identically.

    Absent fields are skipped rather than rendered, so a product missing an
    attribute cannot produce the literal string ``"None"`` or a double space —
    both of which would be embedded as if they were content.
    """
    weight = product.get("weight_gsm")
    parts = [
        product.get("name"),
        product.get("category"),
        product.get("finish"),
        f"{weight}gsm" if weight is not None else None,
        product.get("size_code"),
        product.get("colour_name"),
        product.get("colour_mode"),
        product.get("sides"),
    ]
    return " ".join(
        str(part).strip() for part in parts
        if part is not None and str(part).strip()
    )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity for L2-normalised vectors, as a plain dot product.

    **This function does not normalise.** Both inputs are already unit length —
    checked on receipt by :class:`EmbeddingClient` — so dividing by the norms
    again would be a second normalisation and would quietly produce the wrong
    number for any vector that is not exactly unit length.
    """
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


def _finite(vector: Sequence[float]) -> bool:
    return all(math.isfinite(value) for value in vector)


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


class EmbeddingClient:
    """A thin client for the local ``/api/embed`` shape.

    Request body is ``{"model": ..., "input": [...]}`` and the response carries
    ``embeddings``: one vector per input, in input order.
    """

    def __init__(self, config: EmbeddingConfig | None = None, *, client=None) -> None:
        self.config = config or EmbeddingConfig.from_env()
        self._client = client
        #: Learned from the first successful call. A later call returning a
        #: different width means the provider changed under us, and comparing
        #: those vectors would silently truncate at the shorter length.
        self._dim: int | None = None

    @property
    def available(self) -> bool:
        return self.config.configured

    @property
    def dimension(self) -> int | None:
        return self._dim

    def _http(self):
        if self._client is not None:
            return self._client
        import httpx

        return httpx.Client(timeout=self.config.timeout)

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """Embed ``texts``, returning one vector each, in order.

        Raises :class:`EmbeddingUnavailable` for every failure — unreachable
        host, non-200, unparseable body, or a vector that fails the receipt
        checks. Callers degrade to the non-semantic ordering rather than
        propagating, so a dead provider never fails a customer's request.
        """
        if not self.available:
            raise EmbeddingUnavailable(
                "no embedding provider configured; set PAPERLANE_EMBED_BASE_URL "
                "and PAPERLANE_EMBED_MODEL"
            )
        texts = list(texts)
        if not texts:
            return []

        body = {"model": self.config.model, "input": texts}
        # No Authorization header: the endpoint is local, so there is no key to
        # send and none is read from the environment.
        client = self._http()
        try:
            response = client.post(
                f"{self.config.base_url}/api/embed",
                json=body,
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:  # noqa: BLE001 - every transport failure degrades
            raise EmbeddingUnavailable(
                f"embedding request failed: {type(exc).__name__}"
            ) from exc
        finally:
            if self._client is None:
                client.close()

        if response.status_code != 200:
            raise EmbeddingUnavailable(
                f"embedding provider returned HTTP {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise EmbeddingUnavailable("embedding response was not JSON") from exc

        raw = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            raise EmbeddingUnavailable(
                "embedding response had no 'embeddings' array"
            )
        if len(raw) != len(texts):
            raise EmbeddingUnavailable(
                f"expected {len(texts)} embeddings, got {len(raw)}"
            )

        vectors = self._validate(raw)
        self._dim = len(vectors[0])
        return vectors

    def _validate(self, raw: Iterable[Any]) -> list[tuple[float, ...]]:
        """Reject malformed vectors instead of scoring with them.

        A mismatched dimension or a ``NaN`` does not raise on its own — it
        produces a number. That number would look like a plausible similarity
        and reorder results for no reason, which is the worst kind of bug to
        find later. So every vector is checked before it can reach the ranker.
        """
        vectors: list[tuple[float, ...]] = []
        width: int | None = None
        for index, vector in enumerate(raw):
            if not isinstance(vector, (list, tuple)) or not vector:
                raise EmbeddingUnavailable(f"embedding {index} is not a vector")
            values = tuple(float(value) for value in vector)
            if not _finite(values):
                raise EmbeddingUnavailable(
                    f"embedding {index} contains a non-finite value"
                )
            if width is None:
                width = len(values)
                if self._dim is not None and width != self._dim:
                    raise EmbeddingUnavailable(
                        f"provider changed dimension: {self._dim} -> {width}"
                    )
            elif len(values) != width:
                raise EmbeddingUnavailable(
                    f"embedding {index} has dimension {len(values)}, expected {width}"
                )
            deviation = abs(_norm(values) - 1.0)
            if deviation > NORM_TOLERANCE:
                raise EmbeddingUnavailable(
                    f"embedding {index} is not unit length (off by {deviation:.4g})"
                )
            vectors.append(values)
        return vectors


# ---------------------------------------------------------------------------
# Per-snapshot cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheKey:
    """What makes one set of product vectors distinguishable from another.

    The build time is the part that matters. Keying on the product count alone
    would keep serving vectors from the previous catalog after a re-ingest that
    added and withdrew the same number of items — a stale cache that scores
    against an old catalog, which produces plausible wrong orderings forever.
    """

    base_url: str
    model: str
    built_at: str
    product_count: int


@dataclass
class EmbeddingCache:
    """Process-local vectors, keyed per snapshot.

    72 products cost 944ms to embed. Doing that per request would make the
    assistant slower than the feature is worth, so it is done once and reused
    until the snapshot or the model changes.
    """

    _vectors: dict[CacheKey, dict[str, tuple[float, ...]]] = field(
        default_factory=dict
    )

    def get(self, key: CacheKey) -> dict[str, tuple[float, ...]] | None:
        return self._vectors.get(key)

    def put(self, key: CacheKey, vectors: dict[str, tuple[float, ...]]) -> None:
        self._vectors[key] = vectors

    def clear(self) -> None:
        self._vectors.clear()

    def __len__(self) -> int:
        return len(self._vectors)


#: The cache the application uses. Tests clear it rather than reaching into it.
CACHE = EmbeddingCache()


def snapshot_fingerprint(db_path=None) -> tuple[str, int]:
    """``(built_at, product count)`` for a snapshot, read from its ``meta``.

    Deliberately cheaper than :func:`paperlane.catalog.health`, which this is
    called beside on every request: two small queries instead of the full
    review-item and tier roll-up.
    """
    from . import catalog

    path = catalog.resolve_db_path(db_path)
    if not catalog.snapshot_exists(path):
        return ("", 0)
    with catalog.open_readonly(path) as con:
        row = con.execute(
            "SELECT value FROM meta WHERE key = 'built_at'"
        ).fetchone()
        count = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    return (str(row[0]) if row else "", int(count))


def product_vectors(
    products: Sequence[dict[str, Any]],
    *,
    key: CacheKey,
    client: EmbeddingClient,
) -> dict[str, tuple[float, ...]]:
    """Vectors for every product, from the cache when possible."""
    cached = CACHE.get(key)
    if cached is not None:
        return cached
    texts = [product_text(product) for product in products]
    vectors = client.embed(texts)
    table = {product["sku"]: vector for product, vector in zip(products, vectors)}
    CACHE.put(key, table)
    return table


# ---------------------------------------------------------------------------
# Scoring one request
# ---------------------------------------------------------------------------


class SemanticScorer:
    """Scores a request against the products of one snapshot.

    Embedding is deferred to the first :meth:`scores` call, so a request that
    matches nothing — or asks a clarifying question — never contacts the
    provider at all. That is what makes the unconfigured path and the
    nothing-to-score path indistinguishable in cost.

    Once a call fails, the failure is sticky for the life of the scorer. The
    alternatives path would otherwise retry the same dead provider and pay the
    timeout twice for the same request.
    """

    def __init__(
        self,
        *,
        request_text: str,
        products: Sequence[dict[str, Any]],
        config: EmbeddingConfig,
        client: EmbeddingClient | None = None,
        key: CacheKey,
    ) -> None:
        self.request_text = request_text
        self._products = list(products)
        self.config = config
        self._client = client or EmbeddingClient(config)
        self._key = key
        self._product_vectors: dict[str, tuple[float, ...]] | None = None
        self._request_vector: tuple[float, ...] | None = None
        self._failed: str | None = None

    @property
    def degraded(self) -> bool:
        return self._failed is not None

    def scores(self, skus: Sequence[str]) -> dict[str, float]:
        """Similarity per SKU, for the SKUs asked about.

        Only ever called with SKUs that already passed every hard constraint.
        That is the structural guarantee that similarity cannot change
        membership: there is no code path that consults it before filtering.
        """
        if self._failed is not None:
            raise EmbeddingUnavailable(self._failed)

        try:
            if self._product_vectors is None:
                self._product_vectors = product_vectors(
                    self._products, key=self._key, client=self._client
                )
            if self._request_vector is None:
                self._request_vector = self._client.embed([self.request_text])[0]
        except EmbeddingUnavailable as exc:
            self._failed = str(exc)
            raise

        return {
            sku: cosine(self._request_vector, self._product_vectors[sku])
            for sku in skus
            if sku in self._product_vectors
        }


def scorer_for(
    request_text: str,
    products: Sequence[dict[str, Any]],
    *,
    db_path=None,
    config: EmbeddingConfig | None = None,
    client: EmbeddingClient | None = None,
) -> SemanticScorer | None:
    """A scorer for this request, or ``None`` when no provider is configured.

    ``None`` is not a degraded state — it is the default one, and the caller
    responds by omitting the similarity term from the ranking entirely.

    An empty request text also yields ``None``: a structured request carries no
    wording to compare against, and embedding ``""`` would score every product
    against nothing and reorder results for no reason.
    """
    config = config or EmbeddingConfig.from_env()
    if not config.configured or not request_text.strip():
        return None
    built_at, count = snapshot_fingerprint(db_path)
    return SemanticScorer(
        request_text=request_text,
        products=products,
        config=config,
        client=client,
        key=CacheKey(
            base_url=config.base_url,
            model=config.model,
            built_at=built_at,
            product_count=count,
        ),
    )
