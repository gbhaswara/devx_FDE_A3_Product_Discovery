"""The single page.

Two equal columns: the catalog on the left, the assistant on the right.
Server-rendered HTML fragments over htmx, same origin, no build step and no
client-side state beyond "a click puts a product name in the search box".

The catalog's categories are native ``<details>`` disclosures. A fixed-height
scroller could show only the part of the catalog that happened to be near the
top, so "which categories exist" was a question answered by scrolling; collapsed
groups put every category on screen at once, and each is one click from its
items. No script is involved — the browser does the disclosure, so the page's
one script is still the one that fills the search box.

The page's job is to make the four outcomes *visibly* different, because the
most likely misreading of a sales assistant is treating "nothing matched" as
"here is something close". A no-match is styled as a warning, a refusal as a
blocked item, and only a quote is styled as a result.

The catalog column is a convenience, not a second way to answer a request: it
lists what the snapshot holds and fills the search box when a row is clicked.
It never submits, never quotes and never prices anything in the browser — a
click starts the one ordinary request path, so there is still exactly one way an
answer can be produced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

#: The one availability value the page treats as a warning. Absent is not
#: negative: any other value (including an unknown one) renders with no label
#: rather than claiming the product is in stock.
_OUT_OF_STOCK = "out_of_stock"

#: Where the vendored htmx build lives. Served by ``GET /static/htmx.min.js``.
#:
#: It used to be a ``<script src="https://unpkg.com/...">``. That made the one
#: interactive surface the only part of the system needing internet access, and
#: it failed *silently*: the form carries ``hx-post`` and no ``method``/``action``,
#: so with no htmx loaded the browser issues a plain GET of the current URL and
#: the page merely reloads. The API kept answering, so every curl-based check
#: still passed while a human saw a dead page. Same bytes, same hash, no network.
#: Provenance and licence: ``static/VENDOR.md``.
HTMX_ASSET = Path(__file__).with_name("static") / "htmx.min.js"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PaperLane sales assistant</title>
<script src="/static/htmx.min.js"></script>
<style>
  :root {
    --ink: #1a1a1a; --muted: #6b6b6b; --line: #dcdcdc;
    --paper: #fbfbf9; --accent: #1f5f4a; --warn: #8a5a00; --stop: #8a2b2b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1rem 4rem; background: var(--paper); color: var(--ink);
    font: 16px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  .masthead, main.layout, footer { max-width: 78rem; margin-left: auto; margin-right: auto; }
  h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
  .sub { color: var(--muted); margin: 0 0 1.75rem; font-size: .92rem; }
  form { display: flex; gap: .5rem; flex-wrap: wrap; }
  input[type=text] {
    flex: 1 1 22rem; padding: .7rem .85rem; font: inherit;
    border: 1px solid var(--line); border-radius: 6px; background: #fff;
  }
  input[type=number] { width: 7rem; padding: .7rem .85rem; font: inherit;
    border: 1px solid var(--line); border-radius: 6px; background: #fff; }
  button {
    padding: .7rem 1.2rem; font: inherit; font-weight: 600; color: #fff;
    background: var(--accent); border: 0; border-radius: 6px; cursor: pointer;
  }
  button:disabled { opacity: .55; cursor: progress; }
  .examples { margin: 1rem 0 0; display: flex; gap: .5rem; flex-wrap: wrap; }
  .examples button {
    background: none; color: var(--accent); border: 1px solid var(--line);
    font-weight: 400; font-size: .86rem; padding: .35rem .7rem;
  }
  /* Two equal columns: the catalog on the left, the assistant on the right.
     `minmax(0, 1fr)` and not a bare `1fr` on both tracks — `1fr` is
     `minmax(auto, 1fr)`, so a long product name would widen its own column past
     the half and the split would stop being 50-50. With the minimum at 0 the
     cells can shrink, and the name wraps instead. */
  main.layout {
    display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 2rem; align-items: start;
  }
  .workspace { min-width: 0; }
  .catalog {
    border: 1px solid var(--line); border-radius: 8px; background: #fff;
    overflow: hidden;
  }
  .catalog-head {
    display: flex; justify-content: space-between; align-items: baseline;
    gap: .5rem; padding: .8rem 1rem; background: #f4f4ef;
    border-bottom: 1px solid var(--line);
  }
  .catalog-head h2 {
    margin: 0; font-size: .74rem; letter-spacing: .08em;
    text-transform: uppercase; color: var(--muted);
  }
  .catalog-head .count { font-size: .75rem; color: var(--muted); }
  /* One disclosure per category. The summary is the old category heading plus
     a chevron. `display: flex` replaces the native marker, so the chevron is
     drawn here and both marker implementations are suppressed below. */
  .group > summary {
    display: flex; align-items: baseline; gap: .45rem;
    padding: .5rem 1rem; cursor: pointer; list-style: none;
    font-size: .7rem; letter-spacing: .07em; text-transform: uppercase;
    color: var(--muted); background: var(--paper);
    border-bottom: 1px solid var(--line); user-select: none;
  }
  .group > summary::-webkit-details-marker { display: none; }
  /* Drawn with borders, not a glyph: a font without U+25B8 renders the marker as
     a missing-character box, which is how this looked in testing. */
  .group > summary::before {
    content: ""; align-self: center; flex: none;
    width: 0; height: 0; border-left: 5px solid currentColor;
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    transition: transform .12s ease;
  }
  .group[open] > summary::before { transform: rotate(90deg); }
  .group > summary:hover { color: var(--ink); }
  .group > summary:focus-visible {
    outline: 2px solid var(--accent); outline-offset: -2px;
  }
  .group > summary span { margin-left: auto; font-weight: 400; }
  .group ul { list-style: none; margin: 0; padding: 0; }
  .group li + li { border-top: 1px solid #efefea; }
  .item {
    display: block; width: 100%; padding: .55rem 1rem; text-align: left;
    background: none; border: 0; border-radius: 0; color: var(--ink);
    font: inherit; font-weight: 400; cursor: pointer;
  }
  .item:hover, .item:focus-visible { background: #eef4f0; }
  .item-name { display: block; font-size: .84rem; line-height: 1.35; }
  .item-meta {
    display: block; font-size: .74rem; color: var(--muted); margin-top: .12rem;
  }
  .item-foot {
    display: flex; justify-content: space-between; gap: .5rem; margin-top: .2rem;
    font-size: .76rem; font-variant-numeric: tabular-nums;
  }
  .item-price { font-weight: 600; }
  .stock-out { color: var(--stop); }
  .catalog-hint {
    margin: 0; padding: .55rem 1rem; border-bottom: 1px solid var(--line);
    font-size: .72rem; line-height: 1.45; color: var(--muted);
  }
  .catalog-empty { margin: 0; padding: 1rem; font-size: .8rem; color: var(--muted); }
  .catalog-empty code { font-size: .76rem; word-break: break-all; }
  @media (max-width: 900px) {
    main.layout { grid-template-columns: 1fr; }
    .workspace { order: 1; }
    .catalog { order: 2; }
  }
  #result { margin-top: 2rem; }
  .panel {
    border: 1px solid var(--line); border-radius: 8px; background: #fff;
    padding: 1.25rem 1.4rem;
  }
  .panel.quoted   { border-left: 4px solid var(--accent); }
  .panel.clarified{ border-left: 4px solid var(--muted); }
  .panel.no_match { border-left: 4px solid var(--warn); }
  .panel.refused  { border-left: 4px solid var(--stop); }
  .badge {
    display: inline-block; font-size: .72rem; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; padding: .18rem .5rem; border-radius: 3px;
    margin-bottom: .9rem;
  }
  .quoted .badge   { background: #e6f0eb; color: var(--accent); }
  .clarified .badge{ background: #eee; color: var(--muted); }
  .no_match .badge { background: #f6eeda; color: var(--warn); }
  .refused .badge  { background: #f7e5e5; color: var(--stop); }
  pre.reply {
    margin: 0; white-space: pre-wrap; word-break: break-word;
    font: 13.5px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .criteria { margin-top: 1.1rem; padding-top: .9rem; border-top: 1px dashed var(--line);
    font-size: .84rem; color: var(--muted); }
  .criteria b { color: var(--ink); font-weight: 600; }
  .meta { margin-top: .55rem; font-size: .78rem; color: var(--muted); }
  .errors { margin-top: .9rem; padding: .6rem .8rem; background: #f7e5e5;
    border-radius: 5px; font-size: .84rem; color: var(--stop); }
  .warnings { margin-top: .9rem; padding: .6rem .8rem; background: #f6eeda;
    border-radius: 5px; font-size: .84rem; color: var(--warn); }
  .htmx-indicator { display: none; color: var(--muted); font-size: .86rem; }
  .htmx-request .htmx-indicator { display: block; }
  .note { color: var(--muted); font-size: .84rem; margin: .75rem 0 0; }
  .note a, .note button.link {
    background: none; border: 0; padding: 0; font: inherit; font-size: inherit;
    color: var(--accent); cursor: pointer; text-decoration: underline;
  }
  #conversation-bar:empty { display: none; }
  #conversation-bar {
    margin-top: .75rem; font-size: .8rem; color: var(--muted);
  }
  #conversation-bar b { color: var(--ink); font-weight: 600; }
  footer { margin: 3rem auto 0; font-size: .8rem; color: var(--muted); }
  footer a { color: var(--muted); }
</style>
</head>
<body>
<header class="masthead">
  <h1>PaperLane sales assistant</h1>
  <p class="sub">Describe what you need, or pick a product from the catalog.
  Prices are per pack, before 7% VAT, and volume pricing is applied at the
  quantity you ask for.</p>
</header>

<main class="layout">
__CATALOG__
  <section class="workspace">
    <form hx-post="/ask" hx-target="#result" hx-swap="innerHTML"
          hx-disabled-elt="button" hx-indicator="#spinner">
      <input type="hidden" name="conversation_id" id="conversation_id"
             value="__CONVERSATION_ID__">
      <input type="text" name="request" id="request" required autofocus
             placeholder="e.g. letter-size flyers, one side, colour, under 250 a pack, 20 packs">
      <input type="number" name="quantity" min="1" placeholder="qty">
      <button type="submit">Ask</button>
    </form>
    <div id="spinner" class="htmx-indicator">Working&hellip;</div>
    <p class="note">This page remembers your last request so you can refine it &mdash;
    try <em>make it 50</em> after a quote. The reply says what it remembered.
    <a href="/" id="start-over">Start over</a>.</p>

    <div class="examples">
      <button hx-post="/ask" hx-target="#result" hx-swap="innerHTML"
              hx-vals='{"request": "A4 copy paper, 80 gsm, 20 reams"}'>A4 copy, 20 reams</button>
      <button hx-post="/ask" hx-target="#result" hx-swap="innerHTML"
              hx-vals='{"request": "letter-size flyers, one side, colour, under 250 a pack, 20 packs"}'>Letter flyers under 250</button>
      <button hx-post="/ask" hx-target="#result" hx-swap="innerHTML"
              hx-vals='{"request": "I need ivory A4 paper"}'>Ivory A4 (out of stock)</button>
      <button hx-post="/ask" hx-target="#result" hx-swap="innerHTML"
              hx-vals='{"request": "paper 400 gsm"}'>400 gsm (no match)</button>
      <button hx-post="/ask" hx-target="#result" hx-swap="innerHTML"
              hx-vals='{"request": "I need colour paper"}'>Ambiguous colour</button>
    </div>

    <div id="result"></div>
  </section>
</main>
<footer>
  Data from the PaperLane catalog snapshot. Delivery is free from 3,000.00;
  otherwise 150.00. VAT is charged on goods plus delivery.
</footer>
<script>
  // A catalog row fills the search box and stops there. Clicking is a shortcut
  // for typing a product name, not a request: it never submits, so it cannot
  // spend a model call or invent a quantity the customer did not ask for.
  document.addEventListener('click', function (event) {
    var row = event.target.closest && event.target.closest('[data-request]');
    if (!row) return;
    var input = document.getElementById('request');
    if (!input) return;
    input.value = row.getAttribute('data-request');
    input.focus();
  });
</script>
</body>
</html>
"""


