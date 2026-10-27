"""The single page.

One page, one input, one result panel. Server-rendered HTML fragments over htmx,
same origin, no build step and no client-side state.

The page's job is to make the four outcomes *visibly* different, because the
most likely misreading of a sales assistant is treating "nothing matched" as
"here is something close". A no-match is styled as a warning, a refusal as a
blocked item, and only a quote is styled as a result.
"""

from __future__ import annotations

from pathlib import Path

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
  main { max-width: 52rem; margin: 0 auto; }
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
  footer { max-width: 52rem; margin: 3rem auto 0; font-size: .8rem; color: var(--muted); }
  footer a { color: var(--muted); }
</style>
</head>
<body>
<main>
  <h1>PaperLane sales assistant</h1>
  <p class="sub">Describe what you need. Prices are per pack, before 7% VAT, and
  volume pricing is applied at the quantity you ask for.</p>

  <form hx-post="/ask" hx-target="#result" hx-swap="innerHTML"
        hx-disabled-elt="button" hx-indicator="#spinner">
    <input type="hidden" name="conversation_id" id="conversation_id"
           value="__CONVERSATION_ID__">
    <input type="text" name="request" required autofocus
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
</main>
<footer>
  Data from the PaperLane catalog snapshot. Delivery is free from 3,000.00;
  otherwise 150.00. VAT is charged on goods plus delivery.
</footer>
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
