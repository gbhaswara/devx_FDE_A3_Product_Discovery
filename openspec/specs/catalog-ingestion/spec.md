# Catalog Ingestion Specification

## Purpose

Turns PaperLane's live website into a normalised, provenance-stamped catalog that the rest of the system can query, so that product facts come from the site rather than from a model or a human.

## Requirements

### Requirement: Crawl respects the site's rate limit

The crawler SHALL fetch pages over HTTP only, and SHALL NOT exceed the rate the site permits. The site's footer states a maximum of 2 requests per second and `robots.txt` sets `Crawl-delay: 1`.

#### Scenario: Sequential crawl within budget
- **WHEN** a full ingest runs against the site
- **THEN** no two requests are issued less than 1 second apart, and the crawl never exceeds 2 requests per second

#### Scenario: Local files are not used as a source
- **WHEN** the source location is given as a filesystem path rather than an HTTP base URL
- **THEN** the ingest fails with a clear error instead of reading files directly, because the site must be served over HTTP

### Requirement: Discovery finds every leaf SKU

The crawler SHALL discover all purchasable items (leaf SKUs), including SKUs that appear only as rows inside a product page rather than as their own page. For the reference site this is 72 leaf SKUs: 30 single-SKU pages plus 42 rows across 6 flyer pages.

#### Scenario: Variant rows are enumerated
- **WHEN** a flyer product page presents a table of variants
- **THEN** each variant row becomes its own catalog entry with its own SKU, not a single entry for the page

#### Scenario: Volume-pricing data is fetched for exactly the SKUs that have it
- **WHEN** ingestion completes
- **THEN** the count of retrieved volume-pricing documents equals the count of SKUs that advertise volume pricing, and no document exists for a SKU absent from the catalog

### Requirement: Four markup shapes are handled by a fallback ladder

Product specification markup is not uniform. The extractor SHALL attempt each known shape in turn and SHALL record which shape succeeded for each page, so that the same field can be read from differently-shaped pages.

#### Scenario: Each known shape is parsed
- **WHEN** pages using the variant table, the `<table>` spec block, the `<dl>` spec block, and prose-only description are ingested
- **THEN** all four yield the same normalised fields, and each page records the shape that produced its values

#### Scenario: Unknown shape does not lose the page
- **WHEN** a page's markup matches no known shape and structured fallback extraction also fails
- **THEN** the page is recorded in a needs-review set with its URL, reason, and a raw excerpt, and ingestion continues without raising

#### Scenario: No page is silently dropped
- **WHEN** ingestion completes
- **THEN** every discovered page is either represented in the catalog or present in the needs-review set; the counts account for all pages

### Requirement: Field names are normalised across shapes

Equivalent facts are labelled differently depending on markup shape. The extractor SHALL map them onto one set of catalog fields and SHALL preserve the original label and raw value, so a mapping mistake is visible rather than silent.

#### Scenario: Size, weight, colour, finish and pack size are unified
- **WHEN** a page labels size as `Size`, `Paper size`, or embedded in prose
- **THEN** all forms populate one size field, and the raw label and raw value are retained for audit

#### Scenario: Price is read in every published format
- **WHEN** a price appears as a currency-prefixed amount, a suffix-suffixed amount, or a struck-through original beside a sale amount
- **THEN** the numeric amount is captured correctly and, for the sale form, both the original and the sale amount are recorded

### Requirement: Absent attributes are recorded as not-applicable, not as negative

Some attributes do not exist for some products. Printing-related attributes are meaningful only for printed goods; for plain paper they do not apply. The catalog SHALL distinguish "not applicable" from "does not match".

#### Scenario: Unprinted products carry no printing attributes
- **WHEN** a product has no printing concept at all
- **THEN** its side and colour-mode fields are recorded as not-applicable rather than as an empty or negative value, and a later filter on those attributes does not exclude it

### Requirement: Weight is normalised from four input forms

Weight is published in four forms: a plain grammage, a grammage with a superscript-2 unit, a pound figure carrying the grammage in parentheses, and a pound figure alone. The catalog SHALL record a single normalised grammage plus the original raw text and which form it came from.

#### Scenario: Every published form yields a grammage
- **WHEN** weight appears as a grammage, as a grams-per-square-metre figure, as pounds with a grammage given, or as pounds alone
- **THEN** a normalised grammage is stored, along with the raw source string and the form detected