def render_fragment(
    *,
    outcome: str,
    badge: str,
    body: str,
    criteria: dict,
    meta: dict,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    conversation: dict | None = None,
) -> str:
    """Render one result panel.

    Everything is escaped. The reply text contains product names and catalog
    descriptions, which are *untrusted input* — the site is crawled, not
    authored here — so it is treated as text and never as markup. That is the
    same rule the extraction layer applies, carried through to the browser.
    """
    from html import escape

    parts = [f'<div class="panel {escape(outcome)}">',
             f'<span class="badge">{escape(badge)}</span>',
             f'<pre class="reply">{escape(body)}</pre>']

    if criteria:
        rendered = ", ".join(
            f"<b>{escape(str(k))}</b> {escape(str(v))}" for k, v in criteria.items()
        )
        parts.append(f'<div class="criteria">Understood: {rendered}</div>')

    if meta:
        rendered_meta = " &middot; ".join(
            f"{escape(str(k))}: {escape(str(v))}" for k, v in meta.items()
        )
        parts.append(f'<div class="meta">{rendered_meta}</div>')

    if conversation:
        # Which turn this was, and which requirements it carried. The reply text
        # already says what was remembered in words; this is the same fact in a
        # form a reader can scan, and it is how a salesperson sees that the
        # assistant is not starting from nothing on turn two.
        turn = conversation.get("turn")
        carried = conversation.get("carried") or []
        rendered = (
            f"<b>Turn {escape(str(turn))}</b>"
            + (
                " &middot; remembered: "
                + escape(", ".join(carried).replace("_", " "))
                if carried else
                " &middot; nothing carried from earlier turns"
            )
        )
        parts.append(f'<div id="conversation-bar">{rendered}</div>')

    if errors:
        parts.append(
            '<div class="errors"><b>Self-check failed:</b><br>'
            + "<br>".join(escape(e) for e in errors)
            + "</div>"
        )
    if warnings:
        parts.append(
            '<div class="warnings"><b>Note:</b><br>'
            + "<br>".join(escape(w) for w in warnings)
            + "</div>"
        )

    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# The catalog column
