"""The catalog column: what it lists, what a click does, and what it must not do.

The left-hand column is a *convenience*, and these tests hold the line that
keeps it one:

* it lists exactly the snapshot's products, grouped, with every field escaped;
* a row is a plain `button` that fills the search box and makes no request, so
  a click cannot spend a model call or invent a quantity;
* the name it puts in the box is one the interpreter resolves to that product —
  verified for **all 72**, not sampled, because "most names work" is the kind of
  claim that rots the moment the catalog changes;
* the price on the row is the price a one-unit quote returns for that SKU, so
  the column and the quote beside it cannot disagree — including the sale item,
  whose effective price is 259.00 while its list price is 299.00;
* every category is a native `<details>`, all closed on arrival, so the column
  shows the whole catalog's shape at once instead of the part that fits a
  scroller;
* the two columns are equal tracks, and a narrow screen still stacks the search
  first;
* a page with no snapshot still renders, carrying the remedy.

The escaping tests drive `render_catalog` directly with hostile text rather than
hoping the committed snapshot happens to contain some. The catalog is crawled
from a third-party site, so its text is untrusted input, and the fixture that
proves it is escaped should not depend on a page we do not control.
"""

from __future__ import annotations

import html as html_module
import re

import pytest
from fastapi.testclient import TestClient

from paperlane import assistant, catalog, interpret, ui
from paperlane.api import create_app

#: One row of the column, exactly as `_catalog_row` emits it. The fields are
#: escaped, so they contain no raw `<`.
_ROW = re.compile(
    r'<li><button type="button" class="item" data-request="(?P<request>[^"]*)">'
    r'<span class="item-name">(?P<name>[^<]*)</span>'
    r'<span class="item-meta">(?P<meta>[^<]*)</span>'
    r"(?P<foot>.*?)</button></li>",
    re.S,
)
_PRICE = re.compile(r'<span class="item-price">([^<]+)</span>')

_HOST = re.compile(r"""(?:src|href|action)\s*=\s*["']https?://[^"']+""")


@pytest.fixture(scope="module")
def client() -> TestClient:
    # Recording is off: these tests are about the page, and 70 requests would
    # otherwise fill the request log with rows no one asked to measure.
    return TestClient(create_app(record_writer=None))


@pytest.fixture(scope="module")
def products() -> list[dict]:
    return catalog.load_products()


@pytest.fixture(scope="module")
def page(client: TestClient) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.text


def rows_of(page: str) -> list[dict]:
    found = []
    for match in _ROW.finditer(page):
        price = _PRICE.search(match.group("foot"))
        found.append(
            {
                "request": html_module.unescape(match.group("request")),
                "name": html_module.unescape(match.group("name")),
                "meta": html_module.unescape(match.group("meta")),
                "price": price.group(1) if price else None,
                "out_of_stock": "stock-out" in match.group("foot"),
            }
        )
    return found


# ---------------------------------------------------------------------------
# It lists the catalog
# ---------------------------------------------------------------------------


class TestItListsTheCatalog:
    def test_every_product_appears_exactly_once(self, page, products) -> None:
        rows = rows_of(page)
        assert len(rows) == len(products)
        assert sorted(row["name"] for row in rows) == sorted(
            product["name"] for product in products
        )

    def test_grouped_by_category_with_a_count(self, page, products) -> None:
        expected: dict[str, int] = {}
        for product in products:
            expected[product["category"]] = expected.get(product["category"], 0) + 1

        groups = dict(
            (html_module.unescape(name), int(count))
            for name, count in re.findall(
                r"<summary>([^<]+)<span>(\d+)</span></summary>", page
            )
        )
        assert groups == expected
        assert sum(groups.values()) == len(products)

    def test_the_row_says_what_the_product_is(self, page, products) -> None:
        """Name, size, weight and unit — the fields someone browses by."""
        by_name = {row["name"]: row for row in rows_of(page)}
        sample = next(p for p in products if p["sku"] == "PL-CP-A4-80-NUSA")
        row = by_name[sample["name"]]
        assert sample["size_code"] in row["meta"]
        assert sample["weight_raw"] in row["meta"]
        assert f"pack of {sample['pack_sheets']} sheets" in row["meta"]

    def test_out_of_stock_is_labelled_rather_than_hidden(self, page, products) -> None:
        """Still listed, still clickable, and honest about why it will be refused."""
        expected = sorted(p["name"] for p in products if p["stock_status"] == "out_of_stock")
        labelled = sorted(row["name"] for row in rows_of(page) if row["out_of_stock"])
        assert labelled == expected
        assert len(labelled) == 2

    def test_no_unit_phrase_leaks_from_the_price_box(self, page) -> None:
        """`unit_word` holds the site's non-volume note on four SKUs (BUG.md A16)."""
        assert "No volume pricing" not in page


