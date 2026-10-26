"""Crawler tests: rate limiting, HTTP-only, provenance.

These run against a stub transport, so they are offline and fast, but they
assert the properties that matter against the real site: the interval between
requests, the refusal to read from disk, and the provenance recorded per fetch.
"""

from __future__ import annotations

import time

import httpx
import pytest

from paperlane.crawl import Crawler, CrawlError


def stub_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestRateLimit:
    def test_rejects_rate_above_the_permitted_two_per_second(self):
        with pytest.raises(ValueError, match="at most 2 requests/second"):
            Crawler("http://localhost:8000/paperlane/", rate_per_second=3.0)

    def test_accepts_one_and_two(self):
        for rate in (1.0, 2.0):
            crawler = Crawler(
                "http://localhost:8000/paperlane/",
                rate_per_second=rate,
                client=stub_client(lambda r: httpx.Response(200, text="ok")),
            )
            crawler.close()

    def test_rejects_non_positive_rate(self):
        with pytest.raises(ValueError, match="positive"):
            Crawler("http://localhost:8000/paperlane/", rate_per_second=0)

    def test_requests_are_spaced(self):
        # At the maximum permitted 2 req/s the throttle is 0.5 s, so a second
        # request must wait. This asserts the property the site's Crawl-delay
        # asks for, rather than assuming it.
        crawler = Crawler(
            "http://localhost:8000/paperlane/",
            rate_per_second=2.0,
            client=stub_client(lambda r: httpx.Response(200, text="ok")),
        )
        start = time.monotonic()
        crawler.fetch("index.html")
        crawler.fetch("index.html")
        elapsed = time.monotonic() - start
        crawler.close()
        assert elapsed >= 0.45, f"no throttling applied: {elapsed:.3f}s"

    def test_default_rate_is_one_per_second(self):
        crawler = Crawler(
            "http://localhost:8000/paperlane/",
            client=stub_client(lambda r: httpx.Response(200, text="ok")),
        )
        assert crawler.rate == 1.0
        assert crawler._min_interval == pytest.approx(1.0)
        crawler.close()


class TestHttpOnly:
    def test_filesystem_path_is_refused(self):
        # The site must be served over HTTP: volume pricing is fetched by
        # JavaScript, so reading files from disk would silently lose tiers.
        with pytest.raises(CrawlError, match="must be http"):
            Crawler("/mnt/data/paperlane/")

    def test_file_scheme_is_refused(self):
        with pytest.raises(CrawlError, match="must be http"):
            Crawler("file:///mnt/data/paperlane/")

    def test_plain_path_is_refused(self):
        with pytest.raises(CrawlError, match="must be http"):
            Crawler("./paperlane/")


class TestProvenance:
    def test_url_and_timestamp_recorded(self):
        crawler = Crawler(
            "http://localhost:8000/paperlane/",
            rate_per_second=2.0,
            client=stub_client(lambda r: httpx.Response(200, text="<html>ok</html>")),
        )
        page = crawler.fetch("product/x.html")
        crawler.close()
        assert page.url == "http://localhost:8000/paperlane/product/x.html"
        assert page.crawled_at.tzinfo is not None
        assert page.status == 200

    def test_request_count_is_tracked(self):
        crawler = Crawler(
            "http://localhost:8000/paperlane/",
            rate_per_second=2.0,
            client=stub_client(lambda r: httpx.Response(200, text="ok")),
        )
        for _ in range(4):
            crawler.fetch("index.html")
        assert crawler.request_count == 4
        crawler.close()


class TestErrors:
    def test_non_2xx_raises_from_fetch_ok(self):
        crawler = Crawler(
            "http://localhost:8000/paperlane/",
            rate_per_second=2.0,
            client=stub_client(lambda r: httpx.Response(404, text="nope")),
        )
        with pytest.raises(CrawlError, match="HTTP 404"):
            crawler.fetch_ok("missing.html")
        crawler.close()

    def test_bad_json_raises(self):
        crawler = Crawler(
            "http://localhost:8000/paperlane/",
            rate_per_second=2.0,
            client=stub_client(lambda r: httpx.Response(200, text="not json")),
        )
        with pytest.raises(CrawlError, match="not valid JSON"):
            crawler.fetch_json("api/pricing/X.json")
        crawler.close()


class TestJsonParsing:
    def test_prices_parse_as_decimal_not_float(self):
        body = '{"sku":"X","tiers":[{"min_qty":10,"unit_price":122.55}]}'
        crawler = Crawler(
            "http://localhost:8000/paperlane/",
            rate_per_second=2.0,
            client=stub_client(lambda r: httpx.Response(200, text=body)),
        )
        doc, _ = crawler.fetch_json("api/pricing/X.json")
        crawler.close()
        from decimal import Decimal

        price = doc["tiers"][0]["unit_price"]
        assert isinstance(price, Decimal)
        assert price == Decimal("122.55")
