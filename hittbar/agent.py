"""The agent under test: given a task and the catalogue, pick one API product or none.

The answer is constrained by a JSON schema whose product field is an enum of the
catalogue's ids plus "none", so a wrong answer is always a real, existing product -
never a hallucinated name that a lenient grader might half-credit.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import anthropic

from . import catalog

MODEL = os.environ.get("HITTBAR_MODEL", "claude-opus-5")

SYSTEM = """You are an integration agent for developers building on If Insurance's public API \
catalogue. A developer describes what they need; you pick the single API product they should \
integrate with.

Rules:
- Choose exactly one product id from the catalogue below, or "none".
- Answer "none" when no product in the catalogue does what the developer needs. A product that \
only does part of it (for example quoting when they need to buy, or a different country) is not \
a match.
- Market matters: a product for one Nordic country does not serve another.
- Give a one-sentence reason first, then the product id.

# Catalogue
"""


def schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "product": {"type": "string", "enum": [*catalog.product_ids(), "none"]},
        },
        "required": ["reason", "product"],
        "additionalProperties": False,
    }


@dataclass
class Choice:
    product: str
    reason: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    latency_s: float


def choose(client: anthropic.Anthropic, condition: str, task_text: str) -> Choice:
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        # the catalogue is the large, stable prefix: cache it, keep the task after it
        system=[{"type": "text", "text": SYSTEM + catalog.render(condition),
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": task_text}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema()}},
    )
    dt = time.perf_counter() - t0
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens before the answer")
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    u = resp.usage
    return Choice(
        product=data["product"], reason=data["reason"],
        input_tokens=u.input_tokens,
        cache_write_tokens=u.cache_creation_input_tokens or 0,
        cache_read_tokens=u.cache_read_input_tokens or 0,
        output_tokens=u.output_tokens, latency_s=dt,
    )
