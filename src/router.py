"""boldhalo router client: OpenAI-compatible chat completions for Enrichment and triage.

The router (http://model.boldhalo.home) owns model routing; this client passes
the model name per call and never cares which weights answer. Errors are loud:
one retry, then raise. `/classify` (NPU triage) is not live on the router yet
(404, verified 2026-10-24), so triage runs through chat completions for now.
"""

from __future__ import annotations

import json

import requests

BASE_URL = "http://model.boldhalo.home/v1/chat/completions"

ENRICH_MODEL = "qwen3.8-flash-next-w4b-q8-halogen"
# decider-0.8b is not on the router yet (404, verified 2026-10-24); interim
# triage runs the small-model prompt on the loaded chat model.
TRIAGE_MODEL = ENRICH_MODEL

TIMEOUT = 120  # seconds; enrichment reads 1-3k tokens per call

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
            resp = requests.post(BASE_URL, json=payload, timeout=TIMEOUT)
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


def enrich(listing_text: str, model: str = ENRICH_MODEL) -> dict:
    """Extract Enrichment fields from full listing text via the big model.

    Strict parse: a malformed or contract-violating response raises RouterError
    (a failed enrichment) — never a partial guess.
    """
    content = _chat(
        [
            {"role": "system", "content": _ENRICH_SYSTEM},
            {"role": "user", "content": listing_text},
        ],
        model=model,
        max_tokens=1000,
    )
    return _validate_enrichment(_extract_json(content))


def triage(listing_summary: str, product_identity: str, model: str = TRIAGE_MODEL) -> str:
    """Judge one listing against a Bargain Search's product identity.

    Returns "match", "not_match", or "unsure". Interim implementation: chat
    completions with a small-model prompt. Swap the body when halogen's
    /classify endpoint goes live; keep this signature.
    """
    system = (
        "You decide whether a marketplace listing is the product the buyer wants. "
        "Reply with exactly one word: match, not_match, or unsure. "
        "If the listing could be the product but the text is too vague to tell, say unsure."
    )
    user = f"Wanted product: {product_identity}\nListing: {listing_summary}"
    content = _chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=model,
        max_tokens=8,
    )
    label = content.strip().lower().replace("-", "_").replace(" ", "_")
    if label not in _LABELS:
        raise RouterError(f"triage returned {content!r}, not a valid label")
    return label