# ---------------------------------------------------------------------------


def _unit_price_at_one(facts: Mapping[str, Any] | None, sku: str) -> str | None:
    """The price the quote would charge for one unit, formatted.

    Deliberately *not* ``list_price_satang``. A sale price replaces both the
    list price and every tier (PR3), so a row rendered from the stored list
    price would advertise 299.00 for an item the assistant prices at 259.00 —
    the browse column contradicting the quote beside it. Going through
    ``pricing.unit_price`` keeps the two from being able to disagree.

    ``None`` when the SKU has no facts, which renders the row without a price
    rather than with a guessed one.
    """
    if not facts or not sku:
        return None
    entry = facts.get(sku)
    if entry is None:
        return None

    from .money import format_baht
    from .pricing import unit_price

    return format_baht(unit_price(entry, 1).satang)


def _catalog_row(product: dict[str, Any], facts: Mapping[str, Any] | None) -> str:
    """One product: name, what it is, what it costs, whether it can ship."""
    from html import escape

    from .assistant import unit_phrase

    name = str(product.get("name") or product.get("sku") or "")
    # `unit_phrase` rather than `unit_word`: see BUG.md A16. It falls back to
    # `pack_sheets`, which is the field the reply already trusts.
    meta = " &middot; ".join(
        escape(str(value))
        for value in (
            product.get("size_code"),
            product.get("weight_raw"),
            unit_phrase(product),
        )
        if value
    )

    price = _unit_price_at_one(facts, str(product.get("sku") or ""))
    stock = (
        '<span class="stock-out">out of stock</span>'
        if str(product.get("stock_status") or "") == _OUT_OF_STOCK
        else ""
    )
    foot = ""
    if price is not None or stock:
        cells = []
        if price is not None:
            cells.append(f'<span class="item-price">{escape(price)}</span>')
        if stock:
            cells.append(stock)
        foot = f'<span class="item-foot">{"".join(cells)}</span>'

    # A `button`, not a link or an hx-* element: the click is a local edit of
    # the search box and makes no request. `data-request` carries the product's
    # own name — the string verified to round-trip through the interpreter —
    # so a click starts the one ordinary request path, not a second one.
    return (
        f'<li><button type="button" class="item"'
        f' data-request="{escape(name, quote=True)}">'
        f'<span class="item-name">{escape(name)}</span>'
        f'<span class="item-meta">{meta}</span>'
        f"{foot}</button></li>"
    )


