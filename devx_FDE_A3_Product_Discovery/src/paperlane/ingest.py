"""Ingest: crawl the served site, extract every leaf SKU, build a snapshot.

The orchestration is deliberately sequential and boring. It walks the four
category pages, follows every product link, extracts each page, then fetches one
volume-pricing document per SKU that advertises volume pricing. Everything is
provenance-stamped as it is collected.

Two cross-checks run at the end and both produce review rows rather than
corrections:

* **Availability.** Category cards and product pages are separate renderings of
  the same claim. When they disagree, both values are kept and the disagreement
  is flagged.
* **Tier documents.** The number of documents retrieved must equal the number
  of SKUs that advertise volume pricing. A SKU that advertises pricing but has
  no document is a failure, not a silent zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser

from . import catalog
from .crawl import Crawler, CrawlError, FetchedPage
from .extract import ExtractedProduct, ReviewRow, extract
from .money import to_satang

#: The four category entry points, discovered from the home page rather than
#: hard-coded, but listed here as the expected set for the reference site.
EXPECTED_CATEGORIES = 4

#: Words a card uses when it is claiming an item is unavailable.
_CARD_OUT_RE = re.compile(r"out of stock", re.I)
_CARD_DISCONTINUED_RE = re.compile(r"discontinued", re.I)


@dataclass
class IngestResult:
    """Everything one ingest produced, before it is written to a snapshot."""

    products: list[dict[str, Any]] = field(default_factory=list)
    tiers: list[catalog.TierRow] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    pages_fetched: int = 0
    tier_docs_found: int = 0
    category_cards: dict[str, str] = field(default_factory=dict)


def _discover_category_urls(crawler: Crawler) -> list[str]:
    """Follow the home page's category links.

    The links are relative (``category/copy-paper/index.html``), so the test is
    on the path segment rather than on a leading slash.
    """
    home = crawler.fetch_ok("index.html")
    tree = LexborHTMLParser(home.text)
    urls: list[str] = []
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        if "category/" in href and "page-" not in href:
            urls.append(urljoin(home.url, href))
    # De-duplicate, preserve order.
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _product_links(crawler: Crawler, category_url: str) -> list[tuple[str, str]]:
    """Every ``(product_url, card_text)`` on a category page and its pagers."""
    found: list[tuple[str, str]] = []
    to_visit = [category_url]
    visited: set[str] = set()

    while to_visit:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)
        page = crawler.fetch_ok(url)
        tree = LexborHTMLParser(page.text)

        for card in tree.css("div.card"):
            link = card.css_first("h3 a")
            if link is None:
                continue
            href = link.attributes.get("href") or ""
            if "product/" not in href:
                continue
            found.append((urljoin(page.url, href), _card_text(card)))

        for a in tree.css("div.pager a"):
            href = a.attributes.get("href") or ""
            if href and "page-" in href:
                next_url = urljoin(page.url, href)
                if next_url not in visited:
                    to_visit.append(next_url)

    return found


def _card_text(card) -> str:
    """The card's muted line, which is where an availability claim appears."""
    muted = card.css_first("div.muted")
    return " ".join(muted.text().split()) if muted is not None else ""


def _card_stock_claim(card_text: str) -> str | None:
    """What the card claims about availability, if it claims anything."""
    if _CARD_DISCONTINUED_RE.search(card_text):
        return "discontinued"
    if _CARD_OUT_RE.search(card_text):
        return "out_of_stock"
    return None


def _advertised_skus(html: str) -> set[str]:
    """The SKUs on this page that offer a tier document.

    Two published spellings for "no volume pricing": the explicit sentence "No
    volume pricing for this item.", and a ``data-sku`` span carrying
    ``data-sale='1'``. Everything else with a ``data-sku`` is a loader
    placeholder, which means a document exists.

    Read per SKU rather than per page, because a variant table carries one
    placeholder per row and one row may be the sale item.
    """
    if "No volume pricing for this item." in html:
        return set()
    tree = LexborHTMLParser(html)
    skus: set[str] = set()
    for node in tree.css("[data-sku]"):
        if node.attributes.get("data-sale") == "1":
            continue
        sku = node.attributes.get("data-sku")
        if sku:
            skus.add(sku)
    return skus


