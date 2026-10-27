"""The four-shape extraction ladder with a review floor.

The catalog uses four distinct markup shapes, and the *labels differ between
them*. Verified against the real site:

    table         (10 pages)  Size, Weight, Colour, Finish, Sheets per pack
    dl            (10 pages)  Paper size + Dimensions, Basis weight, Shade,
                              Surface, Pack contents; brand label is
                              ``Manufacturer``, not ``Brand``
    variant-table  (6 pages)  42 flyer rows; ``Colour`` means PRINT colour mode
    prose         (10 pages)  facts only in sentences: "it weighs 80 gsm."

Three silent traps live here:

* ``Colour`` in a ``table`` is the paper **shade**; ``Colour`` in a
  ``variant-table`` is the **print colour mode**. Same word, two fields.
* ``dl`` splits size into a code (``Paper size``) and dimensions
  (``Dimensions``), where ``table`` concatenates them into one string.
* Ten pages have no spec table at all: every fact is only in a sentence.

The ladder ends in a **review row**, never an exception and never a skip. A page
that cannot be parsed becomes visible; it does not disappear from the catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser

from .normalize import SizeError, WeightError, parse_size, parse_weight

#: Shapes, in the order the ladder tries them.
SHAPE_VARIANT_TABLE = "variant-table"
SHAPE_TABLE = "table"
SHAPE_DL = "dl"
SHAPE_PROSE = "prose"
SHAPE_UNKNOWN = "unknown"

#: Canonical field names. Every shape maps onto these, and the raw label and
#: value are always retained alongside so a mapping can be audited.
FIELD_SKU = "sku"
FIELD_BRAND = "brand"
FIELD_CATEGORY = "category"
FIELD_SIZE_CODE = "size_code"
FIELD_WIDTH_MM = "width_mm"
FIELD_HEIGHT_MM = "height_mm"
FIELD_WEIGHT_GSM = "weight_gsm"
FIELD_WEIGHT_RAW = "weight_raw"
FIELD_WEIGHT_FORM = "weight_form"
FIELD_COLOUR_NAME = "colour_name"
FIELD_COLOUR_MODE = "colour_mode"
FIELD_SIDES = "sides"
FIELD_FINISH = "finish"
FIELD_PACK_SHEETS = "pack_sheets"
FIELD_UNIT_WORD = "unit_word"
FIELD_LIST_PRICE = "list_price"
FIELD_SALE_PRICE = "sale_price"
FIELD_STOCK = "stock_status"
FIELD_RESTOCK = "back_in_stock_date"
FIELD_DESCRIPTION = "description"

#: Which raw labels map to which canonical field, per shape.
#:
#: The mapping is per-shape because the same label means different things in
#: different shapes, and because the shapes use different words for the same
#: fact. ``Manufacturer`` and ``Brand`` are one field; ``Size`` and
#: ``Paper size`` are one field.
LABEL_MAP_TABLE = {
    "item code": FIELD_SKU,
    "brand": FIELD_BRAND,
    "size": FIELD_SIZE_CODE,
    "weight": FIELD_WEIGHT_RAW,
    "colour": FIELD_COLOUR_NAME,   # table: paper shade
    "finish": FIELD_FINISH,
    "sheets per pack": FIELD_PACK_SHEETS,
}

LABEL_MAP_DL = {
    "sku": FIELD_SKU,
    "manufacturer": FIELD_BRAND,   # dl says Manufacturer where table says Brand
    "paper size": FIELD_SIZE_CODE,
    "dimensions": "dimensions",    # dl splits size; table concatenates it
    "basis weight": FIELD_WEIGHT_RAW,
    "shade": FIELD_COLOUR_NAME,
    "surface": FIELD_FINISH,
    "pack contents": FIELD_PACK_SHEETS,
}

#: Currency amounts: "฿1,234.56" or "1,234.56 THB".
_MONEY_RE = re.compile(r"[฿]\s*([0-9][0-9,]*\.\d{2})|([0-9][0-9,]*\.\d{2})\s*THB")
_STOCK_OUT_RE = re.compile(r"stock-out[^>]*>\s*([^<]*)", re.I)
_RESTOCK_RE = re.compile(r"expected back\s+(\d{1,2}\s+\w+\s+\d{4})", re.I)
_DISCONTINUED_RE = re.compile(r"discontinued", re.I)
_ITEM_CODE_RE = re.compile(r"Item code:?\s*([A-Z0-9][A-Z0-9-]+)", re.I)

#: Prose facts. Every one of the 10 prose pages follows this shape:
#:   "<Name> from <Brand> is supplied as a <unit> of <N> sheets.
#:    Each sheet is <Size> (<dims>) and weighs <weight>.
#:    The <colour> sheets have a <finish> surface and run well in ..."
_PROSE_SUPPLIED = re.compile(r"supplied as a\s+(ream|pack|box)\s+of\s+(\d+)\s+sheets", re.I)
_PROSE_WEIGHT = re.compile(r"weighs?\s+(\d+(?:\.\d+)?\s*(?:gsm|g/m\u00b2|g/m2))", re.I)
_PROSE_SIZE = re.compile(
    r"(?:Each sheet is|sheet is)\s+([^.(]*\([^)]*\))", re.I
)
_PROSE_COLOUR_FINISH = re.compile(
    r"The\s+([a-z][a-z ]*?)\s+sheets have a\s+([a-z][a-z ]*?)\s+surface", re.I
)
_PROSE_BRAND = re.compile(r"\bfrom\s+([A-Z][A-Za-z ]+?)\s+is supplied", re.I)


@dataclass
class ExtractedProduct:
    """One leaf SKU, normalised. Absent attributes stay ``None``.

    ``None`` means *not applicable*, never "false" or "zero". A plain-paper
    product has no printing sides, so ``sides is None``; a constraint on sides
    must therefore not exclude it.
    """

    sku: str
    name: str = ""
    brand: str | None = None
    category: str | None = None
    size_code: str | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    weight_gsm: int | None = None
    weight_raw: str | None = None
    weight_form: str | None = None
    colour_name: str | None = None
    colour_mode: str | None = None
    sides: str | None = None
    finish: str | None = None
    pack_sheets: int | None = None
    unit_word: str | None = None
    list_price: Decimal | None = None
    sale_price: Decimal | None = None
    stock_status: str = "in_stock"
    back_in_stock_date: str | None = None
    description: str | None = None
    source_url: str = ""
    source_shape: str = ""
    raw_labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ReviewRow:
    """A page or row that could not be parsed.

    The floor of the ladder. Carries enough to diagnose the failure without
    re-fetching: the reason and a short excerpt of the offending markup.
    """

    url: str
    reason: str
    raw_excerpt: str = ""
    sku: str | None = None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _text(node) -> str:
    return " ".join(node.text().split()) if node is not None else ""


def _money(text: str) -> Decimal | None:
    """Pull the first currency amount out of a string.

    Both published formats are accepted: ``฿129.00`` (20 pages) and
    ``72.00 THB`` (10 pages).
    """
    if not text:
        return None
    m = _MONEY_RE.search(text)
    if not m:
        return None
    return Decimal((m.group(1) or m.group(2)).replace(",", ""))


def _detect_shape(html: str) -> str:
    """Identify which of the four shapes a page uses.

    Detection is by markup structure, not by URL, so a renamed page or a new
    page in an existing shape is still handled.
    """
    if "Options and prices" in html:
        return SHAPE_VARIANT_TABLE
    if re.search(r"<table class=['\"]specs['\"]", html):
        return SHAPE_TABLE
    if re.search(r"<dl class=['\"]specs['\"]", html):
        return SHAPE_DL
    if re.search(r"weighs?\s+\d", html, re.I):
        return SHAPE_PROSE
    return SHAPE_UNKNOWN


def _stock_state(html: str) -> tuple[str, str | None]:
    """Return ``(stock_status, restock_date)`` for a page or row."""
    if _DISCONTINUED_RE.search(html):
        return "discontinued", None
    m = _STOCK_OUT_RE.search(html)
    if m:
        r = _RESTOCK_RE.search(m.group(1))
        return "out_of_stock", r.group(1) if r else None
    return "in_stock", None


def _category(tree: LexborHTMLParser) -> str | None:
    """The breadcrumb link above the heading, e.g. 'Copy paper'."""
    crumb = tree.css_first("main > p.muted > a")
    return _text(crumb) if crumb is not None else None


def _description(tree: LexborHTMLParser) -> str | None:
    node = tree.css_first("div.description p")
    return _text(node) if node is not None else None


def _item_code(tree: LexborHTMLParser) -> str | None:
    """The 'Item code: X' line that table and prose pages carry in prose."""
    for node in tree.css("p.muted"):
        m = _ITEM_CODE_RE.search(_text(node))
        if m:
            return m.group(1)
    return None


def _pack_sheets(value: str | None) -> int | None:
    """Extract a sheet count from '500', '500 sheets', '500 sheets / ream'."""
    if value is None:
        return None
    m = re.search(r"(\d{1,4})", value)
    return int(m.group(1)) if m else None


def _apply_size(product: ExtractedProduct, raw: str | None,
                dimensions: str | None = None) -> None:
    """Normalise size, combining the dl shape's split fields when needed."""
    candidate = " ".join(x for x in (raw, dimensions) if x).strip()
    if not candidate:
        return
    code, width, height = parse_size(candidate)
    product.size_code = code
    product.width_mm = width
    product.height_mm = height


