"""The page must not depend on any host but this one.

The single page is htmx-only: the form carries ``hx-post`` and no ``method`` or
``action``. If the script never loads, the browser falls back to a plain ``GET``
of the current URL, so the failure is not an error the user can see — the page
merely reloads with the input cleared. The JSON API keeps answering, which is
what makes it easy to miss: every curl-based check passes while a human is
looking at a form that does nothing.

That is why htmx is vendored into the package instead of loaded from a CDN.
These tests hold both halves of the property, with no network available:

* the page names no external host, so it cannot regress to a CDN reference;
* the bytes it asks for are served from this origin, byte for byte.

The hash assertion is deliberate. It is the same SHA-384 the page previously
carried as its Subresource Integrity value, so it proves the vendored file is
the artefact that used to be fetched from the CDN rather than a lookalike.
"""

from __future__ import annotations

import base64
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from paperlane import ui
from paperlane.api import create_app

#: The SRI value the page carried while it still loaded htmx from unpkg.
HTMX_1_9_12_SHA384 = "ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# The page is self-contained
# ---------------------------------------------------------------------------


class TestPageIsSelfContained:
    def test_page_names_no_external_host(self) -> None:
        """No absolute URL anywhere in the markup.

        Scoped to ``PAGE`` rather than the module, because the module is allowed
        to *explain* the old CDN URL in a comment.
        """
        absolute = re.findall(r"""(?:src|href|action)\s*=\s*["']https?://[^"']+""", ui.PAGE)
        assert absolute == [], (
            "the page must not reference an external origin; it is served on "
            f"hosts without internet access: {absolute}"
        )

    def test_page_loads_htmx_from_this_origin(self) -> None:
        assert '<script src="/static/htmx.min.js"></script>' in ui.PAGE

    def test_page_is_still_htmx_only(self) -> None:
        """The claim the vendoring rests on.

        If a ``method`` or ``action`` were added to the form, a failed script
        load would submit to the server instead of reloading the page, and the
        reasoning in ``ui.py`` and ``VENDOR.md`` would need revisiting. Asserting
        it keeps the justification honest rather than letting it drift.
        """
        form = re.search(r"<form\b[^>]*>", ui.PAGE)
        assert form is not None
        tag = form.group(0)
        assert "hx-post" in tag
        assert "method=" not in tag
        assert "action=" not in tag


# ---------------------------------------------------------------------------
# The asset is really there, and is really served
# ---------------------------------------------------------------------------


class TestVendoredAsset:
    def test_asset_is_present_and_not_a_stub(self) -> None:
        assert ui.HTMX_ASSET.is_file(), (
            f"{ui.HTMX_ASSET} is missing; the page would load no script at all"
        )
        assert ui.HTMX_ASSET.stat().st_size > 20_000

    def test_route_serves_the_exact_bytes(self, client: TestClient) -> None:
        response = client.get("/static/htmx.min.js")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/javascript")
        assert response.content == ui.HTMX_ASSET.read_bytes()

    def test_route_is_cached_but_not_forever(self, client: TestClient) -> None:
        """A long cache on a versioned asset is safe; immutable is not.

        If an upgrade to htmx shipped under the same path, ``immutable`` would
        leave a browser on the old build indefinitely.
        """
        response = client.get("/static/htmx.min.js")
        cache_control = response.headers.get("cache-control", "")
        assert "max-age=" in cache_control
        assert "immutable" not in cache_control

    def test_route_is_not_advertised_in_the_api_schema(self, client: TestClient) -> None:
        """A static asset is not part of the documented API."""
        assert "/static/htmx.min.js" not in client.get("/openapi.json").json()["paths"]

    def test_referenced_asset_is_the_file_that_was_vendored(self, client: TestClient) -> None:
        """The page's script src resolves to the same bytes the test asserts."""
        page = client.get("/").text
        src = re.search(r'<script src="([^"]+htmx[^"]*)"', page)
        assert src is not None
        served = client.get(src.group(1))
        assert served.status_code == 200
        digest = base64.b64encode(hashlib.sha384(served.content).digest()).decode()
        assert digest == HTMX_1_9_12_SHA384


class TestVendoringProvenance:
    def test_documented_hash_matches_the_shipped_file(self) -> None:
        """``VENDOR.md`` must describe the bytes that are actually here.

        A stale provenance note is worse than none: it invites someone to verify
        a hash that no longer applies and conclude the file is correct.
        """
        note = (ui.HTMX_ASSET.parent / "VENDOR.md").read_text(encoding="utf-8")
        assert HTMX_1_9_12_SHA384 in note

        digest = base64.b64encode(hashlib.sha384(ui.HTMX_ASSET.read_bytes()).digest()).decode()
        assert digest == HTMX_1_9_12_SHA384, (
            "the shipped htmx build is not the one VENDOR.md describes; "
            "either restore the vendored bytes or update VENDOR.md and the SRI constant"
        )