def _catalog_shell(count: str, body: str, hint: str = "") -> str:
    return (
        '<aside class="catalog" aria-label="Catalog">'
        '<div class="catalog-head"><h2>Catalog</h2>'
        f'<span class="count">{count}</span></div>'
        f"{hint}"
        f"{body}"
        "</aside>"
    )


def render_catalog(
    products: Sequence[dict[str, Any]] | None,
    facts: Mapping[str, Any] | None = None,
    *,
    snapshot_path: str = "",
) -> str:
    """The left-hand column: everything in the snapshot, grouped by category.

    Three states, and all three render:

    * ``None`` — there is no snapshot yet, so the column carries the remedy.
      A page that fails to load is a dead end; the page is where someone looks,
      so the command that fixes it belongs on it.
    * an empty sequence — the snapshot exists but holds nothing.
    * products — grouped alphabetically by category, in the snapshot's own
      order within a group, so the list is stable between page loads.

    Every field is escaped, by the same rule as :func:`render_fragment`: the
    catalog is crawled from a third-party site, so its text is untrusted input.
    """
    from html import escape

    if products is None:
        where = f" at <code>{escape(snapshot_path)}</code>" if snapshot_path else ""
        body = (
            f'<p class="catalog-empty">No catalog snapshot{where}. Build one '
            "with <code>./run.sh ingest --base-url "
            "http://localhost:8000/paperlane/</code>.</p>"
        )
        return _catalog_shell("none", body, "")

    if not products:
        body = '<p class="catalog-empty">The snapshot holds no products.</p>'
        return _catalog_shell("empty", body, "")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for product in products:
        category = str(product.get("category") or "Uncategorised")
        grouped.setdefault(category, []).append(product)

    # Every category is a disclosure, and every one starts closed. Closed, the
    # column is the catalog's map: four headings instead of a list longer than
    # the window, so which categories exist is answerable at a glance. Opening
    # one shows its rows in place and lets the page scroll.
    #
    # The previous version was a fixed-height scroller with a sticky panel. On a
    # 900-pixel window that showed the first category and clipped the rest, which
    # is the complaint this shape answers: the container no longer has a height
    # of its own to run out of.
    #
    # `<details>` and not a scripted accordion. The page has one script, and it
    # only fills the search box; a disclosure the browser implements is keyboard
    # operable and announced as expanded or collapsed without any of that.
    sections = []
    for category in sorted(grouped):
        items = grouped[category]
        rows = "".join(_catalog_row(product, facts) for product in items)
        sections.append(
            '<details class="group">'
            f"<summary>{escape(category)}<span>{len(items)}</span></summary>"
            f"<ul>{rows}</ul></details>"
        )

    # The quantity matters. A row shows the price for *one* unit, and the one
    # mistake this column must not invite is comparing it against a budget —
    # the trap recorded as T1 in BUG.md. The quote applies tiers at whatever
    # quantity was asked for.
    hint = (
        '<p class="catalog-hint">Open a category to see its products, then click '
        "one to put its name in the search box. Prices are each, before VAT, at "
        "quantity 1; volume tiers are applied when you ask for a quote.</p>"
    )
    return _catalog_shell(f"{len(products)} products", "".join(sections), hint)
