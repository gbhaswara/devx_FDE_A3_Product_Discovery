# devx AI Labs — AI Forward Deployed Engineer take-home

Three assignments were supplied. **A3 — Product Discovery** is the one built
and submitted here; the A1 and A2 folders contain only the supplied briefs and
their inputs.

The submission is a sales assistant for **PaperLane**, a paper and flyer
printer in Bangkok. A customer describes what they need in their own words; the
assistant finds the right products in the crawled catalog, prices them to the
satang, and writes a reply a salesperson can send.

**Start here: [`devx_FDE_A3_Product_Discovery/README.md`](devx_FDE_A3_Product_Discovery/README.md)** —
run instructions, architecture, trade-offs, limitations, evaluation results and
the AI-tools note.

## Run the demo

From a clean checkout:

```bash
cd devx_FDE_A3_Product_Discovery
uv sync
./run.sh test
./run.sh serve
./run.sh eval
./run.sh ask "A4 80gsm copy paper, 20 reams" --conversation demo \
  && ./run.sh ask "make it 50" --conversation demo
```

The catalog snapshot (`data/catalog.duckdb`) is committed, so `serve` and `ask`
work without crawling. Rebuilding it from the supplied site takes two more
commands, and the site must be served over HTTP — opening `paperlane/` from disk
does not load volume prices:

```bash
python3 -m http.server 8000
./run.sh ingest --base-url http://localhost:8000/paperlane/
```

## What is where

| Path | Contents |
|---|---|
| `devx_FDE_A3_Product_Discovery/` | The A3 submission: source, tests, evaluation, docs, catalog snapshot |
| `devx_FDE_A3_Product_Discovery/paperlane/` | The supplied catalog site — read-only input |
| `devx_FDE_A3_Product_Discovery/docs/pre/`, `devx_FDE_A3_Product_Discovery/docs/post/` | Planning evidence, and the design as built |
| `openspec/specs/` | The live behavioural contracts: eleven capabilities, 86 requirements, 227 scenarios |
| `openspec/changes/archive/` | The six changes that produced them, each with proposal, design and tasks |
| `AGENTS.md`, `CLAUDE.md` | Working rules and the read order for this repository |
| `ARCHITECTURE.md`, `DESIGN.md`, `TEST.md` | How it is built, how it reads, how it is proven |
| `BUG.md`, `CHANGELOG.md` | The defect register with its guards, and the project history |
| `devx_FDE_A1_Document_Intelligence/`, `devx_FDE_A2_Transaction_Reconciliation/` | The other two briefs and their inputs — not attempted |

## Design rules the code holds to

- **Pricing is deterministic code, never the model.** Money is integer satang;
  every figure comes from the pricing engine. The model interprets free text
  only — it never selects a product, prices one, or writes a total.
- **The catalog is read over HTTP, at 1 request per second.** `robots.txt` sets
  `Crawl-delay: 1`; the brief caps the crawl at 2 req/s.
- **Absent is not negative.** An attribute that does not apply to a product must
  not exclude it from a search.
- **Degrade, never crash.** An unparseable page becomes a review row, an
  unreachable model becomes a rule-based answer, a missing detail becomes a
  clarification.
- **Provenance on every catalog row** — source URL and retrieval timestamp.
- **No credentials in the repository.** They come from environment variables;
  `.env` is git-ignored.

## Verification

| Check | Result |
|---|---|
| Test suite, offline (`./run.sh test-offline`) | 1,260 passed, 3 skipped (1,263 collected); one further case skips on a fresh clone until `verify-refresh --keep` |
| Test suite, with `bge-m3` on a local Ollama | 1,263 passed, 0 skipped |
| Evaluation, v1 catalog | 24/24 runnable cases pass (4 not run by design) |
| Evaluation, mutated v2 catalog | 21/21 |
| Conversation set | 12/12 over 27 turns; both negative controls fail as designed |
| Held-out set | 9/11, with two failures retained |
| Refresh harness | 12/12 declared changes reported under the correct kind |

The evaluation records live in
`devx_FDE_A3_Product_Discovery/eval/results.md`; the defect register and its
guards are in `BUG.md`.

## AI tools

The build used OpenCode with a spec-driven workflow (OpenSpec), Context7 for
library documentation, and MCP memory tools across sessions. The model drafted
the analysis, specs and most of the code; pricing arithmetic, evaluation design
and scope decisions stayed under human ownership. The full note is
[`README §6`](devx_FDE_A3_Product_Discovery/README.md#6-how-i-used-ai-tools).
