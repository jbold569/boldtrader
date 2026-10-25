"""boldhalo router client: chat completions for Enrichment, d3 decision lane for Sifting.

The router (http://model.boldhalo.home) owns model routing; this client passes
the model name per call and never cares which weights answer. Errors are loud:
one retry, then raise.
"""

from __future__ import annotations

import json

import requests

ROUTER = "http://model.boldhalo.home"
CHAT_URL = ROUTER + "/v1/chat/completions"
SIFT_URL = ROUTER + "/v1/systemone"

# Both chat and Enrichment pin the `-pair` variant: it is the
# BoldTrader-specific container the router keeps loaded, serving both models
# from one container. The old plain id (`...-halogen`) triggers a container
# swap mid-turn and stalls requests (observed live, 2026-10-25; ADR 0007).
ENRICH_MODEL = "qwen3.8-flash-next-w4b-q8-halogen-pair"
SIFT_MODEL = "vllm-sr/d3-lite"

# Chat pins the `-pair` variant: it is the container the router keeps
# loaded, so chat turns never trigger a container swap. (2026-10-25: the
# plain id caused a swap mid-turn; user directive to pin chat to -pair.)
CHAT_MODEL = "qwen3.8-flash-next-w4b-q8-halogen-pair"

TIMEOUT = 120  # seconds; enrichment reads 1-3k tokens per call
SIFT_TIMEOUT = 300  # seconds; covers a cold decision-lane load

# Gate on d3's confidence, not the headline number: a live test showed a
# confident-looking 0.93 score whose per-level distribution was uniform and
# whose confidence was 0.008. Tune from observed data.
SIFT_CONFIDENCE_FLOOR = 0.5

# Canonical condition set (GLOSSARY.md).
CONDITIONS = ("complete", "cosmetic damage", "missing parts", "for parts", "refurbished")
_CONFIDENCE = ("high", "medium", "low", "unknown")
_LABELS = ("match", "not_match", "unsure")
_PRODUCT_FIELDS = ("manufacturer", "model", "config")


class RouterError(RuntimeError):
    """Router unreachable, HTTP failure, or a response that violates the contract."""


