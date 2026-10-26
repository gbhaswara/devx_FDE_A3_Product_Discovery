"""The model client: criteria extraction only, with a sanitising boundary.

The model's job is narrow and deliberately so. It reads a customer's sentence
and returns **search criteria**. It never sees a price, never returns a price,
never names a SKU, and never writes the reply. That is a structural guarantee,
not a prompt instruction: the reply is rendered by `assistant.py` from
deterministic values, and any price or SKU the model emits is discarded.

The endpoint is treated as unreliable by design, because it is. Three failures
were observed on the configured provider and each has a named remedy here:

1. **A stray terminator.** The body ends with ``data: [DONE]``, which
   ``json.loads`` rejects with ``Extra data``. Stripped before parsing.
2. **Reasoning eats the budget.** ``9inference`` is a reasoning model: with a
   small ``max_tokens`` it spends the whole allowance thinking and returns
   ``content: null`` with HTTP 200. The budget is therefore set high.
3. **Structured-output flags make it worse.** ``response_format={"type":
   "json_object"}`` produced empty content; ``reasoning_effort="none"`` was
   ignored. Neither is used. The JSON is extracted from prose instead.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

#: The reasoning model spends output tokens thinking before it answers. Below
#: roughly 1000 it returns ``content: None`` with a 200 status, which looks like
#: a working request that produced nothing.
DEFAULT_MAX_TOKENS = 2000

#: A stray SSE-style terminator the endpoint appends to otherwise valid JSON.
_TERMINATOR = re.compile(r"\s*data:\s*\[DONE\]\s*$")

#: A fenced code block, which models add even when told not to.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class ModelUnavailable(RuntimeError):
    """The model could not be reached, or returned nothing usable."""


@dataclass
class ModelConfig:
    """Where the model lives. Read from the environment, never hard-coded."""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout: float = 45.0

    @classmethod
    def from_env(cls) -> "ModelConfig":
        """Build from ``PAPERLANE_*`` then the generic OpenAI-compatible names.

        No credential is ever stored in the repository; ``.env`` is git-ignored
        and the README documents environment variables only.
        """
        return cls(
            base_url=(
                os.environ.get("PAPERLANE_LLM_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or ""
            ).rstrip("/"),
            api_key=(
                os.environ.get("PAPERLANE_LLM_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or ""
            ),
            model=(
                os.environ.get("PAPERLANE_LLM_MODEL")
                or os.environ.get("OPENAI_MODEL")
                or ""
            ),
            max_tokens=int(os.environ.get("PAPERLANE_LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


# ---------------------------------------------------------------------------
# Sanitising
# ---------------------------------------------------------------------------


def strip_terminator(raw: str) -> str:
    """Remove the stray ``data: [DONE]`` the endpoint appends.

    Without this, ``json.loads`` raises ``Extra data: line 1 column N`` on a
    body that is otherwise perfectly valid JSON.
    """
    return _TERMINATOR.sub("", raw.strip())


def extract_json_object(raw: str) -> dict[str, Any]:
    """Pull one JSON object out of a model response.

    Tries, in order: the whole body, the first fenced block, and the outermost
    brace-balanced span. Raises :class:`ModelUnavailable` if none parses — the
    caller then falls back to rules rather than propagating a parse error.
    """
    if not raw or not raw.strip():
        raise ModelUnavailable("model returned an empty body")

    candidates: list[str] = []
    cleaned = strip_terminator(raw)
    candidates.append(cleaned)

    for fenced in _FENCE.findall(cleaned):
        candidates.append(strip_terminator(fenced))

    balanced = _outermost_object(cleaned)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ModelUnavailable(f"no JSON object in model output: {raw[:200]!r}")


def _outermost_object(text: str) -> str | None:
    """The first brace-balanced object in ``text``, respecting strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def message_content(payload: dict[str, Any]) -> str:
    """Read ``choices[0].message.content``, treating null as unavailable.

    The reasoning-model failure mode: HTTP 200, a well-formed envelope, and
    ``content: null`` because every output token went to reasoning. That is not
    a usable answer and must not be treated as an empty one.
    """
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelUnavailable(f"unexpected response envelope: {payload!r:.200}") from exc

    content = message.get("content")
    if content is None or not str(content).strip():
        raise ModelUnavailable(
            "model returned no content (reasoning likely consumed the output "
            f"budget; raise max_tokens above {DEFAULT_MAX_TOKENS})"
        )
    return str(content)


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


