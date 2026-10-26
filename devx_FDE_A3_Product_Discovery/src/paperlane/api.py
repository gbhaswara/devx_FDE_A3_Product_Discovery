"""The HTTP surface: one conversational entry point, one structured one.

The design constraint is that a caller must be able to drive the same behaviour
three ways — a browser, an evaluation harness, and a script — without knowing
anything about internal structure. So every response carries the same envelope,
and the four outcomes are a closed set.

Error handling is deliberately split in two:

* **Client errors** (400/422) name the problem and never expose a stack trace.
  A malformed body, an implausible quantity, or a criterion the catalog cannot
  express is the caller's mistake, and saying so is more useful than a 500.
* **A missing snapshot** (503) is not the caller's mistake. It names the file and
  the command that builds one, because "not found" without a remedy is a dead
  end.

A model outage is neither. It degrades the *answer*, never the service: the rule
interpreter answers, and `interpretation` says so.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import catalog, embeddings
from .assistant import (
    OUTCOME_CLARIFIED,
    OUTCOME_NO_MATCH,
    OUTCOME_QUOTED,
    OUTCOME_REFUSED,
    AssistantReply,
    answer,
)
from .criteria import Criteria
from .interpret import CriteriaInvalid, interpret, interpret_rules, validate
from .model import ModelClient, ModelConfig, ModelUnavailable
from .money import Money
from .pricing import LineRequest, PriceFacts, quote

#: The four outcomes, as a closed set. A caller can branch on this without
#: parsing prose.
OUTCOMES = (OUTCOME_QUOTED, OUTCOME_CLARIFIED, OUTCOME_NO_MATCH, OUTCOME_REFUSED)

#: What each outcome must carry. Declared rather than implied, so that a reply
#: which silently loses its figures — or asks a question while carrying a price
#: — is a detectable defect instead of a plausible-looking response.
#:
#: ``quoted`` requires figures and at least one candidate; a quote with no price
#: is not a quote. ``clarified`` requires questions; asking nothing is not a
#: clarification. ``refused`` requires the refused items, because "cannot supply"
#: without naming what is unhelpful. ``no_match`` requires only the reply: its
#: whole message is that nothing qualified.
OUTCOME_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    OUTCOME_QUOTED: ("reply", "candidates", "figures"),
    OUTCOME_CLARIFIED: ("reply", "questions"),
    OUTCOME_NO_MATCH: ("reply",),
    OUTCOME_REFUSED: ("reply", "refused"),
}


def check_outcome_contract(outcome: str, body: dict[str, Any]) -> list[str]:
    """List the contract violations in a response body.

    Returns an empty list when the response is well-formed. Used by the tests and
    by the UI route, so the same rule is enforced in both places.
    """
    problems: list[str] = []

    if outcome not in OUTCOMES:
        return [f"{outcome!r} is not one of {OUTCOMES}"]

    for field in OUTCOME_REQUIRED_FIELDS[outcome]:
        value = body.get(field)
        if value is None or value == "" or value == [] or value == {}:
            problems.append(f"{outcome} response is missing {field!r}")

    # An outcome must not carry a price it did not earn.
    if outcome != OUTCOME_QUOTED and body.get("figures"):
        problems.append(f"{outcome} response carries figures but did not quote")

    return problems


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ConversationalRequest(BaseModel):
    """A free-text request."""

    request: str = Field(..., min_length=1, max_length=2000,
                         description="What the customer asked for, in their words.")
    quantity: int | None = Field(None, ge=1, le=100_000)
    use_model: bool = Field(True, description="Allow the model to interpret.")

    @field_validator("request")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("request must not be blank")
        return value


class StructuredRequest(BaseModel):
    """Already-structured requirements. No model is involved."""

    category: str | None = None
    size: str | None = None
    weight_gsm: int | None = Field(None, ge=1, le=1000)
    weight_gsm_min: int | None = Field(None, ge=1, le=1000)
    weight_gsm_max: int | None = Field(None, ge=1, le=1000)
    colour_shade: str | None = None
    colour_mode: str | None = None
    finish: str | None = None
    sides: str | None = None
    quantity: int = Field(1, ge=1, le=100_000)
    budget_per_unit: Decimal | None = None
    budget_basis: str = "per pack, before VAT"


class QuoteLineRequest(BaseModel):
    """A cart line for the multi-line quote endpoint."""

    sku: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100_000)


class MultiLineRequest(BaseModel):
    lines: list[QuoteLineRequest] = Field(..., min_length=1, max_length=50)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _client_error(detail: str, *, field: str | None = None, status: int = 400):
    """A client error that names the problem and exposes no internals."""
    payload: dict[str, Any] = {"error": "invalid_request", "detail": detail}
    if field:
        payload["field"] = field
    return JSONResponse(status_code=status, content=payload)


def _missing_snapshot(exc: catalog.SnapshotMissing):
    """503 with the remedy, because a bare 404 is a dead end."""
    return JSONResponse(
        status_code=503,
        content={
            "error": "no_snapshot",
            "detail": str(exc),
            "snapshot_path": str(exc.path),
            "remedy": "./run.sh ingest --base-url http://localhost:8000/paperlane/",
        },
    )


def _meta(*, started: float, interpretation: str, snapshot: dict) -> dict[str, Any]:
    return {
        "interpretation": interpretation,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "snapshot": snapshot,
    }


def _snapshot_meta() -> dict[str, Any]:
    """A compact statement of what the answer was computed against."""
    info = catalog.health()
    return {
        "path": info.get("path"),
        "products": info.get("products"),
        "price_tiers": info.get("price_tiers"),
        "built_at": (info.get("last_ingest") or {}).get("finished_at"),
        "base_url": (info.get("last_ingest") or {}).get("base_url"),
    }


def _criteria_from_structured(payload: StructuredRequest) -> Criteria:
    """Map a structured request onto Criteria, resolving vocabulary.

    Structured callers get the same vocabulary resolution as free-text ones: a
    ``size`` of ``"letter"`` resolves to ``LTR``. Otherwise the two entry points
    would accept different values for the same field, which is exactly the kind
    of inconsistency that makes an API untrustworthy.
    """
    from .aliases import (
        resolve_category,
        resolve_colour,
        resolve_finish,
        resolve_size,
    )
    from .normalize import SizeError

    notes: tuple[str, ...] = ()

    size_code = None
    if payload.size:
        try:
            size_code = resolve_size(payload.size)
        except SizeError as exc:
            raise CriteriaInvalid(str(exc), "size") from exc
        if size_code is None:
            raise CriteriaInvalid(
                f"{payload.size!r} is not a size this catalog stocks", "size"
            )

    category = None
    if payload.category:
        category = resolve_category(payload.category)
        if category is None:
            raise CriteriaInvalid(
                f"{payload.category!r} is not a catalog category", "category"
            )

    finish = None
    if payload.finish:
        finish = resolve_finish(payload.finish)
        if finish is None:
            raise CriteriaInvalid(
                f"{payload.finish!r} is not a catalog finish", "finish"
            )

    shade = payload.colour_shade.lower() if payload.colour_shade else None
    mode = payload.colour_mode
    if mode:
        _, resolved_mode, _ = resolve_colour(mode)
        mode = resolved_mode or mode

    sides = payload.sides
    if sides is not None:
        from .model import normalise_sides

        sides = normalise_sides(sides) or sides

    return Criteria(
        raw_text="",
        category=category,
        size_code=size_code,
        weight_gsm=payload.weight_gsm,
        weight_gsm_min=payload.weight_gsm_min,
        weight_gsm_max=payload.weight_gsm_max,
        colour_name=shade,
        colour_mode=mode,
        finish=finish,
        sides=sides,
        quantity=payload.quantity,
        budget_per_unit=(
            Money.from_baht(payload.budget_per_unit)
            if payload.budget_per_unit is not None
            else None
        ),
        budget_basis=payload.budget_basis,
        notes=notes,
    )


def _candidates_and_figures(reply: AssistantReply) -> dict[str, Any]:
    """The candidate and figure structure shared by both entry points."""
    payload: dict[str, Any] = {
        "outcome": reply.outcome,
        "candidates": [c.as_dict() for c in reply.candidates],
    }
    # Reported only when similarity participated or failed, so a deployment with
    # no provider returns exactly the shape it returned before this capability.
    if reply.semantic != "off":
        payload["semantic"] = reply.semantic
        if reply.semantic_detail:
            payload["semantic_detail"] = reply.semantic_detail
    if reply.quote is not None:
        payload["figures"] = {
            "subtotal": reply.quote.subtotal.format(),
            "delivery": reply.quote.delivery.format(),
            "vat": reply.quote.vat.format(),
            "total": reply.quote.total.format(),
            "vat_rate": str(reply.quote.vat_rate),
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price.format(),
                    "line_total": line.line_total.format(),
                    "discount": line.discount_source,
                }
                for line in reply.quote.lines
            ],
        }
    if reply.questions:
        payload["questions"] = [q.as_dict() for q in reply.questions]
    if reply.alternatives:
        payload["alternatives"] = [c.as_dict() for c in reply.alternatives]
    if reply.relaxed:
        payload["relaxed"] = reply.relaxed
    if reply.refused:
        payload["refused"] = [c.as_dict() for c in reply.refused]
    if reply.errors:
        payload["errors"] = list(reply.errors)
    if reply.warnings:
        payload["warnings"] = list(reply.warnings)
    return payload


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------


def create_app(
    *,
    db_path=None,
    model_client: ModelClient | None = None,
) -> FastAPI:
    """Build the application.

    ``db_path`` and ``model_client`` are injectable so tests can drive a
    temporary snapshot and a stub model without touching the committed one.
    """
    app = FastAPI(
        title="PaperLane sales assistant",
        version="0.1.0",
        description="Product discovery and quoting over the PaperLane catalog.",
    )

    def facts() -> dict[str, PriceFacts]:
        return catalog.load_price_facts(db_path)

    def products() -> list[dict[str, Any]]:
        return catalog.load_products(db_path)

    def health_info() -> dict[str, Any]:
        return catalog.health(db_path)

    def get_model() -> ModelClient | None:
        if model_client is not None:
            return model_client
        config = ModelConfig.from_env()
        return ModelClient(config) if config.configured else None

    def get_scorer(request_text: str, product_rows: list[dict[str, Any]]):
        """A semantic scorer for this request, or ``None`` when unconfigured.

        Built per request because it carries the request text, but the product
        vectors behind it are cached per snapshot, so the 72-product embed cost
        is paid once per re-ingest rather than once per question.
        """
        return embeddings.scorer_for(request_text, product_rows, db_path=db_path)

    def model_reachable() -> bool:
        return get_model() is not None

    # -- exception handling: no stack traces, ever ---------------------

    @app.exception_handler(catalog.SnapshotMissing)
    async def _snapshot_missing(request: Request, exc: catalog.SnapshotMissing):
        return _missing_snapshot(exc)

    @app.exception_handler(CriteriaInvalid)
    async def _criteria_invalid(request: Request, exc: CriteriaInvalid):
        return _client_error(exc.reason, field=exc.field, status=422)

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(request: Request, exc: RequestValidationError):
        """Normalise framework validation errors onto the same contract.

        FastAPI's default is ``{"detail": [...]}``, which is a *different shape*
        from the one every other error uses. A caller that has to parse two error
        formats will get it wrong, so the first error is reported in the same
        ``error``/``detail``/``field`` form as everything else. The full list is
        kept under ``issues`` rather than dropped, because with several bad
        fields the caller needs all of them.
        """
        issues = []
        for error in exc.errors():
            location = [str(part) for part in error.get("loc", ()) if part != "body"]
            issues.append({
                "field": ".".join(location) or None,
                "detail": error.get("msg", "invalid value"),
            })

        first = issues[0] if issues else {"field": None, "detail": "invalid request"}
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_request",
                "detail": first["detail"],
                "field": first["field"],
                "issues": issues,
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # A last resort. The detail is generic on purpose: an internal message
        # can leak paths and structure.
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": "The request could not be completed.",
            },
        )

    # -- 6.1 structured quoting ---------------------------------------

    @app.post("/api/quote")
    def structured_quote(payload: StructuredRequest):
        """Price already-structured requirements. No model is consulted."""
        started = time.perf_counter()

        criteria = _criteria_from_structured(payload)
        validate(criteria)

        rows = products()
        reply = answer(
            criteria, rows, facts(), interpretation="rules",
            scorer=get_scorer(criteria.raw_text, rows),
        )
        body = _candidates_and_figures(reply)
        body["criteria"] = criteria.describe()
        body["meta"] = _meta(
            started=started, interpretation="structured", snapshot=_snapshot_meta()
        )
        return body

    @app.post("/api/quote/lines")
    def multi_line_quote(payload: MultiLineRequest):
        """Price several known SKUs together, so delivery and VAT are once."""
        started = time.perf_counter()
        all_facts = facts()

        lines: list[LineRequest] = []
        unknown: list[str] = []
        for line in payload.lines:
            if line.sku not in all_facts:
                unknown.append(line.sku)
                continue
            lines.append(LineRequest(line.sku, line.quantity, all_facts[line.sku]))

        if unknown:
            return _client_error(
                f"unknown SKU(s): {', '.join(sorted(unknown))}", field="lines",
                status=422,
            )
        if not lines:
            return _client_error("no priceable lines supplied", field="lines")

        order = quote(lines)
        return {
            "outcome": OUTCOME_QUOTED,
            "figures": {
                "subtotal": order.subtotal.format(),
                "delivery": order.delivery.format(),
                "vat": order.vat.format(),
                "total": order.total.format(),
                "vat_rate": str(order.vat_rate),
                "lines": [
                    {
                        "sku": line.sku,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price.format(),
                        "line_total": line.line_total.format(),
                        "discount": line.discount_source,
                    }
                    for line in order.lines
                ],
            },
            "meta": _meta(
                started=started, interpretation="structured",
                snapshot=_snapshot_meta(),
            ),
        }

    # -- 6.2, 6.3, 6.6 conversational ----------------------------------

    @app.post("/api/ask")
    def ask(payload: ConversationalRequest):
        """Free text in; reply, interpretation, candidates, figures out."""
        started = time.perf_counter()

        client = get_model() if payload.use_model else None
        interpretation = interpret(payload.request, client)

        criteria = interpretation.criteria
        if payload.quantity is not None:
            from dataclasses import replace

            criteria = replace(criteria, quantity=payload.quantity)

        # Validation failure is a client error, and it never reaches pricing.
        validate(criteria)

        rows = products()
        reply = answer(
            criteria, rows, facts(), interpretation=interpretation.path,
            scorer=get_scorer(criteria.raw_text or payload.request, rows),
        )

        body = _candidates_and_figures(reply)
        body["reply"] = reply.text
        body["criteria"] = criteria.describe()
        body["meta"] = _meta(
            started=started,
            interpretation=interpretation.path,
            snapshot=_snapshot_meta(),
        )
        body["meta"]["interpretation_detail"] = interpretation.detail
        return body

    # -- 6.7 catalog inspection, health, comparison --------------------

    @app.get("/api/products")
    def list_products(
        size: str | None = Query(None, description="Size code, e.g. A4"),
        category: str | None = Query(None),
        weight_min: int | None = Query(None, ge=1, le=1000),
        weight_max: int | None = Query(None, ge=1, le=1000),
        in_stock_only: bool = Query(False),
        limit: int = Query(200, ge=1, le=1000),
    ):
        """The normalised catalog, filterable, with provenance."""
        rows = products()
        if size:
            rows = [r for r in rows if (r.get("size_code") or "").upper() == size.upper()]
        if category:
            rows = [
                r for r in rows
                if (r.get("category") or "").lower() == category.lower()
            ]
        if weight_min is not None:
            rows = [r for r in rows if (r.get("weight_gsm") or 0) >= weight_min]
        if weight_max is not None:
            rows = [r for r in rows if (r.get("weight_gsm") or 0) <= weight_max]
        if in_stock_only:
            rows = [r for r in rows if r.get("stock_status") == "in_stock"]

        return {
            "count": len(rows),
            "returned": min(len(rows), limit),
            "products": [
                {
                    key: (str(value) if isinstance(value, Decimal) else value)
                    for key, value in row.items()
                }
                for row in rows[:limit]
            ],
        }

    @app.get("/api/health")
    def health():
        """Name the snapshot, count it, and say whether the model is reachable.

        A health check that reports "unhealthy" without a remedy is a dead end
        for whoever is on call, so a missing snapshot names the file and the
        command that builds one — the same remedy the 503 carries.
        """
        info = health_info()
        info["model_reachable"] = model_reachable()
        info["model_configured"] = ModelConfig.from_env().configured
        if info.get("snapshot_present"):
            try:
                with catalog.open_readonly(db_path) as con:
                    con.execute("SELECT count(*) FROM products").fetchone()
                info["catalog_readable"] = True
            except Exception:  # noqa: BLE001
                info["catalog_readable"] = False
        else:
            info["catalog_readable"] = False
            info["remedy"] = (
                "./run.sh ingest --base-url http://localhost:8000/paperlane/"
            )
        info["healthy"] = bool(info.get("catalog_readable"))
        return info

    @app.get("/api/diff")
    def diff():
        """Compare the staged snapshot against the serving one."""
        return catalog.diff_snapshots()

    # -- the single page ------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index():
        from .ui import PAGE

        return HTMLResponse(PAGE)

    @app.post("/ask", response_class=HTMLResponse)
    def ask_fragment(
        request: str = Form(...),
        quantity: str | None = Form(None),
    ):
        """The fragment the page swaps in.

        Separate from ``/api/ask`` because the two have different obligations: the
        JSON endpoint must expose structure for a harness, while this one must
        render something a salesperson can read. Sharing the rendering code but
        not the response shape keeps each honest.
        """
        from html import escape

        from .ui import render_fragment

        started = time.perf_counter()

        if not request.strip():
            return HTMLResponse(render_fragment(
                outcome="clarified", badge="Need a request",
                body="Please describe what you are looking for.",
                criteria={}, meta={},
            ))

        parsed_quantity: int | None = None
        if quantity and quantity.strip():
            try:
                parsed_quantity = int(quantity)
                if parsed_quantity < 1 or parsed_quantity > 100_000:
                    raise ValueError
            except ValueError:
                return HTMLResponse(render_fragment(
                    outcome="clarified", badge="Bad quantity",
                    body="Quantity must be a whole number between 1 and 100,000.",
                    criteria={}, meta={},
                ))

        try:
            client = get_model()
            interpretation = interpret(request, client)
            criteria = interpretation.criteria
            if parsed_quantity is not None:
                from dataclasses import replace

                criteria = replace(criteria, quantity=parsed_quantity)
            validate(criteria)
            rows = products()
            reply = answer(
                criteria, rows, facts(), interpretation=interpretation.path,
                scorer=get_scorer(criteria.raw_text or request, rows),
            )
        except catalog.SnapshotMissing as exc:
            return HTMLResponse(render_fragment(
                outcome="refused", badge="No catalog",
                body=str(exc), criteria={}, meta={},
            ))
        except CriteriaInvalid as exc:
            return HTMLResponse(render_fragment(
                outcome="clarified", badge="Could not use that",
                body=exc.reason, criteria={}, meta={},
            ))

        return HTMLResponse(render_fragment(
            outcome=reply.outcome,
            badge={
                "quoted": "Quote",
                "clarified": "Need more detail",
                "no_match": "Nothing matched",
                "refused": "Cannot supply",
            }.get(reply.outcome, reply.outcome),
            body=reply.text,
            criteria=criteria.describe(),
            meta={
                "interpretation": interpretation.path,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            },
            errors=list(reply.errors),
            warnings=list(reply.warnings),
        ))

    return app


app = create_app()


def run_server(host: str = "127.0.0.1", port: int = 8000) -> int:
    """Serve the API and the page. Entry point for ``./run.sh serve``.

    Fails early and legibly when there is no snapshot, rather than starting a
    service whose every request returns 503.
    """
    import uvicorn

    if not catalog.snapshot_exists():
        print(
            f"No catalog snapshot at {catalog.DEFAULT_DB_PATH}.\n"
            f"Build one with: "
            f"./run.sh ingest --base-url http://localhost:8000/paperlane/",
            flush=True,
        )
        return 1

    report = catalog.health()
    print(
        f"Serving {report['products']} products, "
        f"{report['price_tiers']} price tiers from {report['path']}",
        flush=True,
    )
    if report.get("open_review_items"):
        print(
            f"Warning: {report['open_review_items']} open review item(s); "
            f"see ./run.sh diff",
            flush=True,
        )
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