def _chat(messages: list[dict], model: str, max_tokens: int) -> str:
    """POST one chat completion with low/no-thinking mode; retry once, then raise."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    last: Exception | None = None
    for _ in range(2):  # initial attempt + one retry
        try:
            resp = requests.post(CHAT_URL, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if not content or not content.strip():
                raise RouterError("router returned empty content")
            return content
        except (requests.RequestException, ValueError, KeyError, RouterError) as exc:
            last = exc
    raise RouterError(f"router call failed after retry: {last}") from last


def _extract_json(content: str) -> dict:
    """Parse a JSON object out of a model reply, tolerating ``` fences."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    obj = json.loads(text)  # ValueError propagates as a contract violation
    if not isinstance(obj, dict):
        raise RouterError(f"expected a JSON object, got {type(obj).__name__}")
    return obj


_ENRICH_SYSTEM = f"""You extract structured facts from used-hardware marketplace listings.
Reply with ONLY a JSON object in this exact shape, no prose:

{{
  "product": {{
    "manufacturer": "<string or 'unknown'>",
    "model": "<string or 'unknown'>",
    "config": "<string or 'unknown'>"
  }},
  "condition": "<one of: {', '.join(CONDITIONS)}, or 'unknown'>",
  "bundle": ["<each extra item included beyond the main product, short name>"],
  "confidence": {{
    "manufacturer": "<high|medium|low|unknown>",
    "model": "<high|medium|low|unknown>",
    "config": "<high|medium|low|unknown>",
    "condition": "<high|medium|low|unknown>",
    "bundle": "<high|medium|low|unknown>"
  }}
}}

Rules:
- A field you cannot fill from the listing text is "unknown". Never guess.
- "config" is the spec summary: CPU, RAM, storage, etc.
- "bundle" lists only extras beyond the main product; use [] if none.
- confidence is your certainty in that field; "unknown" when the field is "unknown"."""


def _validate_enrichment(record: dict) -> dict:
    """Enforce the enrichment schema; raise RouterError on any violation."""
    product = record.get("product")
    if not isinstance(product, dict):
        raise RouterError("missing 'product' object")
    for field in _PRODUCT_FIELDS:
        if not isinstance(product.get(field), str):
            raise RouterError(f"product.{field} must be a string or 'unknown'")
    condition = record.get("condition")
    if condition not in CONDITIONS + ("unknown",):
        raise RouterError(f"condition {condition!r} not in the fixed set")
    bundle = record.get("bundle")
    if not isinstance(bundle, list) or not all(isinstance(x, str) for x in bundle):
        raise RouterError("bundle must be a list of strings")
    confidence = record.get("confidence")
    if not isinstance(confidence, dict):
        raise RouterError("missing 'confidence' object")
    for field in _PRODUCT_FIELDS + ("condition", "bundle"):
        if confidence.get(field) not in _CONFIDENCE:
            raise RouterError(f"confidence.{field} must be one of {_CONFIDENCE}")
    return record


def enrich(listing_text: str, authored: str = "", model: str = ENRICH_MODEL) -> dict:
    """Extract Enrichment fields from full listing text via the big model.

    `authored` is the user's own description of the listing, appended as
    extra context — it supplements the listing text, and where the two
    disagree the user's account wins (per the glossary: authored overrides
    AI enrichment, so the model is told to trust it over the seller's text).

    Strict parse: a malformed or contract-violating response raises RouterError
    (a failed enrichment) — never a partial guess.
    """
    user = listing_text
    if authored.strip():
        user += (
            "\n\n---\nBuyer's note about this listing (trust this over the "
            "seller's text where they disagree):\n" + authored.strip()
        )
    content = _chat(
        [
            {"role": "system", "content": _ENRICH_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=model,
        max_tokens=1000,
    )
    return _validate_enrichment(_extract_json(content))


def sift(
    listing_summary: str,
    product_identity: str,
    model: str = SIFT_MODEL,
    exclusions: list[str] | None = None,
) -> str:
    """Judge one listing against a Bargain Search's product identity.

    Returns "match", "not_match", or "unsure". A low-confidence answer is
    demoted to "unsure" so a noisy decision never silently drops a listing.
    """
    state = f"Wanted product: {product_identity}"
    if exclusions:
        state += " Never accept these: " + "; ".join(exclusions) + "."
    state += f"\nListing: {listing_summary}"
    payload = {
        "model": model,
        "state": state,
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Is this listing the product the buyer wants?",
                "criteria": {
                    "match": "The listing is the wanted product",
                    "not_match": "The listing is not the wanted product",
                },
            }
        },
    }
    last: Exception | None = None
    for _ in range(2):  # initial attempt + one retry
        try:
            resp = requests.post(SIFT_URL, json=payload, timeout=SIFT_TIMEOUT)
            resp.raise_for_status()
            answer = resp.json()["answers"]["route"]
            if float(answer.get("confidence") or 0.0) < SIFT_CONFIDENCE_FLOOR:
                return "unsure"
            choice = answer["choice"]
            if choice not in _LABELS:
                raise RouterError(f"sift returned {choice!r}, not a valid label")
            return choice
        except (requests.RequestException, ValueError, KeyError, RouterError) as exc:
            last = exc
    raise RouterError(f"sift call failed after retry: {last}") from last


def chat(messages: list[dict], model: str = CHAT_MODEL, max_tokens: int = 2000) -> str:
    """Free-form chat completion (Bargain Search authoring)."""
    return _chat(messages, model=model, max_tokens=max_tokens)


def chat_with_tools(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = CHAT_MODEL,
    max_tokens: int = 2000,
) -> dict:
    """Chat completion that returns the full assistant message (content AND
    tool_calls), for the authoring chat's tool loop (ticket #6, ADR 0007).

    Same pinned model, temperature 0, thinking off as `chat`. Unlike
    `_chat`, empty content is not an error: a tool-call turn often has no
    prose.
    """
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools is not None:
        payload["tools"] = tools
    last: Exception | None = None
    for _ in range(2):  # initial attempt + one retry
        try:
            resp = requests.post(CHAT_URL, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]
        except (requests.RequestException, ValueError, KeyError) as exc:
            last = exc
    raise RouterError(f"router tool call failed after retry: {last}") from last
