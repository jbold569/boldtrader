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
_ACTIONS = ("match", "mint", "unknown")


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


_ENRICH_SYSTEM = f"""You read a used-hardware marketplace listing and decide what the
main product actually is, against the identities we already track.
Reply with ONLY a JSON object in this exact shape, no prose:

{{
  "product": {{
    "description": "<one prose sentence naming the main product and its defining specs>",
    "action": "<match|mint|unknown>",
    "matched_id": <int or null>,
    "confidence": "<high|medium|low|unknown>"
  }},
  "condition": "<one of: {', '.join(CONDITIONS)}, or 'unknown'>",
  "bundle": [
    {{"description": "<each extra item included beyond the main product>",
      "confidence": "<high|medium|low|unknown>"}}
  ]
}}

Rules:
- "action" is your verdict against the candidate identities listed with
  the listing. "match" = the listing IS one of those candidates: set
  "matched_id" to its id. "mint" = the listing is clearly a different,
  identifiable product that none of the candidates covers: "matched_id"
  is null. "unknown" = you cannot tell what the product is: "matched_id"
  is null and "description" is "unknown".
- Prefer "match". Only mint when you are confident the product is
  genuinely distinct from every candidate. If you are not confident, say
  "unknown" — a wrong mint is worse than an unidentified listing.
- "description" is how a human would say the product out loud: make,
  model, and the specs that distinguish it. Keep it stable and specific;
  do not restate condition, price, or seller copy.
- "confidence" is your certainty in the identity resolution, not the prose.
- "bundle" holds extras beyond the main product (cables, remotes, stands).
  Use [] if there are none. Each entry is its own product with its own
  confidence; "unknown" is not a bundle entry.
- A buyer's note overrides the seller's text where they disagree; trust
  the buyer.
- Never guess a field you cannot fill: use "unknown"."""


def _validate_enrichment(record: dict) -> dict:
    """Enforce the enrichment schema; raise RouterError on any violation.

    The shape is checked strictly because the record is persisted verbatim
    and every downstream reader (identity resolution, deal math, the SPA)
    assumes it. A model reply that misses the contract is a failed
    enrichment, not a partial one.
    """
    product = record.get("product")
    if not isinstance(product, dict):
        raise RouterError("missing 'product' object")
    description = product.get("description")
    if not isinstance(description, str) or not description.strip():
        raise RouterError("product.description must be a non-empty string")
    action = product.get("action")
    if action not in _ACTIONS:
        raise RouterError(f"product.action {action!r} not in {_ACTIONS}")
    matched_id = product.get("matched_id")
    if action == "match":
        if not isinstance(matched_id, int) or isinstance(matched_id, bool):
            raise RouterError("product.action 'match' requires an integer matched_id")
    elif matched_id is not None:
        raise RouterError(f"product.action {action!r} requires matched_id null")
    if product.get("confidence") not in _CONFIDENCE:
        raise RouterError(f"product.confidence must be one of {_CONFIDENCE}")
    condition = record.get("condition")
    if condition not in CONDITIONS + ("unknown",):
        raise RouterError(f"condition {condition!r} not in the fixed set")
    bundle = record.get("bundle")
    if not isinstance(bundle, list):
        raise RouterError("bundle must be a list")
    for item in bundle:
        if not isinstance(item, dict):
            raise RouterError("bundle entries must be objects")
        if not isinstance(item.get("description"), str) or not item["description"].strip():
            raise RouterError("bundle.description must be a non-empty string")
        if item.get("confidence") not in _CONFIDENCE:
            raise RouterError(f"bundle.confidence must be one of {_CONFIDENCE}")
    return record


def enrich(
    listing_text: str,
    candidates: list[dict] | None = None,
    authored: str = "",
    model: str = ENRICH_MODEL,
) -> dict:
    """Resolve the main product of a listing via the big model.

    `candidates` is the existing Product Identity list (id + description)
    the model chooses from; an empty list means nothing is tracked yet, so
    every answer is a mint or unknown. `authored` is the buyer's own
    account of the listing and overrides the seller's text (GLOSSARY:
    Correction).

    Strict parse: a malformed or contract-violating response raises
    RouterError (a failed enrichment) — never a partial guess.
    """
    lines = [f"{c['id']}: {c['description']}" for c in candidates or []]
    user = "Known product identities:\n" + ("\n".join(lines) if lines else "(none)")
    user += "\n\n---\nListing text:\n" + listing_text
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


_SYNTH_SYSTEM = """You write the Product Identity description for a deal-hunting
system. The identity is one prose sentence naming the exact product a buyer
is hunting: make, model, and the defining specs. It is what the sift model
will judge every future listing against, so it must be specific enough to
separate the wanted product from near-misses, and free of price, condition,
and seller copy.

Reply with ONLY the description sentence. No preamble, no quotes, no JSON."""


def synthesize_description(evidence: dict, model: str = CHAT_MODEL) -> str:
    """Draft the identity prose from an evidence pack (ticket #55, ADR 0012).

    The pack carries the mode ("synthesize" first draft, "retune" revision),
    the matched listing context, and for a retune the counter-evidence:
    rejects with reasons, authored descriptions, the current description,
    and the deal threshold. Plain chat (not the decision lane): this is
    creative writing, not classification.
    """
    parts = [evidence.get("current_description") or "(none yet)"]
    if evidence.get("mode") == "retune":
        parts.append(
            "Rejections and corrections since this description was written:\n"
            + json.dumps(
                {
                    "rejects": evidence.get("rejects", []),
                    "authored_descriptions": evidence.get("authored_descriptions", []),
                    "deal_threshold": evidence.get("deal_threshold"),
                },
                ensure_ascii=False,
            )
        )
    parts.append(
        "Listings matching the search so far:\n"
        + json.dumps(evidence.get("matched", []), ensure_ascii=False)
    )
    parts.append(
        "Rewrite the description so it names the product these listings "
        "actually are, and nothing they rejected."
    )
    content = _chat(
        [
            {"role": "system", "content": _SYNTH_SYSTEM},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        model=model,
        max_tokens=200,
    )
    text = content.strip().strip('"')
    if not text:
        raise RouterError("synthesis returned empty description")
    return text



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


def stream_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str = CHAT_MODEL,
    max_tokens: int = 2000,
):
    """POST a streaming chat completion; yield each parsed SSE chunk dict.

    The router streams `data:`-only JSON frames and ends with `data: [DONE]`
    (ticket #16 findings). No retry: once deltas are in flight a retry would
    duplicate them; the chat turn owns failure handling instead.
    """
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
    }
    if tools is not None:
        payload["tools"] = tools
    resp = requests.post(CHAT_URL, json=payload, timeout=TIMEOUT, stream=True)
    try:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            text = line.decode("utf-8")
            if not text.startswith("data:"):
                continue
            data = text[len("data:"):].strip()
            if data == "[DONE]":
                return
            yield json.loads(data)
    finally:
        resp.close()