#: The criteria the model may return. Anything else is dropped, so a model
#: cannot widen its own influence.
ALLOWED_CRITERIA_KEYS = frozenset({
    "category", "size", "weight_gsm", "weight_gsm_min", "weight_gsm_max",
    "colour_shade", "colour_mode", "colour", "finish", "sides", "quantity",
    "budget_per_unit", "budget_basis", "notes",
})

#: Keys the model actually emits, mapped onto the canonical names.
#:
#: Measured against the live endpoint, not guessed. ``9inference`` ignores the
#: key list in the system prompt and answers in its own vocabulary — ``gsm``,
#: ``packs``, ``paper_weight_gsm``, ``product``, ``per_pack_constraint``. A
#: strict allow-list therefore discarded every value and the model never
#: contributed anything, which made the "model" path a fig leaf. Translating the
#: observed keys is what makes it real.
MODEL_KEY_ALIASES: dict[str, str] = {
    # identity
    "product": "category",
    "need": "category",
    "product_type": "category",
    "paper_type": "category",
    # size
    "paper_size": "size",
    "dimensions": "size",
    # weight
    "gsm": "weight_gsm",
    "weight": "weight_gsm",
    "paper_weight": "weight_gsm",
    "paper_weight_gsm": "weight_gsm",
    "basis_weight": "weight_gsm",
    # quantity
    "packs": "quantity",
    "reams": "quantity",
    "qty": "quantity",
    "count": "quantity",
    "units": "quantity",
    # money
    "budget": "budget_per_unit",
    "max_price_per_pack": "budget_per_unit",
    "max_price": "budget_per_unit",
    "price_per_pack": "budget_per_unit",
    "per_pack_constraint": "budget_per_unit",
    # colour
    "color": "colour",
    "colour_shade_name": "colour_shade",
    "shade": "colour_shade",
    "print_colour": "colour_mode",
    "print_color": "colour_mode",
    # printing
    "printing": "sides",
    "print_sides": "sides",
    "sides_printed": "sides",
}

#: Model keys that are commentary rather than criteria. Dropped deliberately:
#: they describe the model's own uncertainty, which the assistant decides for
#: itself from the criteria and the catalog.
MODEL_NOISE_KEYS = frozenset({
    "status", "clarification", "clarification_needed", "required_details",
    "note", "notes_", "explanation", "reason", "reasoning", "confidence",
    "product_name", "assumptions", "questions", "ambiguity",
})

#: Side phrasings the model produced, mapped to the stored values.
_SIDE_ALIASES: dict[str, str] = {
    "one-sided": "single", "one sided": "single", "single-sided": "single",
    "single sided": "single", "single": "single", "simplex": "single",
    "one side": "single", "one-side": "single", "1-sided": "single",
    "1 side": "single", "single side": "single",
    "double-sided": "double", "double sided": "double", "two-sided": "double",
    "two sided": "double", "double": "double", "duplex": "double",
    "two sides": "double", "both sides": "double", "2-sided": "double",
    "2 sides": "double", "double side": "double",
}


def normalise_model_keys(raw: dict[str, Any]) -> dict[str, Any]:
    """Translate the model's own key vocabulary onto the canonical names.

    Canonical keys pass through untouched. Unknown keys are dropped unless they
    are known noise. A translated key never overwrites a canonical key the model
    also supplied, so an explicit ``weight_gsm`` beats an inferred ``gsm``.
    """
    normalised: dict[str, Any] = {}

    for key, value in raw.items():
        name = str(key).strip().lower()
        if name in MODEL_NOISE_KEYS:
            continue
        canonical = name if name in ALLOWED_CRITERIA_KEYS else MODEL_KEY_ALIASES.get(name)
        if canonical is None:
            continue
        if canonical in ALLOWED_CRITERIA_KEYS and canonical not in normalised:
            normalised[canonical] = value

    return normalised