#### Scenario: Pound-only weight is converted from the agreed table
- **WHEN** weight is published only in pounds and the value is one of 20, 24, 28 or 32
- **THEN** it is converted to 75, 90, 105 or 120 grammage respectively

#### Scenario: Unrecognised weight raises rather than extrapolates
- **WHEN** weight is published in pounds and the value is not in the agreed table
- **THEN** extraction reports the page for review instead of inventing a converted value

#### Scenario: Weight stated only in prose is still captured
- **WHEN** a product page states its weight only within descriptive prose rather than in a labelled specification field
- **THEN** the weight is still captured, and the page is not recorded as having unknown weight

### Requirement: Size is normalised to a code and never matched as display text

Sizes are published inconsistently, including a vulgar-fraction form and a non-ASCII multiplication sign. The catalog SHALL store a normalised size code plus numeric dimensions, and matching SHALL use the code.

#### Scenario: Equivalent size spellings map to one code
- **WHEN** the same paper size is written with decimal dimensions, with a vulgar fraction, or with a unicode multiplication sign
- **THEN** all spellings produce the same size code

#### Scenario: Unmappable size is reported, not left unset
- **WHEN** a size string cannot be mapped to a known size code
- **THEN** the page is reported for review rather than stored with an unset size

### Requirement: Paper shade and print colour mode are separate fields

"Colour" refers to two unrelated properties: the shade of the paper itself, and whether printing is in colour. The catalog SHALL record these in separate fields.

#### Scenario: Shade and colour mode are both retained independently
- **WHEN** a product page states a shade, or a printing colour mode, or both
- **THEN** each is stored in its own field, and neither is inferred from the other

### Requirement: Pack size is captured independently of the unit word

Prices are per pack, but packs differ in sheet count, and the words used for the unit are unreliable — the same product family uses both "ream" and "pack", and some pages use both words for one product. The catalog SHALL treat the sheet count as the fact and the unit word as display text only.

#### Scenario: Sheet count is the authoritative quantity basis
- **WHEN** a page states its pack contents
- **THEN** the sheet count is stored as a number and used for quantity reasoning

#### Scenario: Unit word is never used for filtering
- **WHEN** the same product family describes one item as a ream and another with both words
- **THEN** both yield the same stored facts, and no filter or comparison depends on the unit word

### Requirement: Sale and stock state are recorded explicitly

The catalog SHALL record whether an item is on sale, its stock state, and any stated restock date, distinguishing an item that is temporarily unavailable from one that is permanently withdrawn.

#### Scenario: Sale item is distinguishable and its volume pricing is suppressed
- **WHEN** a product is shown with a struck-through original price
- **THEN** it is recorded as on sale with both amounts, and it is recorded as offering no volume pricing

#### Scenario: Availability carries its restock date
- **WHEN** a product is out of stock and the page states an expected return date
- **THEN** the stock state and the stated date are both recorded

#### Scenario: Discontinued is distinct from out of stock
- **WHEN** a product is marked as discontinued
- **THEN** it is recorded as discontinued, differently from an out-of-stock item, so it can be reported and refused separately

### Requirement: Independently rendered stock claims are cross-checked

Category listing cards and product pages are separate renderings of the same underlying fact. The catalog SHALL compare the stock claim on the card that linked to a product against the product page's own claim and SHALL flag disagreement without silently correcting either.

#### Scenario: Disagreement is flagged not resolved
- **WHEN** a category card states an availability that contradicts the corresponding product page
- **THEN** the discrepancy is recorded as a review item and neither source's value is used to overwrite the other

### Requirement: Every catalog row carries provenance

Every stored product fact and every price tier SHALL record the URL it came from and the time it was retrieved.

#### Scenario: Provenance is present on stored rows
- **WHEN** any product or price tier is read from the catalog
- **THEN** its source URL and retrieval timestamp are available alongside it

### Requirement: Ingested content is treated as untrusted data

Text from the site may contain instructions aimed at the assistant. The catalog SHALL store such text as data only, and it SHALL NOT be interpreted as instructions to the system.

#### Scenario: Embedded instruction has no effect on behaviour
- **WHEN** a product description contains text instructing the system to change prices or ignore its rules
- **THEN** the text is stored and displayed as product data, and has no effect on pricing, filtering, or the reply