# ---------------------------------------------------------------------------
# The column collapses, so the whole catalog fits
# ---------------------------------------------------------------------------


class TestTheCatalogIsCollapsible:
    """Every category is a native `<details>`, all closed on arrival.

    Asked for directly: the left column should be a drop-down so all categories
    and items can be seen. The column used to be a fixed-height scroller with a
    sticky panel; on a 900-pixel window the first category filled it and the rest
    were below an inner scrollbar, so "which categories exist" was a question
    answered by scrolling. Collapsed to headings, all of them are on screen.

    `<details>` is deliberate over a scripted accordion. The page has exactly one
    script and it only fills the search box; a browser-implemented disclosure
    needs no code, is keyboard operable, and announces its expanded state.
    """

    def test_every_category_is_a_disclosure_with_its_count(self, page, products) -> None:
        expected: dict[str, int] = {}
        for product in products:
            expected[product["category"]] = expected.get(product["category"], 0) + 1

        blocks = page.split('<details class="group"')[1:]
        assert len(blocks) == len(expected), "one disclosure per category"

        found = {}
        for block in blocks:
            summary = re.search(
                r"<summary>([^<]+)<span>(\d+)</span></summary>", block
            )
            assert summary is not None, "every disclosure needs a summary"
            found[html_module.unescape(summary.group(1))] = int(summary.group(2))
        assert found == expected

    def test_every_row_sits_inside_its_disclosure(self, page, products) -> None:
        """Otherwise closing a group would leave its items on screen."""
        blocks = page.split('<details class="group"')[1:]
        inside = sum(
            block.split("</details>", 1)[0].count("<li><button") for block in blocks
        )
        assert inside == len(products)

    def test_no_group_starts_open(self, page, products) -> None:
        """Collapsed on arrival is the whole point.

        Opening the first category reads friendlier, but it pushes the remaining
        headings below the bottom of the panel — the state this change exists to
        leave. Closed, every category is on screen at once.
        """
        headings = re.findall(r'<details class="group"( open)?>', page)
        assert len(headings) == len({product["category"] for product in products})
        assert all(flag == "" for flag in headings), "no group may start expanded"

    def test_the_column_has_no_height_of_its_own_to_run_out_of(self) -> None:
        """The old panel was `max-height: calc(100vh - 2rem)` with `overflow-y`.

        That is what clipped the catalog: the first category filled the box and
        the others sat below an inner scrollbar. A container with no fixed height
        cannot hide anything — the page scrolls instead.
        """
        style = ui.PAGE.split("<style>", 1)[1].split("</style>", 1)[0]
        catalog = re.search(r"\.catalog \{([^}]*)\}", style)
        assert catalog is not None
        assert "max-height" not in catalog.group(1)
        assert "overflow-y" not in catalog.group(1)
        assert "catalog-scroll" not in ui.PAGE

    def test_a_click_inside_a_collapsed_group_still_fills_the_box(self, page) -> None:
        """The handler is delegated to `document`, so disclosure cannot break it.

        A listener bound per row at load would also work, but delegation is what
        makes collapse irrelevant: opening a group later needs no rebinding, and
        a row hidden on arrival behaves exactly like a visible one.
        """
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "document.addEventListener('click'" in script
        assert "closest('[data-request]')" in script
        assert "onclick" not in page


