# Refresh verification

How the refresh path is *demonstrated* rather than asserted.

Code: `src/paperlane/mutate.py`, `refresh.py`, `refresh_cli.py`. Tests:
`tests/test_mutate.py`. Command: `./run.sh verify-refresh`.

---

## The problem this solves

`./run.sh diff` reports six change kinds: added, withdrawn, price changed,
availability changed, tier changed, and parse failed. On the committed catalog it
reports nothing — all six lists empty, `no_change: true`.

That is a weak claim. An empty report is equally consistent with three very
different implementations:

1. a diff that correctly found no changes;
2. a diff that read nothing at all and defaulted to empty;
3. a diff that read the wrong thing and found nothing because it looked in the
   wrong place.

The v1 catalog is a fixture with no adversity in it: every page parses, nothing
is discontinued, no page carries an injected instruction, and no price, tier or
availability has ever changed. So the refresh path could not be exercised, and
"the diff works" rested on reading the code.

This harness closes that gap by **manufacturing the adversity and declaring it in
advance**. It copies the site, injects a known set of changes, ingests the copy
into a throwaway snapshot, diffs that snapshot against the committed one, and
checks the report against the declaration.

---

## Running it

From the project root:

```bash
./run.sh verify-refresh
```

It takes about **55 seconds**: ~108 requests against a loopback copy at 2 req/s,
the crawler's own cap. No arguments, no server to start, no network access beyond
127.0.0.1.

Exit codes are distinct so a caller can tell the outcomes apart:

| Code | Meaning |
|---|---|
| 0 | Every declared change was reported under the correct kind |
| 1 | A discrepancy was found; the run names it and dumps the report as JSON |
| 2 | The run could not be performed at all (ingest failed, or `--drop-entry` named no injected change) |

Two flags exist:

```bash
./run.sh verify-refresh --keep                      # keep the generated site
./run.sh verify-refresh --drop-entry PL-CP-A4-70    # prove it can fail
```

`--drop-entry` is how the harness demonstrates it is not a rubber stamp. It
removes one change from the **manifest** after the injection has happened, so the
site still contains the change, the diff still reports it, and the verification
must reject it as undeclared:

```
$ ./run.sh verify-refresh --drop-entry PL-CP-A4-70
...
1 discrepancy(ies) across 11 checks:
  - [reported_but_not_injected] PL-CP-A4-70: reported under 'price_changed'
    but no such change was injected
$ echo $?
1
```

Suppressing the *expectation* rather than the *mutation* is deliberate: the crawl
and the diff run identically to a passing run, so the only difference is the
declaration, and the failure can only come from the comparison.

---

## What is injected, and why each one exists

Twelve changes across all six kinds. Each targets a distinct SKU, so a change can
be attributed to one injection rather than to a pile of edits (a price change and
an availability change on the same SKU would be indistinguishable in the report).

| # | Kind | SKU | What is done | Why it is needed |
|---|---|---|---|---|
| 1 | added | PL-CP-A4-90-ADD | New table-shape product page, plus a category card linking it | The `added` list has never been non-empty. An added page **no category links to is never crawled**, so the card matters as much as the page |
| 2 | withdrawn | PL-CP-A4-75 | Product page deleted, category card removed | The `withdrawn` list has never been non-empty. Removing only the page would leave a dangling card, which a real merchant's site would not have |
| 3 | price_changed | PL-CP-A4-70 | List price ฿109.00 → ฿115.00 on page and card; tier document untouched | Proves a list-price change is detected *and* distinguished from a tier change on the same item type |
| 4 | tier_changed | PL-CP-A4-80-ECO | Tier unit prices reduced 5%; list price untouched | The mirror of #3. Both are "the price changed", and conflating them would misreport where the change came from |
| 5 | availability_changed | PL-CP-A5-80 | In stock → out of stock, with a restock date | The catalog had 2 out-of-stock items but no *transition* to observe |
| 6 | availability_changed | PL-CS-A4-200-WH | In stock → discontinued | The v1 catalog has zero discontinued items, so the refusal path had no live data |
| 7 | parse_failed | PL-CP-A4-88-ODD | A page in markup none of the four shapes match | The review floor exists and is reachable but had **never been reached by a real page** |
| 8 | added | PL-CP-A4-80-NOTE | A page whose description carries an instruction addressed to an automated reader | The v1 catalog has no injection sample (0 of 36 pages). Written as plausible merchant copy, not a caricature |
| 9 | added | PL-CP-LTR-28 | 28 lb (105 gsm) letter product | The pound→grammage table has four rows; only 20 lb and 24 lb were stocked, so two rows were untestable |
| 10 | added | PL-CP-LTR-32 | 32 lb (120 gsm) letter product | Same, for the fourth row |
| 11 | added | PL-CP-A4-80-EXACT | Priced at exactly ฿250.00 | Makes the budget bound *exactly* reachable, so an exclusive comparison is detectable. The bound is inclusive (PR6) |
| 12 | added | PL-CP-A4-80-THRIFT | Priced at ฿1500.00 | Two units subtotal exactly ฿3000.00, the free-delivery threshold — and one satang below it must be charged |