def _apply_weight(product: ExtractedProduct, raw: str | None) -> None:
    if not raw:
        return
    weight = parse_weight(raw)
    product.weight_gsm = weight.gsm
    product.weight_raw = weight.raw
    product.weight_form = weight.form


def _read_pricebox(tree: LexborHTMLParser) -> tuple[Decimal | None, Decimal | None, str | None]:
    """Read ``(list_price, sale_price, unit_word)`` from the price box.

    The box has two published layouts, both verified on the real site:

        <div class='pricebox'><div class='big'>฿129.00</div>
            <div class='muted'>Ream of 500 sheets</div> ...

        <div class='pricebox'><div>Price: <span class='big'>72.00 THB</span>
            / ream</div> ...

    So the amount always comes from ``.big``, but the unit word comes from
    ``.muted`` in the first layout and from the text after the slash in the
    second. The unit word is display text only — see ``docs/ingestion.md``.
    """
    box = tree.css_first("div.pricebox")
    if box is None:
        return None, None, None

    big = box.css_first(".big")
    amount = _money(_text(big)) if big is not None else None

    # A struck-through list price in the box means the item is on sale.
    del_node = box.css_first("del")
    if del_node is not None:
        list_price = _money(_text(del_node))
        sale_price = amount
        return list_price, sale_price, _unit_word(box, big)

    return amount, None, _unit_word(box, big)