class TestTheSplitIsHalfAndHalf:
    """The two columns are equal tracks, and a narrow screen still stacks."""

    @staticmethod
    def _style() -> str:
        return ui.PAGE.split("<style>", 1)[1].split("</style>", 1)[0]

    def test_the_two_columns_are_equal_tracks(self) -> None:
        style = self._style()
        layout = re.search(r"main\.layout\s*\{([^}]*)\}", style)
        assert layout is not None
        assert re.search(
            r"grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(0,\s*1fr\)",
            layout.group(1),
        ), "the split must be 50-50, and must not be widenable by its content"
        assert "minmax(15rem, 19rem)" not in style, "the old fixed track is gone"

    def test_a_narrow_screen_stacks_the_search_above_the_catalog(self) -> None:
        """Two 50% columns on a phone would be two unreadable slivers."""
        narrow = re.search(
            r"@media \(max-width: 900px\)\s*\{(.*?)\n  \}", self._style(), re.S
        )
        assert narrow is not None
        block = narrow.group(1)
        assert "grid-template-columns: 1fr" in block
        assert ".workspace { order: 1; }" in block
        assert ".catalog { order: 2;" in block


# ---------------------------------------------------------------------------
# A click fills the box; it does not ask
# ---------------------------------------------------------------------------


class TestAClickPrefillsRatherThanSubmits:
    def test_every_row_is_a_plain_button(self, page) -> None:
        for row in page.split('<li><button')[1:]:
            tag = row.split(">", 1)[0]
            assert 'type="button"' in tag, tag
            assert "hx-" not in tag, (
                "a catalog row must make no request; the only way to ask a "
                f"question is the form: {tag}"
            )
            assert 'data-request="' in tag

    def test_the_row_carries_the_products_own_name(self, page, products) -> None:
        rows = rows_of(page)
        assert {row["request"] for row in rows} == {p["name"] for p in products}

    def test_the_page_wires_the_click_to_the_search_box(self, page) -> None:
        assert 'id="request"' in page
        assert "getElementById('request')" in page

        # Prefill only: judge the code, not the comment above it. A row must not
        # submit the form or call htmx on its own.
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        code = "\n".join(
            line for line in script.splitlines() if not line.strip().startswith("//")
        )
        assert ".submit(" not in code
        assert "requestSubmit" not in code
        assert "htmx." not in code


class TestAClickedNameReachesTheAssistant:
    def test_every_product_name_resolves_to_that_product(self, products) -> None:
        """All 72, because the click rests on it.

        A row that put a name in the box which the assistant could not find
        would be worse than no list: the page would show a product and the reply
        would say nothing matched. The two out-of-stock products are expected to
        be *refused*, and the refusal must name them — that is still an answer
        about the product that was clicked.
        """
        facts = catalog.load_price_facts()
        failures = []

        for product in products:
            criteria = interpret.interpret(product["name"], None).criteria
            reply = assistant.answer(
                criteria, products, facts, interpretation="rules"
            )
            quoted = {candidate.sku for candidate in reply.candidates}
            refused = {candidate.sku for candidate in reply.refused}

            if reply.outcome == "quoted" and product["sku"] not in quoted:
                failures.append((product["sku"], reply.outcome, sorted(quoted)[:3]))
            elif reply.outcome == "refused" and product["sku"] not in refused:
                failures.append((product["sku"], reply.outcome, sorted(refused)[:3]))
            elif reply.outcome not in ("quoted", "refused"):
                failures.append((product["sku"], reply.outcome, reply.text[:80]))

        assert failures == [], (
            "clicking these rows would not answer about the product clicked: "
            f"{failures}"
        )


