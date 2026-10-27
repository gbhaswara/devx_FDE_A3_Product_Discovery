# Vendored assets

## `htmx.min.js`

| | |
|---|---|
| Version | 1.9.12 |
| Source | `https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js` |
| Fetched | 2026-10-27 |
| Size | 48,101 bytes |
| SHA-384 (base64) | `ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2` |

The hash is the same one the page previously carried as its Subresource
Integrity value, so these bytes are provably the file that was being loaded
from the CDN before it was vendored — not a re-download of unknown provenance.

**Why it is here.** The page is htmx-only: the form carries `hx-post` and no
`method` or `action`, and `POST /ask` returns an HTML fragment rather than a
document. With no `htmx.js` there is no request at all — the browser falls back
to a plain `GET` of the current URL, and the page reloads with the input cleared.
Loading that script from `unpkg.com` therefore made the interface depend on
internet access while the rest of the system is deliberately offline: the tests,
the evaluation and the CLI need no network. Serving it from this package removes
that dependency, so the page works on an air-gapped or CDN-blocked host.

It is served by `GET /static/htmx.min.js` (`api.py`) and referenced by the page
in `ui.py`. `tests/test_ui_offline.py` asserts both halves — that the page names
no external host, and that the route returns these exact bytes.

## Licence

htmx is distributed under the Zero-Clause BSD licence:

```
Zero-Clause BSD
=============

Permission to use, copy, modify, and/or distribute this software for
any purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL
WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE
FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```