def _unit_word(box, big) -> str | None:
    """The unit basis as published, for display only.

    Two layouts, plus one trap. A price line can carry the unit itself —
    ``Price: <span class='big'>289.00 THB</span> / ream`` — while the only
    ``.muted`` in the box is a note, ``No volume pricing for this item.``. The
    price line is therefore read first when it has no muted text of its own, so
    the note cannot be stored as a unit (BUG.md A16).

    Deliberately unreliable as a data source: ``pl-cl-a4-80-pyl.html`` states
    "195.00 THB / ream" in the price box while its own spec table says
    "Pack contents: 500 sheets". Nothing may compare or filter on this value;
    ``pack_sheets`` is the machine-readable field.
    """
    if big is not None:
        parent = big.parent
        if parent is not None and parent.css_first(".muted") is None:
            raw = _text(parent)
            if "/" in raw:
                tail = raw.rsplit("/", 1)[1].strip()
                if tail:
                    return tail
    muted = box.css_first(".muted")
    if muted is not None:
        return _text(muted) or None
    return None


# ---------------------------------------------------------------------------
# Shape: table
# ---------------------------------------------------------------------------


def extract_table(html: str, url: str) -> tuple[list[ExtractedProduct], list[ReviewRow]]:
    tree = LexborHTMLParser(html)
    reviews: list[ReviewRow] = []
    product = ExtractedProduct(
        sku="", name=_text(tree.css_first("h1")), source_url=url,
        source_shape=SHAPE_TABLE,
    )
    product.category = _category(tree)
    product.description = _description(tree)

    table = tree.css_first("table.specs")
    if table is None:
        return [], [ReviewRow(url, "table shape but no table.specs", html[:200])]

    for row in table.css("tr"):
        th, td = row.css_first("th"), row.css_first("td")
        if th is None or td is None:
            continue
        label, value = _text(th), _text(td)
        product.raw_labels[label] = value
        target = LABEL_MAP_TABLE.get(label.lower())
        if target == FIELD_SKU:
            product.sku = value
        elif target == FIELD_BRAND:
            product.brand = value
        elif target == FIELD_FINISH:
            product.finish = value
        elif target == FIELD_COLOUR_NAME:
            product.colour_name = value
        elif target == FIELD_PACK_SHEETS:
            product.pack_sheets = _pack_sheets(value)
        elif target == FIELD_SIZE_CODE:
            try:
                _apply_size(product, value)
            except SizeError as exc:
                reviews.append(ReviewRow(url, f"size: {exc}", value, product.sku or None))
        elif target == FIELD_WEIGHT_RAW:
            try:
                _apply_weight(product, value)
            except WeightError as exc:
                reviews.append(ReviewRow(url, f"weight: {exc}", value, product.sku or None))

    # The table shape carries its SKU in the table, but fall back to the prose
    # line if a future page drops the row.
    product.sku = product.sku or (_item_code(tree) or "")

    product.list_price, product.sale_price, product.unit_word = _read_pricebox(tree)
    product.stock_status, product.back_in_stock_date = _stock_state(html)
    return _finish([product], reviews, url)