class TestThePriceIsTheQuote:
    def test_each_row_shows_the_one_unit_quote(self, client, page, products) -> None:
        """Not the stored list price: the effective one, sale included.

        Compares against `/api/quote/lines` rather than re-deriving the number,
        so a page that formatted its own figure would be caught.
        """
        displayed = {
            row["request"]: row["price"]
            for row in rows_of(page)
            if row["price"] is not None
        }
        assert len(displayed) == len(products), "every row must carry a price"

        quoted: dict[str, str] = {}
        skus = [product["sku"] for product in products]
        for start in range(0, len(skus), 50):          # the endpoint's limit
            chunk = skus[start:start + 50]
            response = client.post(
                "/api/quote/lines",
                json={"lines": [{"sku": sku, "quantity": 1} for sku in chunk]},
            )
            assert response.status_code == 200, response.text
            for line in response.json()["figures"]["lines"]:
                quoted[line["sku"]] = line["unit_price"]

        names = {product["sku"]: product["name"] for product in products}
        mismatches = [
            (sku, names[sku], displayed[names[sku]], quoted[sku])
            for sku in skus
            if displayed[names[sku]] != quoted[sku]
        ]
        assert mismatches == [], f"the page and the quote disagree: {mismatches}"

    def test_the_sale_item_shows_the_sale_price_not_the_list_price(
        self, page, products
    ) -> None:
        """The case that made this rule necessary.

        One SKU is on sale, and a sale price replaces the list price *and* every
        tier. A column built from `list_price_satang` would advertise a price the
        quote then refuses to honour. Both numbers are read from the snapshot, so
        this still holds if the sale ends or the prices change.
        """
        from paperlane.money import format_baht

        sale = next(p for p in products if p["sale_price_satang"] is not None)
        assert sale["sale_price_satang"] != sale["list_price_satang"]

        row = next(row for row in rows_of(page) if row["name"] == sale["name"])
        assert row["price"] == format_baht(sale["sale_price_satang"])
        assert row["price"] != format_baht(sale["list_price_satang"])

    def test_no_price_is_invented_when_facts_are_missing(self) -> None:
        """Degrade to no price, never to 0.00."""
        rendered = ui.render_catalog(
            [
                {
                    "sku": "X-1",
                    "name": "A product with no facts",
                    "category": "Copy paper",
                    "size_code": "A4",
                    "weight_raw": "80 gsm",
                    "pack_sheets": 500,
                    "stock_status": "in_stock",
                }
            ],
            None,
        )
        assert _PRICE.search(rendered) is None
        assert "0.00" not in rendered


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------


class TestCrawledTextIsEscaped:
    def test_a_hostile_name_renders_as_text(self) -> None:
        rendered = ui.render_catalog(
            [
                {
                    "sku": "X-1",
                    "name": '<script>alert("x")</script>',
                    "category": "Copy paper",
                    "size_code": "A4",
                    "weight_raw": "80 gsm",
                    "pack_sheets": 10,
                    "stock_status": "in_stock",
                }
            ]
        )
        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered
        assert len(re.findall(r'data-request="', rendered)) == 1, (
            "a quote in the name must not be able to open a second attribute"
        )
        assert '&quot;x&quot;' in rendered

    def test_a_hostile_category_cannot_inject_markup(self) -> None:
        rendered = ui.render_catalog(
            [
                {
                    "sku": "X-2",
                    "name": "Innocent product",
                    "category": '<img src=x onerror="alert(1)">',
                    "stock_status": "in_stock",
                }
            ]
        )
        assert "<img" not in rendered
        assert "&lt;img" in rendered


# ---------------------------------------------------------------------------
# Degraded states
# ---------------------------------------------------------------------------


class TestDegradedStates:
    def test_no_snapshot_still_renders_the_page(self, tmp_path) -> None:
        """A dead page is a dead end; the page is where the remedy belongs."""
        missing = tmp_path / "absent.duckdb"
        client = TestClient(
            create_app(db_path=missing, record_writer=None),
            raise_server_exceptions=False,
        )

        response = client.get("/")
        assert response.status_code == 200
        assert "No catalog snapshot" in response.text
        assert str(missing) in response.text
        assert "run.sh ingest" in response.text
        assert rows_of(response.text) == []

    def test_the_search_box_works_even_with_no_catalog(self, tmp_path) -> None:
        """The form is not part of the degraded state."""
        client = TestClient(
            create_app(db_path=tmp_path / "absent.duckdb", record_writer=None),
            raise_server_exceptions=False,
        )
        body = client.get("/").text
        assert 'hx-post="/ask"' in body
        assert 'id="request"' in body

    def test_an_empty_snapshot_says_so_rather_than_looking_broken(self) -> None:
        rendered = ui.render_catalog([])
        assert "holds no products" in rendered
        assert "catalog-empty" in rendered

    def test_the_served_page_has_no_external_host(self, page) -> None:
        """Post-substitution, so a product field cannot introduce one."""
        assert _HOST.findall(page) == []

    def test_neither_placeholder_survives_substitution(self, page) -> None:
        assert "__CATALOG__" not in page
        assert "__CONVERSATION_ID__" not in page