def run_ingest(base_url: str, rate: float = 1.0) -> int:
    """Crawl, extract, cross-check, build, and swap. Returns a process code."""
    result = IngestResult()

    try:
        crawler = Crawler(base_url, rate_per_second=rate)
    except CrawlError as exc:
        print(f"ingest failed: {exc}")
        return 2

    crawled_at = datetime.now(timezone.utc)

    with crawler:
        try:
            category_urls = _discover_category_urls(crawler)
            if not category_urls:
                print("ingest failed: no category links found on the home page")
                return 2
            print(f"categories: {len(category_urls)}")

            product_pages: list[tuple[str, str]] = []
            for category_url in category_urls:
                links = _product_links(crawler, category_url)
                print(f"  {category_url} -> {len(links)} product links")
                product_pages.extend(links)

            # A product reachable from two categories is crawled once.
            seen_pages: dict[str, str] = {}
            for url, card_text in product_pages:
                seen_pages.setdefault(url, card_text)

            print(f"product pages: {len(seen_pages)}")

            tier_docs: dict[str, tuple[Decimal | None, list[tuple[int, Decimal]], str]] = {}

            for url, card_text in sorted(seen_pages.items()):
                page = crawler.fetch_ok(url)
                products, reviews = extract(page.text, page.url)

                for review in reviews:
                    result.reviews.append({
                        "kind": "extraction",
                        "url": review.url,
                        "sku": review.sku,
                        "reason": review.reason,
                        "raw_excerpt": review.raw_excerpt,
                    })

                card_claim = _card_stock_claim(card_text)
                advertised = _advertised_skus(page.text)
                for product in products:
                    result.products.append(
                        _to_row(product, page.url, crawled_at,
                                has_volume_pricing=product.sku in advertised)
                    )
                    if card_claim and card_claim != product.stock_status:
                        # Both renderings are kept; neither overwrites the other.
                        result.reviews.append({
                            "kind": "availability_disagreement",
                            "url": page.url,
                            "sku": product.sku,
                            "reason": (
                                f"category card claims {card_claim!r} but the "
                                f"product page claims {product.stock_status!r}"
                            ),
                            "raw_excerpt": card_text,
                        })
                    result.category_cards[product.sku] = card_text

            print(f"leaf SKUs: {len(result.products)}")
            advertised_total = sum(1 for r in result.products if r["has_volume_pricing"])
            print(f"SKUs advertising volume pricing: {advertised_total}")

            # One tier document per SKU that advertises volume pricing.
            for row in result.products:
                sku = row["sku"]
                if not row["has_volume_pricing"]:
                    continue
                try:
                    doc, page = crawler.fetch_json(
                        f"api/pricing/{sku}.json"
                    )
                except CrawlError as exc:
                    result.reviews.append({
                        "kind": "tier_document",
                        "url": f"api/pricing/{sku}.json",
                        "sku": sku,
                        "reason": f"advertised volume pricing but document failed: {exc}",
                        "raw_excerpt": None,
                    })
                    continue

                result.tier_docs_found += 1
                tiers = doc.get("tiers") or []
                if not tiers:
                    result.reviews.append({
                        "kind": "tier_document",
                        "url": page.url,
                        "sku": sku,
                        "reason": "document exists but contains no tiers",
                        "raw_excerpt": None,
                    })
                    continue
                for tier in tiers:
                    result.tiers.append(catalog.TierRow(
                        sku=sku,
                        min_qty=int(tier["min_qty"]),
                        unit_price_satang=to_satang(tier["unit_price"]),
                        source_url=page.url,
                        crawled_at=page.crawled_at,
                    ))

            result.pages_fetched = crawler.request_count

            # Cross-check: documents retrieved vs SKUs advertising them.
            advertised = sum(1 for r in result.products if r["has_volume_pricing"])
            if result.tier_docs_found != advertised:
                result.reviews.append({
                    "kind": "tier_document",
                    "url": base_url,
                    "sku": None,
                    "reason": (
                        f"{advertised} SKUs advertise volume pricing but "
                        f"{result.tier_docs_found} documents were retrieved"
                    ),
                    "raw_excerpt": None,
                })

        except CrawlError as exc:
            print(f"ingest failed: {exc}")
            return 2

    print(f"requests: {result.pages_fetched}")
    print(f"tier documents: {result.tier_docs_found}")
    print(f"review items: {len(result.reviews)}")

    # Build to a staging file, then swap. A failure above never reaches here.
    staged = catalog.build_snapshot(
        products=result.products,
        tiers=result.tiers,
        reviews=result.reviews,
        base_url=base_url,
        pages_fetched=result.pages_fetched,
        tier_docs_found=result.tier_docs_found,
        # An unresolved item from the previous snapshot is carried forward
        # unless this run reports it again, so the backlog cannot vanish.
        carry_reviews_from=catalog.DEFAULT_DB_PATH,
    )
    catalog.swap_into_place(staged)
    print(f"snapshot: {catalog.DEFAULT_DB_PATH}")
    return 0


def _to_row(
    product: ExtractedProduct,
    url: str,
    crawled_at: datetime,
    *,
    has_volume_pricing: bool,
) -> dict[str, Any]:
    """Convert an extracted product into the store's row shape.

    Money is converted to integer satang here and nowhere else on the way in.
    """
    return {
        "sku": product.sku,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "size_code": product.size_code,
        "width_mm": product.width_mm,
        "height_mm": product.height_mm,
        "weight_gsm": product.weight_gsm,
        "weight_raw": product.weight_raw,
        "weight_form": product.weight_form,
        "colour_name": product.colour_name,
        "colour_mode": product.colour_mode,
        "sides": product.sides,
        "finish": product.finish,
        "pack_sheets": product.pack_sheets,
        "unit_word": product.unit_word,
        "list_price_satang": to_satang(product.list_price),
        "sale_price_satang": (
            to_satang(product.sale_price) if product.sale_price is not None else None
        ),
        "has_volume_pricing": has_volume_pricing,
        "stock_status": product.stock_status,
        "back_in_stock_date": product.back_in_stock_date,
        "description": product.description,
        "source_url": url,
        "source_shape": product.source_shape,
        "crawled_at": crawled_at,
        "raw_labels": product.raw_labels,
    }