# ---------------------------------------------------------------------------
# Shape: dl
# ---------------------------------------------------------------------------


def extract_dl(html: str, url: str) -> tuple[list[ExtractedProduct], list[ReviewRow]]:
    tree = LexborHTMLParser(html)
    reviews: list[ReviewRow] = []
    product = ExtractedProduct(
        sku="", name=_text(tree.css_first("h1")), source_url=url,
        source_shape=SHAPE_DL,
    )
    product.category = _category(tree)
    product.description = _description(tree)

    dl = tree.css_first("dl.specs")
    if dl is None:
        return [], [ReviewRow(url, "dl shape but no dl.specs", html[:200])]

    values: dict[str, str] = {}
    for dt, dd in zip(dl.css("dt"), dl.css("dd")):
        label, value = _text(dt), _text(dd)
        product.raw_labels[label] = value
        target = LABEL_MAP_DL.get(label.lower())
        if target is not None:
            values[target] = value

    product.sku = values.get(FIELD_SKU, "")
    product.brand = values.get(FIELD_BRAND)
    product.colour_name = values.get(FIELD_COLOUR_NAME)
    product.finish = values.get(FIELD_FINISH)
    product.pack_sheets = _pack_sheets(values.get(FIELD_PACK_SHEETS))

    try:
        # dl splits the size across two fields; table concatenates them.
        _apply_size(product, values.get(FIELD_SIZE_CODE), values.get("dimensions"))
    except SizeError as exc:
        reviews.append(ReviewRow(
            url, f"size: {exc}",
            f"{values.get(FIELD_SIZE_CODE)} / {values.get('dimensions')}",
            product.sku or None,
        ))
    try:
        _apply_weight(product, values.get(FIELD_WEIGHT_RAW))
    except WeightError as exc:
        reviews.append(ReviewRow(url, f"weight: {exc}", values.get(FIELD_WEIGHT_RAW),
                                 product.sku or None))

    product.sku = product.sku or (_item_code(tree) or "")

    product.list_price, product.sale_price, product.unit_word = _read_pricebox(tree)
    product.stock_status, product.back_in_stock_date = _stock_state(html)
    return _finish([product], reviews, url)


# ---------------------------------------------------------------------------
# Shape: variant-table (flyer pages: many leaf SKUs on one page)
# ---------------------------------------------------------------------------


def _normalise_sides(text: str) -> str | None:
    t = (text or "").lower()
    if "single" in t:
        return "single"
    if "double" in t:
        return "double"
    return None


def _finish_from_heading(page_name: str) -> str | None:
    """Flyer pages state the paper finish once, in the heading.

    ``Digital Flyers A4 – Gloss`` and ``Letter-size Flyers (8.5 × 11 in) –
    Matte``. The finish is a real attribute of the paper, so it must reach the
    same ``finish`` field the table and prose shapes populate; a filter on
    finish would otherwise silently exclude all 42 flyer SKUs.
    """
    for known in ("Gloss", "Matte", "Uncoated", "Laid", "Smooth"):
        if re.search(rf"\b{known}\b", page_name, re.I):
            return known
    return None