Items 9–12 exist because a boundary that can never be hit is not being tested.

---

## What the verification proves

**Both directions.** Every manifest entry appears in the list its kind names, and
no list contains a SKU the manifest does not declare. Checking only the first
direction would pass a diff that reports everything plus hallucinations.

**Values, not just membership.** Where the manifest states a value — the new list
price, the new availability — the reported value must agree, compared in integer
satang so a rounding difference cannot pass as a match.

**Six named failures, not one message.** Each way the report can disagree with
the declaration has its own name, because they are different bugs with different
fixes:

| Failure | Meaning |
|---|---|
| `missing_from_report` | Declared, and the list is missing it — the diff read the change but dropped it |
| `reported_under_wrong_kind` | Declared under one kind, reported under another — an attribution bug |
| `reported_but_not_injected` | Reported with nothing declared — a spurious or duplicated entry |
| `reported_in_list_it_must_stay_out_of` | The parse-failure case, reported as something else |
| `page_not_reached_by_crawler` | The page was never crawled, so the diff was *right* to say nothing and the fixture is at fault |
| `reported_value_disagrees_with_manifest` | Right kind, wrong figure |

**A parse failure is not a withdrawal.** This is the distinction the review floor
exists to make, and it is checked in both halves: the page must appear in
`parse_failed`, **and** must not appear in `withdrawn`. A page that appears
nowhere at all is reported as missing, because silently dropping it is worse than
misattributing it.

**"Not reported" is distinguished from "never crawled".** The verifier is given
the SKUs the crawl actually reached, read from the snapshot it produced. Without
that, a fixture whose new page is unreachable looks exactly like a diff that
ignores new pages, and the reader is sent to the wrong file.

---

## What it does not prove

Stated plainly, because a verification section that only lists strengths is
advertising.

- **It does not prove the diff is complete for changes nobody injected.** Six
  kinds are represented, but a seventh kind the catalog might grow — say, a
  changed description — is not tested because it does not exist.
- **It does not exercise the model path.** The run is offline and model-free. The
  LLM is used only for criteria extraction, and none of these changes touch it.
- **It does not test the crawler's politeness, retries or error handling.** It
  crawls a loopback copy at the crawler's own 2 req/s cap. Those behaviours are in
  `tests/test_crawl.py`.
- **It does not prove the assistant answers well.** It proves the *catalog* a
  refresh produces is the one the site describes. What the assistant does with it
  is `eval/results.md`.
- **The mutated site is not a realistic future catalog.** It is a fixture with
  deliberate adversity. A real refresh would carry changes nobody chose.
- **It cannot detect a change that is invisible in the snapshot.** If a site edit
  does not alter any stored column, the diff is correct to report nothing, and
  this harness would not notice the edit — correctly, but worth knowing.

---

## The second catalog

The mutated snapshot is also a second catalog the evaluation set can be scored
against. That is what makes four previously-inapplicable cases runnable: the v1
catalog has no discontinued item, no injection sample, and no 28 lb or 32 lb
product, and the mutated one has all four.

A case now names the catalog its requirement needs (`requires_catalog` in
`eval/cases.json`), and a run names the catalog it scored (`catalog` in the JSON
payload). See the "Second catalog" section of `eval/results.md` for both runs.

---

## Files and where the output goes

Everything generated goes to `.refresh-verification/` under the project root,
which is git-ignored:

```
.refresh-verification/
  site/              the mutated copy of the catalog site   (--keep only)
  mutated.duckdb     the snapshot ingested from it          (--keep only)
```

The **committed** snapshot at `data/catalog.duckdb` is read as the diff baseline
and is never written. `git status` is clean after a run, and a test asserts the
directory is ignored — derived HTML committed by accident would look like a
second catalog.

`--keep` leaves the generated site and snapshot in place for inspection. Without
it they are removed after verification, so a run leaves nothing behind. The
directory is git-ignored either way; the cleanup is about not finding a stale site
from a previous run and mistaking it for the current one.

---

## Determinism

Generation is deterministic: no timestamps, no randomness, no dict-ordering
dependence. Two generations of the same mutation produce byte-identical trees,
asserted by hashing every file. This matters because a verification failure must
never be blameable on the fixture having drifted.

The source site is never touched. Every write goes to the target directory, and
tests hash the source before and after a full generation.

---

## Adding a mutation

1. Write an `inject_*` function in `mutate.py` that edits the copy and returns a
   `Change` describing what it did. Build pages by substituting into a real
   page's shell (`_render_table_page`) rather than re-authoring markup, so the
   header and footer cannot drift from the real site.
2. Target a SKU no other injection touches, so attribution stays separable.
3. If the new page must be crawled, add a category card linking it — an
   unreachable page makes the verification fail for the wrong reason.
4. Call it from `generate()` and add it to the manifest.
5. Add tests to `tests/test_mutate.py` asserting both that the injection landed
   and that the manifest declares it.

`Change` rejects an unknown `kind` at construction, so a typo fails where it is
made rather than at verification.
