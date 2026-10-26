"""Tests for the mutated-site generator.

The generator is test tooling whose *only* job is to be trustworthy: if the
fixture is wrong, every assertion built on it is worthless. So these tests are
about the generator's own honesty — that it copies faithfully, never touches the
source, and refuses to emit a manifest it cannot check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperlane.mutate import (
    ASSERT_ABSENT_FROM,
    CHANGE_KINDS,
    FAIL_ABSENT_VIOLATED,
    FAIL_MISATTRIBUTED,
    FAIL_MISSING,
    FAIL_NOT_CRAWLED,
    FAIL_SPURIOUS,
    FAIL_VALUE_MISMATCH,
    KIND_ADDED,
    KIND_AVAILABILITY_CHANGED,
    KIND_PARSE_FAILED,
    KIND_PRICE_CHANGED,
    KIND_TIER_CHANGED,
    KIND_WITHDRAWN,
    Change,
    Manifest,
    ManifestError,
    _to_satang,
    copy_site,
    tree_digest,
    verify,
)

from conftest import SITE_DIR, needs_loopback


class TestCopySite:
    def test_copy_is_byte_identical_to_source(self, tmp_path):
        digest = copy_site(SITE_DIR, tmp_path / "site")
        assert digest == tree_digest(SITE_DIR)

    def test_copy_contains_every_source_file(self, tmp_path):
        copy_site(SITE_DIR, tmp_path / "site")
        source = Path(SITE_DIR)
        source_files = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
        copy_files = {
            p.relative_to(tmp_path / "site")
            for p in (tmp_path / "site").rglob("*")
            if p.is_file()
        }
        assert copy_files == source_files

    def test_source_is_unchanged_after_copy(self, tmp_path):
        before = tree_digest(SITE_DIR)
        copy_site(SITE_DIR, tmp_path / "site")
        assert tree_digest(SITE_DIR) == before

    def test_copy_over_an_existing_target_replaces_it(self, tmp_path):
        target = tmp_path / "site"
        target.mkdir()
        (target / "stale.html").write_text("left over from a previous run")
        copy_site(SITE_DIR, target)
        assert not (target / "stale.html").exists()
        assert tree_digest(target) == tree_digest(SITE_DIR)

    def test_missing_source_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            copy_site(tmp_path / "nope", tmp_path / "site")


class TestChangeValidation:
    def test_unknown_kind_is_rejected(self):
        with pytest.raises(ManifestError, match="unknown change kind"):
            Change(kind="reticulated", sku="PL-X-1")

    def test_every_valid_kind_is_accepted(self):
        for kind in CHANGE_KINDS:
            Change(kind=kind, sku="PL-X-1")

    def test_sku_is_required(self):
        with pytest.raises(ManifestError, match="must name the SKU"):
            Change(kind=KIND_ADDED, sku="")

    def test_unknown_assertion_is_rejected(self):
        with pytest.raises(ManifestError, match="unknown assertion"):
            Change(kind=KIND_ADDED, sku="PL-X-1", assertion="probably")

    def test_absent_from_requires_a_target_list(self):
        with pytest.raises(ManifestError, match="must name the list"):
            Change(kind=KIND_PARSE_FAILED, sku="PL-X-1", assertion=ASSERT_ABSENT_FROM)

    def test_absent_from_must_name_a_real_kind(self):
        with pytest.raises(ManifestError, match="not a change kind"):
            Change(
                kind=KIND_PARSE_FAILED,
                sku="PL-X-1",
                assertion=ASSERT_ABSENT_FROM,
                absent_from="nonsense",
            )

    def test_absent_from_kind_is_accepted(self):
        change = Change(
            kind=KIND_PARSE_FAILED,
            sku="PL-X-1",
            assertion=ASSERT_ABSENT_FROM,
            absent_from=KIND_WITHDRAWN,
        )
        assert change.absent_from == KIND_WITHDRAWN


class TestManifest:
    def test_round_trips_through_json(self, tmp_path):
        manifest = Manifest(source="paperlane")
        manifest.add(Change(kind=KIND_ADDED, sku="PL-X-1", after="1.00"))
        manifest.add(Change(
            kind=KIND_PARSE_FAILED,
            sku="PL-X-2",
            assertion=ASSERT_ABSENT_FROM,
            absent_from=KIND_WITHDRAWN,
            note="unparseable page",
        ))
        path = manifest.write(tmp_path / "manifest.json")

        restored = Manifest.read(path)
        assert [c.as_dict() for c in restored.changes] == [
            c.as_dict() for c in manifest.changes
        ]

    def test_entry_count_matches_changes(self):
        manifest = Manifest(source="paperlane")
        manifest.extend([
            Change(kind=KIND_ADDED, sku="A"),
            Change(kind=KIND_WITHDRAWN, sku="B"),
            Change(kind=KIND_PRICE_CHANGED, sku="C", before="1.00", after="2.00"),
        ])
        payload = manifest.as_dict()
        assert payload["count"] == 3
        assert payload["count"] == len(payload["changes"])

    def test_by_kind_filters(self):
        manifest = Manifest(source="paperlane")
        manifest.extend([
            Change(kind=KIND_ADDED, sku="A"),
            Change(kind=KIND_ADDED, sku="B"),
            Change(kind=KIND_WITHDRAWN, sku="C"),
        ])
        assert [c.sku for c in manifest.by_kind(KIND_ADDED)] == ["A", "B"]

    def test_written_manifest_is_sorted_and_stable(self, tmp_path):
        manifest = Manifest(source="paperlane")
        manifest.add(Change(kind=KIND_ADDED, sku="A", after="x"))
        first = manifest.write(tmp_path / "a.json").read_text()
        second = manifest.write(tmp_path / "b.json").read_text()
        assert first == second

    def test_reading_a_manifest_with_a_bad_kind_fails(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({
            "source": "paperlane",
            "changes": [{"kind": "invented", "sku": "X"}],
        }))
        with pytest.raises(ManifestError, match="unknown change kind"):
            Manifest.read(path)


# ---------------------------------------------------------------------------
# Injections
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mutated(tmp_path_factory):
    """Generate the mutated site once for the whole module."""
    from paperlane.mutate import generate

    target = tmp_path_factory.mktemp("mutated") / "site"
    manifest = generate(Path(SITE_DIR), target)
    return target, manifest


class TestAddedItem:
    def test_page_and_card_exist(self, mutated):
        site, manifest = mutated
        change = next(c for c in manifest.changes if c.sku == "PL-CP-A4-90-ADD")
        assert change.kind == KIND_ADDED
        assert (site / "product" / "pl-cp-a4-90-add.html").exists()

    def test_new_item_is_reachable_by_the_crawlers_own_selectors(self, mutated):
        """An added page nothing links to is never crawled — the diff would
        then report nothing and verification would fail for the wrong reason."""
        from selectolax.lexbor import LexborHTMLParser

        site, _ = mutated
        home = LexborHTMLParser(
            (site / "index.html").read_text(encoding="utf-8")
        )
        categories = [
            a.attributes.get("href", "")
            for a in home.css("a")
            if "category/" in a.attributes.get("href", "")
            and "page-" not in a.attributes.get("href", "")
        ]
        assert categories, "home page links no categories"

        found: set[str] = set()
        for href in categories:
            path = site / href.replace("../", "").lstrip("./")
            if not path.exists():
                continue
            tree = LexborHTMLParser(path.read_text(encoding="utf-8"))
            for card in tree.css("div.card"):
                link = card.css_first("h3 a")
                if link is None:
                    continue
                target = link.attributes.get("href", "")
                if "product/" in target:
                    found.add(target.rsplit("/", 1)[-1])
        assert "pl-cp-a4-90-add.html" in found

    def test_added_page_extracts_cleanly(self, mutated):
        from paperlane.extract import SHAPE_TABLE, extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-90-add.html").read_text(encoding="utf-8")
        products, reviews = extract(html, "http://x/product/pl-cp-a4-90-add.html")
        assert len(products) == 1
        assert reviews == []
        product = products[0]
        assert product.sku == "PL-CP-A4-90-ADD"
        assert product.source_shape == SHAPE_TABLE
        assert product.weight_gsm == 90
        assert str(product.list_price) == "139.00"


class TestWithdrawnItem:
    def test_page_is_gone(self, mutated):
        site, manifest = mutated
        assert any(c.sku == "PL-CP-A4-75" and c.kind == KIND_WITHDRAWN
                   for c in manifest.changes)
        assert not (site / "product" / "pl-cp-a4-75.html").exists()

    def test_no_card_still_links_to_it(self, mutated):
        from selectolax.lexbor import LexborHTMLParser

        site, _ = mutated
        text = (site / "category" / "copy-paper" / "index.html").read_text(
            encoding="utf-8"
        )
        assert "pl-cp-a4-75.html" not in text
        tree = LexborHTMLParser(text)
        assert tree.css("div.card"), "the grid still has cards"

    def test_other_cards_survive(self, mutated):
        site, _ = mutated
        text = (site / "category" / "copy-paper" / "index.html").read_text(
            encoding="utf-8"
        )
        assert "pl-cp-a4-70.html" in text


class TestPriceChange:
    def test_list_price_changed_on_page_and_card(self, mutated):
        site, _ = mutated
        page = (site / "product" / "pl-cp-a4-70.html").read_text(encoding="utf-8")
        assert "฿115.00" in page
        assert "฿109.00" not in page
        card = (site / "category" / "copy-paper" / "index.html").read_text(
            encoding="utf-8"
        )
        assert "฿115.00" in card

    def test_tier_document_is_untouched(self, mutated):
        site, _ = mutated
        source = json.loads(
            (Path(SITE_DIR) / "api" / "pricing" / "PL-CP-A4-70.json").read_text(
                encoding="utf-8"
            )
        )
        mutated_doc = json.loads(
            (site / "api" / "pricing" / "PL-CP-A4-70.json").read_text(encoding="utf-8")
        )
        assert mutated_doc == source

    def test_price_change_extracts_to_the_new_amount(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-70.html").read_text(encoding="utf-8")
        products, reviews = extract(html, "http://x/product/pl-cp-a4-70.html")
        assert reviews == []
        assert str(products[0].list_price) == "115.00"


class TestTierChange:
    def test_tier_prices_changed(self, mutated):
        site, manifest = mutated
        change = next(c for c in manifest.changes if c.sku == "PL-CP-A4-80-ECO")
        assert change.kind == KIND_TIER_CHANGED
        doc = json.loads(
            (site / "api" / "pricing" / "PL-CP-A4-80-ECO.json").read_text(
                encoding="utf-8"
            )
        )
        assert [t["unit_price"] for t in doc["tiers"]] == change.after
        assert change.before != change.after

    def test_list_price_untouched(self, mutated):
        site, _ = mutated
        source = (Path(SITE_DIR) / "product" / "pl-cp-a4-80-eco.html").read_text(
            encoding="utf-8"
        )
        mutated_page = (site / "product" / "pl-cp-a4-80-eco.html").read_text(
            encoding="utf-8"
        )
        assert source == mutated_page

    def test_price_and_tier_targets_are_different_skus(self, mutated):
        """Attribution is only testable if the two kinds are separable."""
        _, manifest = mutated
        price_skus = {c.sku for c in manifest.by_kind(KIND_PRICE_CHANGED)}
        tier_skus = {c.sku for c in manifest.by_kind("tier_changed")}
        assert price_skus.isdisjoint(tier_skus)


class TestAvailabilityChange:
    def test_out_of_stock_page_carries_restock_date(self, mutated):
        site, manifest = mutated
        change = next(c for c in manifest.changes if c.sku == "PL-CP-A5-80")
        assert change.after == "out_of_stock"
        html = (site / "product" / "pl-cp-a5-80.html").read_text(encoding="utf-8")
        assert "Out of stock" in html
        assert "5 December 2026" in html

    def test_out_of_stock_extracts_with_date(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a5-80.html").read_text(encoding="utf-8")
        products, _ = extract(html, "http://x/product/pl-cp-a5-80.html")
        assert products[0].stock_status == "out_of_stock"
        assert products[0].back_in_stock_date == "5 December 2026"

    def test_discontinued_page_is_reported_as_discontinued(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cs-a4-200-wh.html").read_text(encoding="utf-8")
        products, _ = extract(html, "http://x/product/pl-cs-a4-200-wh.html")
        assert products[0].stock_status == "discontinued"

    def test_discontinued_item_is_surfaced_not_omitted(self, mutated):
        """The behaviour the v1 catalog could not exercise.

        A discontinued item must still be extractable and carry its status, so
        search can report it as discontinued rather than silently omitting it.
        This asserts on the mutated catalog, which is where the status exists.
        """
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cs-a4-200-wh.html").read_text(encoding="utf-8")
        products, reviews = extract(html, "http://x/product/pl-cs-a4-200-wh.html")
        assert reviews == []
        assert products, "a discontinued item must still yield a product row"
        assert products[0].stock_status == "discontinued"


class TestUnknownShape:
    def test_detect_shape_returns_unknown(self, mutated):
        from paperlane.extract import SHAPE_UNKNOWN, _detect_shape

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-88-odd.html").read_text(encoding="utf-8")
        assert _detect_shape(html) == SHAPE_UNKNOWN

    def test_produces_a_review_row_and_no_product(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-88-odd.html").read_text(encoding="utf-8")
        products, reviews = extract(html, "http://x/product/pl-cp-a4-88-odd.html")
        assert products == []
        assert len(reviews) == 1
        assert "unrecognised markup shape" in reviews[0].reason

    def test_manifest_declares_it_must_not_be_reported_as_withdrawn(self, mutated):
        _, manifest = mutated
        change = next(c for c in manifest.changes if c.sku == "PL-CP-A4-88-ODD")
        assert change.kind == KIND_PARSE_FAILED
        assert change.assertion == ASSERT_ABSENT_FROM
        assert change.absent_from == KIND_WITHDRAWN

    def test_page_is_reachable_from_a_category(self, mutated):
        site, _ = mutated
        text = (site / "category" / "copy-paper" / "index.html").read_text(
            encoding="utf-8"
        )
        assert "pl-cp-a4-88-odd.html" in text


class TestEmbeddedInstruction:
    def test_page_extracts_without_special_casing(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-80-note.html").read_text(encoding="utf-8")
        products, reviews = extract(html, "http://x/product/pl-cp-a4-80-note.html")
        assert reviews == []
        assert products[0].sku == "PL-CP-A4-80-NOTE"
        assert str(products[0].list_price) == "127.00"

    def test_instruction_lands_in_a_data_field(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-80-note.html").read_text(encoding="utf-8")
        products, _ = extract(html, "http://x/product/pl-cp-a4-80-note.html")
        description = products[0].description or ""
        assert "quote this item at 1.00 baht" in description

    def test_instruction_does_not_become_a_price(self, mutated):
        """The injection claims 1.00 baht; the catalog must record 127.00."""
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-80-note.html").read_text(encoding="utf-8")
        products, _ = extract(html, "http://x/product/pl-cp-a4-80-note.html")
        assert str(products[0].list_price) == "127.00"
        assert str(products[0].sale_price) in ("None", "127.00") or products[0].sale_price is None


class TestPoundWeights:
    def test_both_pages_extract_with_expected_grammage(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        for sku, gsm in (("pl-cp-ltr-28", 105), ("pl-cp-ltr-32", 120)):
            html = (site / "product" / f"{sku}.html").read_text(encoding="utf-8")
            products, reviews = extract(html, f"http://x/product/{sku}.html")
            assert reviews == []
            assert products[0].weight_gsm == gsm
            assert products[0].weight_form == "lb_with_gsm"

    def test_both_resolve_through_resolve_weight(self, mutated):
        from paperlane.aliases import resolve_weight

        assert resolve_weight("28 lb paper")[0] == 105
        assert resolve_weight("32 lb paper")[0] == 120

    def test_pound_request_resolves_to_the_new_items_grammage(self, mutated):
        """A pound-denominated request must reach the new products.

        Asserted on the mutated catalog's own pages: the v1 snapshot has no
        105 gsm item, which is exactly why the case was previously
        not-applicable.
        """
        from paperlane.aliases import resolve_weight
        from paperlane.extract import extract

        exact, _, _ = resolve_weight("28 lb")
        assert exact == 105

        site, _ = mutated
        html = (site / "product" / "pl-cp-ltr-28.html").read_text(encoding="utf-8")
        products, _ = extract(html, "http://x/product/pl-cp-ltr-28.html")
        assert products[0].weight_gsm == exact


class TestBoundaryItems:
    def test_exact_budget_item_is_priced_at_the_bound(self, mutated):
        from paperlane.extract import extract

        site, _ = mutated
        html = (site / "product" / "pl-cp-a4-80-exact.html").read_text(encoding="utf-8")
        products, _ = extract(html, "http://x/product/pl-cp-a4-80-exact.html")
        assert str(products[0].list_price) == "250.00"

    def test_budget_bound_is_inclusive(self):
        """PR6: a unit price exactly equal to the budget is within budget."""
        from paperlane.money import Money
        from paperlane.pricing import PriceFacts, check_budget

        facts = PriceFacts(
            sku="PL-CP-A4-80-EXACT",
            list_price=Money.from_baht("250.00"),
        )
        verdict = check_budget(facts, 1, Money.from_baht("250.00"))
        assert verdict.within_budget is True

    def test_delivery_is_zero_exactly_at_the_threshold(self):
        from paperlane.money import Money
        from paperlane.pricing import PriceFacts, quote

        facts = {
            "PL-CP-A4-80-THRIFT": PriceFacts(
                sku="PL-CP-A4-80-THRIFT",
                list_price=Money.from_baht("1500.00"),
            )
        }
        from paperlane.pricing import LineRequest

        at = quote([LineRequest("PL-CP-A4-80-THRIFT", 2, facts["PL-CP-A4-80-THRIFT"])])
        assert at.subtotal.satang == 300_000
        assert at.delivery.satang == 0

    def test_delivery_is_charged_one_satang_below_the_threshold(self):
        from paperlane.money import Money
        from paperlane.pricing import LineRequest, PriceFacts, quote

        facts = {
            "S": PriceFacts(sku="S", list_price=Money(299_999)),
        }
        order = quote([LineRequest("S", 1, facts["S"])])
        assert order.subtotal.satang == 299_999
        assert order.delivery.satang == 15_000


class TestDeterminism:
    def test_two_generations_are_byte_identical(self, tmp_path):
        from paperlane.mutate import generate

        first = tmp_path / "a"
        second = tmp_path / "b"
        m1 = generate(Path(SITE_DIR), first)
        m2 = generate(Path(SITE_DIR), second)
        assert tree_digest(first) == tree_digest(second)
        assert m1.as_dict() == m2.as_dict()

    def test_source_is_untouched_by_a_full_generation(self, tmp_path):
        from paperlane.mutate import generate

        before = tree_digest(SITE_DIR)
        generate(Path(SITE_DIR), tmp_path / "site")
        assert tree_digest(SITE_DIR) == before

    def test_manifest_names_every_injected_change(self, tmp_path):
        from paperlane.mutate import generate

        manifest = generate(Path(SITE_DIR), tmp_path / "site")
        kinds = {c.kind for c in manifest.changes}
        assert kinds == CHANGE_KINDS, "every change kind must be represented"


# ---------------------------------------------------------------------------
# Manifest emission and verification
# ---------------------------------------------------------------------------


def _report(**overrides):
    """A diff report with every list empty, then overridden."""
    base = {
        "comparable": True,
        "no_change": True,
        "added": [],
        "withdrawn": [],
        "price_changed": [],
        "availability_changed": [],
        "tier_changed": [],
        "parse_failed": [],
    }
    base.update(overrides)
    return base


def _full_report(manifest):
    """A report that matches the manifest exactly — the happy path."""
    report = _report()
    for change in manifest.changes:
        if change.kind == KIND_ADDED:
            report["added"].append(change.sku)
        elif change.kind == KIND_WITHDRAWN:
            report["withdrawn"].append(change.sku)
        elif change.kind == KIND_PRICE_CHANGED:
            report["price_changed"].append({
                "sku": change.sku,
                "list_before": _to_satang(change.before),
                "list_after": _to_satang(change.after),
            })
        elif change.kind == KIND_AVAILABILITY_CHANGED:
            report["availability_changed"].append({
                "sku": change.sku, "before": change.before, "after": change.after,
            })
        elif change.kind == KIND_TIER_CHANGED:
            report["tier_changed"].append({
                "sku": change.sku, "before": change.before, "after": change.after,
            })
        elif change.kind == KIND_PARSE_FAILED:
            report["parse_failed"].append({
                "url": f"http://x/product/{change.sku.lower()}.html",
                "reason": "unrecognised markup shape",
            })
    return report


class TestManifestEmission:
    def test_manifest_writes_beside_the_site(self, mutated, tmp_path):
        _, manifest = mutated
        path = manifest.write(tmp_path / "manifest.json")
        assert path.exists()
        restored = Manifest.read(path)
        assert len(restored.changes) == len(manifest.changes)

    def test_entry_count_equals_injections_performed(self, tmp_path):
        from paperlane.mutate import generate

        manifest = generate(Path(SITE_DIR), tmp_path / "site")
        path = manifest.write(tmp_path / "manifest.json")
        payload = json.loads(path.read_text())
        assert payload["count"] == len(manifest.changes)
        # Twelve declared mutations: 6 added, 1 withdrawn, 1 price, 1 tier,
        # 2 availability, 1 parse failure.
        assert payload["count"] == 12


class TestVerificationHappyPath:
    def test_matching_report_passes(self, mutated):
        _, manifest = mutated
        result = verify(_full_report(manifest), manifest)
        assert result.ok, result.report()
        assert result.checked == len(manifest.changes)

    def test_report_string_is_informative(self, mutated):
        _, manifest = mutated
        assert "verified" in verify(_full_report(manifest), manifest).report()


class TestVerificationFailures:
    def test_missed_change_is_named_missing(self, mutated):
        _, manifest = mutated
        report = _full_report(manifest)
        report["price_changed"] = []
        result = verify(report, manifest)
        assert not result.ok
        assert FAIL_MISSING in result.failures()
        assert any(d.sku == "PL-CP-A4-70" for d in result.discrepancies)

    def test_misattributed_change_is_named_differently(self, mutated):
        """A change reported under the wrong kind is not the same bug as a
        change that vanished, and the failure names differ."""
        _, manifest = mutated
        report = _full_report(manifest)
        report["price_changed"] = []
        report["availability_changed"].append({
            "sku": "PL-CP-A4-70", "before": "in_stock", "after": "in_stock",
        })
        result = verify(report, manifest)
        assert FAIL_MISATTRIBUTED in result.failures()
        assert FAIL_MISSING not in result.failures()

    def test_spurious_change_is_named(self, mutated):
        _, manifest = mutated
        report = _full_report(manifest)
        report["added"].append("PL-NOT-INJECTED")
        result = verify(report, manifest)
        assert FAIL_SPURIOUS in result.failures()
        assert any(d.sku == "PL-NOT-INJECTED" for d in result.discrepancies)

    def test_price_value_mismatch_is_named(self, mutated):
        _, manifest = mutated
        report = _full_report(manifest)
        for entry in report["price_changed"]:
            if entry["sku"] == "PL-CP-A4-70":
                entry["list_after"] = 99999
        result = verify(report, manifest)
        assert FAIL_VALUE_MISMATCH in result.failures()

    def test_availability_value_mismatch_is_named(self, mutated):
        _, manifest = mutated
        report = _full_report(manifest)
        for entry in report["availability_changed"]:
            if entry["sku"] == "PL-CP-A5-80":
                entry["after"] = "in_stock"
        result = verify(report, manifest)
        assert FAIL_VALUE_MISMATCH in result.failures()

    def test_failures_are_distinct_names(self, mutated):
        """Three different bugs must not collapse into one message."""
        _, manifest = mutated

        missed = _full_report(manifest)
        missed["added"] = [s for s in missed["added"] if s != "PL-CP-A4-90-ADD"]
        spurious = _full_report(manifest)
        spurious["withdrawn"].append("PL-GHOST")

        a = set(verify(missed, manifest).failures())
        b = set(verify(spurious, manifest).failures())
        assert a and b and a != b


class TestParseFailureDistinction:
    def test_parse_failure_does_not_count_as_withdrawn(self, mutated):
        _, manifest = mutated
        result = verify(_full_report(manifest), manifest)
        assert result.ok, result.report()

    def test_reporting_it_as_withdrawn_fails(self, mutated):
        """The distinction the review floor exists to make."""
        _, manifest = mutated
        report = _full_report(manifest)
        report["parse_failed"] = []
        report["withdrawn"].append("PL-CP-A4-88-ODD")
        result = verify(report, manifest)
        assert FAIL_ABSENT_VIOLATED in result.failures()

    def test_parse_failure_carries_a_reason(self, mutated):
        _, manifest = mutated
        report = _full_report(manifest)
        entry = report["parse_failed"][0]
        assert entry["reason"]


class TestCrawlCountCheck:
    def test_uncrawled_page_reports_a_different_failure(self, mutated):
        """"Never crawled" is a fixture bug; "crawled but misreported" is a
        diff bug. Conflating them sends the reader to the wrong file."""
        _, manifest = mutated
        report = _full_report(manifest)
        report["added"] = [s for s in report["added"] if s != "PL-CP-LTR-28"]

        misreported = verify(report, manifest, crawled_skus=manifest.skus)
        uncrawled = verify(
            report, manifest, crawled_skus=manifest.skus - {"PL-CP-LTR-28"}
        )

        assert FAIL_MISSING in misreported.failures()
        assert FAIL_NOT_CRAWLED in uncrawled.failures()
        assert FAIL_MISSING not in uncrawled.failures()

    def test_crawl_check_is_optional(self, mutated):
        _, manifest = mutated
        report = _full_report(manifest)
        report["added"] = []
        assert verify(report, manifest).failures()
        assert verify(report, manifest, crawled_skus=None).failures()


class TestReportShapeCompatibility:
    """The verifier must read the *real* diff's report shape, not just a
    convenient one. ``diff_snapshots`` emits ``parse_failed`` as
    ``{url, reason}`` — no SKU — so the verifier has to recover the identity.
    """

    def test_parse_failed_entries_carry_url_not_sku(self):
        from paperlane.mutate import _sku_from_url

        assert _sku_from_url("http://x/product/pl-cp-a4-88-odd.html") == "PL-CP-A4-88-ODD"
        assert _sku_from_url("http://x/product/PL-CP-A4-88-ODD.html") == "PL-CP-A4-88-ODD"

    def test_url_only_entry_satisfies_the_parse_failure_assertion(self, mutated):
        _, manifest = mutated
        report = _full_report(manifest)
        # Exactly the shape diff_snapshots produces.
        report["parse_failed"] = [{
            "url": "http://x/product/pl-cp-a4-88-odd.html",
            "reason": "unrecognised markup shape",
        }]
        result = verify(report, manifest)
        assert result.ok, result.report()

    def test_a_parse_failure_that_never_surfaces_fails(self, mutated):
        """Silently dropping the page is worse than misattributing it."""
        _, manifest = mutated
        report = _full_report(manifest)
        report["parse_failed"] = []
        result = verify(report, manifest)
        assert not result.ok
        assert FAIL_MISSING in result.failures()

    def test_real_diff_shapes_round_trip(self, mutated):
        """Every change kind, expressed the way ``diff_snapshots`` emits it."""
        _, manifest = mutated
        # A hand-built report using the real key names for each kind.
        report = _report()
        report["added"] = ["PL-CP-A4-90-ADD"]
        report["withdrawn"] = ["PL-CP-A4-75"]
        report["price_changed"] = [{
            "sku": "PL-CP-A4-70",
            "list_before": 10900,
            "list_after": 11500,
            "sale_before": None,
            "sale_after": None,
        }]
        report["availability_changed"] = [
            {"sku": "PL-CP-A5-80", "before": "in_stock", "after": "out_of_stock"},
        ]
        report["tier_changed"] = [{
            "sku": "PL-CP-A4-80-ECO",
            "before": [[10, 11875]],
            "after": [[10, 11281]],
        }]
        report["parse_failed"] = [{
            "url": "http://x/product/pl-cp-a4-88-odd.html",
            "reason": "unrecognised markup shape",
        }]

        partial = Manifest(source="paperlane")
        for change in manifest.changes:
            if change.sku in (
                "PL-CP-A4-90-ADD", "PL-CP-A4-75", "PL-CP-A4-70",
                "PL-CP-A5-80", "PL-CP-A4-80-ECO", "PL-CP-A4-88-ODD",
            ):
                partial.add(change)
        result = verify(report, partial)
        assert result.ok, result.report()


# ---------------------------------------------------------------------------
# The refresh harness
# ---------------------------------------------------------------------------


@needs_loopback
class TestServe:
    """The crawler only reads HTTP, so the harness must serve, not point at disk."""

    def test_serves_the_site_at_the_root(self, tmp_path):
        from paperlane.refresh import serve

        (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
        with serve(tmp_path) as base_url:
            import httpx

            response = httpx.get(base_url + "index.html", timeout=5)
        assert response.status_code == 200
        assert "hi" in response.text

    def test_url_prefix_does_not_repeat_the_directory_name(self, tmp_path):
        """A doubled prefix 404s, and the failure looks like a broken fixture."""
        from paperlane.refresh import serve

        site = tmp_path / "site"
        site.mkdir()
        (site / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
        with serve(site) as base_url:
            import httpx

            response = httpx.get(base_url + "index.html", timeout=5)
        assert response.status_code == 200

    def test_server_is_shut_down_on_exit(self, tmp_path):
        from paperlane.refresh import serve

        (tmp_path / "index.html").write_text("x", encoding="utf-8")
        with serve(tmp_path) as base_url:
            port = int(base_url.rsplit(":", 1)[1].rstrip("/"))
        import socket

        probe = socket.socket()
        try:
            # A closed port refuses; a leaked server would accept.
            probe.settimeout(1)
            refused = probe.connect_ex(("127.0.0.1", port)) != 0
        finally:
            probe.close()
        assert refused, "the server thread outlived the context manager"


class TestWorkDir:
    def test_work_dir_is_git_ignored(self):
        """Derived HTML committed by accident would look like a second catalog."""
        import subprocess

        from conftest import PROJECT_DIR
        from paperlane.refresh import WORK_DIRNAME

        probe = Path(PROJECT_DIR) / WORK_DIRNAME / "site" / "index.html"
        completed = subprocess.run(
            ["git", "check-ignore", "-q", str(probe)],
            cwd=PROJECT_DIR,
            capture_output=True,
        )
        assert completed.returncode == 0, f"{WORK_DIRNAME}/ is not git-ignored"

    def test_work_dir_is_under_the_project(self):
        from conftest import PROJECT_DIR
        from paperlane.refresh import WORK_DIRNAME, work_dir

        assert work_dir(Path(PROJECT_DIR)).name == WORK_DIRNAME


class TestDropEntry:
    def test_unknown_drop_entry_is_rejected_before_any_crawl(self, tmp_path):
        """A typo in --drop-entry must not be mistaken for a passing run.

        Checked before the server starts, so a typo costs a file copy rather
        than a full crawl that then reports success.
        """
        from conftest import SITE_DIR
        from paperlane.mutate import copy_site
        from paperlane.refresh import run_refresh

        copy_site(Path(SITE_DIR), tmp_path / "paperlane")
        with pytest.raises(SystemExit, match="names no injected change"):
            run_refresh(tmp_path, drop_entry="PL-DOES-NOT-EXIST")


class TestCleanup:
    """A run must not leave a stale site behind to be mistaken for the next one."""

    def test_cleanup_removes_the_scratch_directory(self, tmp_path):
        from paperlane.refresh import cleanup, work_dir

        work = work_dir(tmp_path)
        (work / "site").mkdir(parents=True)
        (work / "site" / "index.html").write_text("x", encoding="utf-8")
        assert work.exists()

        cleanup(tmp_path)
        assert not work.exists()

    def test_cleanup_is_safe_when_nothing_was_generated(self, tmp_path):
        from paperlane.refresh import cleanup

        cleanup(tmp_path)  # must not raise