def extract_variant_table(html: str, url: str) -> tuple[list[ExtractedProduct], list[ReviewRow]]:
    """Extract every leaf SKU row from a flyer page.

    One page carries 6 or 8 leaf SKUs, each with its own price and its own
    tier document. The columns are authoritative for every attribute; the
    ``-40``/``-44``/``-10``/``-11`` suffix is never used to infer anything.
    """
    tree = LexborHTMLParser(html)
    products: list[ExtractedProduct] = []
    reviews: list[ReviewRow] = []

    page_name = _text(tree.css_first("h1"))
    category = _category(tree)
    description = _description(tree)
    page_stock, page_restock = _stock_state(html)

    table = tree.css_first("table")
    if table is None:
        return [], [ReviewRow(url, "variant-table shape but no table", html[:200])]

    rows = table.css("tr")
    if not rows:
        return [], [ReviewRow(url, "variant-table has no rows", html[:200])]

    # Column positions come from the header row, never from a fixed index.
    headers = [_text(th).lower() for th in rows[0].css("th")]
    try:
        i_sku = headers.index("item code")
        i_weight = headers.index("paper weight")
        i_print = headers.index("printing")
        i_colour = headers.index("colour")
        i_price = next(i for i, h in enumerate(headers) if h.startswith("price per pack"))
    except (ValueError, StopIteration):
        return [], [ReviewRow(url, "variant-table header not recognised",
                              str(headers)[:200])]

    # "Price per pack of 100" — the pack size is stated in the header.
    pack_match = re.search(r"pack of\s+(\d+)", headers[i_price])
    pack_sheets = int(pack_match.group(1)) if pack_match else None

    for row in rows[1:]:
        cells = row.css("td")
        if len(cells) <= max(i_sku, i_weight, i_print, i_colour, i_price):
            continue
        values = [_text(c) for c in cells]
        sku = values[i_sku].strip()
        if not sku:
            continue

        product = ExtractedProduct(
            sku=sku,
            # The name must distinguish every leaf SKU. Two rows differ only by
            # colour mode (-10 black-and-white vs -40 full colour), so leaving
            # the colour column out would give two different products the same
            # display name and make the reply ambiguous.
            name=f"{page_name} — {values[i_weight]}, {values[i_print]}, {values[i_colour]}",
            brand=None,
            category=category,
            colour_mode=values[i_colour] or None,   # variant-table: PRINT colour
            sides=_normalise_sides(values[i_print]),
            finish=_finish_from_heading(page_name),
            pack_sheets=pack_sheets,
            description=description,
            source_url=url,
            source_shape=SHAPE_VARIANT_TABLE,
            raw_labels=dict(zip(headers, values)),
        )

        # Size is stated once for the whole page, in the heading.
        try:
            _apply_size(product, page_name)
        except SizeError as exc:
            reviews.append(ReviewRow(url, f"size: {exc}", page_name, sku))
        try:
            _apply_weight(product, values[i_weight])
        except WeightError as exc:
            reviews.append(ReviewRow(url, f"weight: {exc}", values[i_weight], sku))

        # Price: the cell may hold <del>list</del> sale<span>Sale</span>.
        price_cell = cells[i_price]
        del_node = price_cell.css_first("del")
        if del_node is not None:
            product.list_price = _money(_text(del_node))
            remainder = price_cell.html.split("</del>", 1)[-1]
            product.sale_price = _money(re.sub(r"<[^>]+>", " ", remainder))
        else:
            product.list_price = _money(values[i_price])
            product.sale_price = None

        # Availability is per row on this shape.
        product.stock_status, product.back_in_stock_date = page_stock, page_restock
        if "availability" in headers:
            i_avail = headers.index("availability")
            if i_avail < len(cells):
                avail = values[i_avail]
                if re.search(r"out of stock", avail, re.I):
                    product.stock_status = "out_of_stock"
                    m = _RESTOCK_RE.search(avail)
                    product.back_in_stock_date = m.group(1) if m else None
                elif re.search(r"discontinued", avail, re.I):
                    product.stock_status = "discontinued"
                elif avail:
                    product.stock_status = "in_stock"

        product.unit_word = f"pack of {pack_sheets} printed sheets" if pack_sheets else None
        products.append(product)

    if not products:
        reviews.append(ReviewRow(url, "variant-table produced no rows", html[:200]))
    return _finish(products, reviews, url)


