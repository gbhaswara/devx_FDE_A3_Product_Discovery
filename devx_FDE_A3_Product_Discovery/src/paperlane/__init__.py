"""PaperLane product discovery and quoting assistant.

The package is deliberately layered so that the deterministic core has no
dependency on the network, the clock, or a language model:

    money      integer satang and explicit half-up rounding
    pricing    pure functions implementing PR1-PR8
    normalize  size and weight normalisation
    catalog    the DuckDB snapshot store
    crawl      the rate-limited HTTP crawler
    extract    the four-shape extraction ladder
    search     hard-constraint filtering and deterministic ranking
    assistant  criteria parsing and the reply contract
    api        the HTTP surface
"""

__version__ = "0.1.0"