def normalise_sides(value: Any) -> str | None:
    """Map a side phrasing onto ``"single"`` or ``"double"``."""
    if value is None:
        return None
    return _SIDE_ALIASES.get(str(value).strip().lower())


SYSTEM_PROMPT = """You convert a paper-buying request into search criteria.

Return ONE JSON object. No prose, no markdown, no explanation.

Allowed keys (all optional):
  category        one of: "Copy paper", "Coloured paper", "Card and photo", "Flyer printing"
  size            one of: "A3", "A4", "A5", "LTR", "LGL"
  weight_gsm      integer, exact grammage
  weight_gsm_min  integer floor
  weight_gsm_max  integer ceiling
  colour_shade    paper colour, e.g. "white", "ivory", "pastel blue"
  colour_mode     printing colour, e.g. "Full colour (CMYK)", "Black and white"
  finish          one of: "Gloss", "Matte", "Uncoated", "Laid", "Smooth"
  sides           "single" or "double"
  quantity        integer, how many packs
  budget_per_unit number, maximum price per pack
  notes           short array of strings for anything you could not map

Rules:
- Never invent a product, SKU, or price.
- "colour" for printed goods means colour_mode; for plain paper it means colour_shade.
- If the request does not state something, omit the key entirely. Do not guess.
- Return {} if the request contains no product requirements at all."""

#: Appended to the user turn. The position is the point: this model honours a
#: format instruction in the user message and ignores the same instruction in
#: the system prompt. Verified against the live endpoint.
USER_SUFFIX = "Reply with only a JSON object and nothing else."


@dataclass
class ModelResult:
    """What the model produced, and how it was obtained."""

    criteria: dict[str, Any]
    raw: str = ""
    strategy: str = "model"


class ModelClient:
    """A minimal OpenAI-compatible chat client for criteria extraction."""

    def __init__(self, config: ModelConfig | None = None, *, client=None) -> None:
        self.config = config or ModelConfig.from_env()
        self._client = client

    @property
    def available(self) -> bool:
        return self.config.configured

    def _http(self):
        if self._client is not None:
            return self._client
        import httpx

        return httpx.Client(timeout=self.config.timeout)

    def extract_criteria(self, request_text: str) -> ModelResult:
        """Ask the model for criteria. Raises :class:`ModelUnavailable`."""
        if not self.available:
            raise ModelUnavailable(
                "no model configured; set PAPERLANE_LLM_BASE_URL, "
                "PAPERLANE_LLM_API_KEY and PAPERLANE_LLM_MODEL"
            )

        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                # The JSON instruction goes in the USER message. Measured: with
                # it only in the system prompt this model replies in prose every
                # time, and `response_format={"type":"json_object"}` made it
                # worse. In the user message it returns a bare object.
                {"role": "user", "content": f"{request_text}\n\n{USER_SUFFIX}"},
            ],
            # Deliberately generous: this model reasons before answering, and a
            # small budget yields content=null with HTTP 200.
            "max_tokens": self.config.max_tokens,
            "temperature": 0,
        }
        # No response_format and no reasoning_effort: both were measured to make
        # this provider worse. The JSON is recovered from prose instead.

        client = self._http()
        try:
            response = client.post(
                f"{self.config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except Exception as exc:  # noqa: BLE001 - any transport failure is the same
            raise ModelUnavailable(f"model request failed: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

        if response.status_code != 200:
            raise ModelUnavailable(
                f"model returned HTTP {response.status_code}: {response.text[:200]}"
            )

        # The terminator arrives on the ENVELOPE, not inside the message
        # content: the body is `{...}data: [DONE]` and `response.json()` raises
        # "Extra data" on it. Verified against the live endpoint.
        body_text = strip_terminator(response.text)
        try:
            payload = json.loads(body_text)
        except ValueError as exc:
            raise ModelUnavailable(f"model envelope was not JSON: {exc}") from exc

        content = message_content(payload)
        parsed = extract_json_object(content)
        # The model answers in its own vocabulary; translate before filtering,
        # otherwise the allow-list discards every value it produced.
        criteria = normalise_model_keys(parsed)
        if criteria.get("sides") is not None:
            criteria["sides"] = normalise_sides(criteria["sides"]) or criteria["sides"]
        return ModelResult(criteria=criteria, raw=content, strategy="model")