# ---------------------------------------------------------------------------
# Shape: prose (no spec table; every fact is in a sentence)
# ---------------------------------------------------------------------------


def extract_prose(html: str, url: str) -> tuple[list[ExtractedProduct], list[ReviewRow]]:
    """Extract a page whose facts exist only in prose.

    Ten pages have no table and no definition list. The sentences are regular,
    but a regex is still a regex: a sentence that fails to match produces a
    review row rather than a missing attribute.
    """
    tree = LexborHTMLParser(html)
    reviews: list[ReviewRow] = []
    product = ExtractedProduct(
        sku="", name=_text(tree.css_first("h1")), source_url=url,
        source_shape=SHAPE_PROSE,
    )
    product.category = _category(tree)
    product.description = _description(tree)

    body = " ".join(_text(tree.css_first("main")).split())

    m = _ITEM_CODE_RE.search(body)
    if m:
        product.sku = m.group(1)

    m = _PROSE_BRAND.search(body)
    if m:
        product.brand = m.group(1).strip()

    m = _PROSE_SUPPLIED.search(body)
    if m:
        product.unit_word = f"{m.group(1).lower()} of {m.group(2)} sheets"
        product.pack_sheets = int(m.group(2))

    m = _PROSE_SIZE.search(body)
    if m:
        try:
            _apply_size(product, m.group(1))
        except SizeError as exc:
            reviews.append(ReviewRow(url, f"size: {exc}", m.group(1), product.sku or None))
    else:
        reviews.append(ReviewRow(url, "prose page with no size sentence", body[:200],
                                 product.sku or None))

    m = _PROSE_WEIGHT.search(body)
    if m:
        try:
            _apply_weight(product, m.group(1))
        except WeightError as exc:
            reviews.append(ReviewRow(url, f"weight: {exc}", m.group(0), product.sku or None))
    else:
        reviews.append(ReviewRow(url, "prose page with no weight sentence", body[:200],
                                 product.sku or None))

    m = _PROSE_COLOUR_FINISH.search(body)
    if m:
        product.colour_name = m.group(1).strip()
        product.finish = m.group(2).strip()

    product.list_price, product.sale_price, product.unit_word = _read_pricebox(tree)
    if product.unit_word is None and product.pack_sheets is not None:
        product.unit_word = f"pack of {product.pack_sheets} sheets"
    product.stock_status, product.back_in_stock_date = _stock_state(html)
    return _finish([product], reviews, url)


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def extract(html: str, url: str) -> tuple[list[ExtractedProduct], list[ReviewRow]]:
    """Run the extraction ladder over one page.

    Returns ``(products, reviews)``. Never raises for a page-level problem: an
    unrecognised shape produces a review row, so the catalog cannot silently
    shrink.
    """
    shape = _detect_shape(html)
    handlers = {
        SHAPE_VARIANT_TABLE: extract_variant_table,
        SHAPE_TABLE: extract_table,
        SHAPE_DL: extract_dl,
        SHAPE_PROSE: extract_prose,
    }
    handler = handlers.get(shape)
    if handler is None:
        return [], [ReviewRow(url, "unrecognised markup shape", html[:300])]

    try:
        return handler(html, url)
    except Exception as exc:  # noqa: BLE001 - the floor must catch everything
        return [], [ReviewRow(url, f"{shape} extraction failed: {exc}", html[:300])]


def _finish(
    products: list[ExtractedProduct], reviews: list[ReviewRow], url: str
) -> tuple[list[ExtractedProduct], list[ReviewRow]]:
    """Apply the minimum-completeness check that decides review vs accept."""
    kept: list[ExtractedProduct] = []
    for product in products:
        if not product.sku:
            reviews.append(ReviewRow(url, "no SKU found on page", product.name))
            continue
        if product.list_price is None:
            reviews.append(ReviewRow(url, "no price found on page", product.name, product.sku))
            continue
        kept.append(product)
    return kept, reviews
