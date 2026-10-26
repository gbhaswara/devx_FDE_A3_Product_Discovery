"""The rate-limited HTTP crawler.

The site must be served over HTTP: volume pricing is fetched by JavaScript from
per-SKU JSON documents, and opening the files from disk does not load them. So
this module never touches the filesystem for catalog content — everything comes
over HTTP.

Rate limit: the site's footer permits 2 requests per second and ``robots.txt``
sets ``Crawl-delay: 1``. We run at 1 req/s, which is inside both.

Provenance is captured on every fetch (final URL and retrieval timestamp) so
that each catalog row can be traced back to what produced it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

USER_AGENT = "PaperLaneCatalogBot/0.1 (assignment crawl; 1 req/s)"


class CrawlError(RuntimeError):
    """Raised when the site cannot be fetched at all."""


@dataclass(frozen=True)
class FetchedPage:
    """One fetched document, with the provenance needed to audit it."""

    url: str
    status: int
    text: str
    crawled_at: datetime

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Crawler:
    """A sequential, rate-limited HTTP client.

    Sequential on purpose: the permitted rate is 1-2 req/s, so concurrency buys
    nothing and would risk exceeding the limit.
    """

    def __init__(
        self,
        base_url: str,
        *,
        rate_per_second: float = 1.0,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if rate_per_second > 2.0:
            raise ValueError(
                f"the site permits at most 2 requests/second; {rate_per_second} "
                "would exceed it"
            )

        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise CrawlError(
                f"base_url must be http(s), got {base_url!r}. The catalog must be "
                "served over HTTP; opening files from disk will not load volume prices."
            )

        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.rate = rate_per_second
        self._min_interval = 1.0 / rate_per_second
        self._last_request_at = 0.0
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self.request_count = 0

    # -- lifecycle ------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "Crawler":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- fetching -------------------------------------------------------
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def fetch(self, path_or_url: str) -> FetchedPage:
        """Fetch one document, respecting the rate limit."""
        url = (
            path_or_url
            if path_or_url.startswith(("http://", "https://"))
            else urljoin(self.base_url, path_or_url.lstrip("/"))
        )
        self._throttle()
        try:
            response = self._client.get(url)
        finally:
            self._last_request_at = time.monotonic()
        self.request_count += 1
        return FetchedPage(
            url=str(response.url),
            status=response.status_code,
            text=response.text,
            crawled_at=datetime.now(timezone.utc),
        )

    def fetch_ok(self, path_or_url: str) -> FetchedPage:
        """Fetch and require a 2xx response."""
        page = self.fetch(path_or_url)
        if not page.ok:
            raise CrawlError(f"{page.url} returned HTTP {page.status}")
        return page

    def fetch_json(self, path_or_url: str):
        """Fetch and parse a JSON document.

        Parsed with ``parse_float=Decimal`` so no float is ever constructed:
        the money path depends on that.
        """
        import json
        from decimal import Decimal

        page = self.fetch_ok(path_or_url)
        try:
            return json.loads(page.text, parse_float=Decimal), page
        except json.JSONDecodeError as exc:
            raise CrawlError(f"{page.url} is not valid JSON: {exc}") from exc
