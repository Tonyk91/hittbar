"""The catalogue as an agent sees it, under three conditions.

A  published   - what the portal shows today: page, product and API names and descriptions
B  ai          - A plus a generated aiDescription per page (the CMS field that is empty today)
C  pagetext    - A plus the page's own prose, the same kind of extra text B adds but not
                 written for agents

C is the control. If B beats A only because it adds words, C should beat A by as much.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
CONDITIONS = ("published", "ai", "pagetext")


@lru_cache
def load() -> dict:
    return json.loads((DATA / "catalog.json").read_text())


@lru_cache
def ai_descriptions() -> dict[str, str]:
    p = DATA / "ai_descriptions.json"
    return json.loads(p.read_text()) if p.exists() else {}


def product_ids() -> list[str]:
    return [pr["id"] for p in load()["pages"] for pr in p["products"]]


def page_of(product_id: str) -> str:
    for p in load()["pages"]:
        if any(pr["id"] == product_id for pr in p["products"]):
            return p["id"]
    raise KeyError(product_id)


def render(condition: str) -> str:
    """One deterministic text block - identical bytes on every call, so it caches."""
    if condition not in CONDITIONS:
        raise ValueError(condition)
    ai = ai_descriptions()
    if condition == "ai" and len(ai) < len(load()["pages"]):
        raise RuntimeError("data/ai_descriptions.json is missing pages - run hittbar.describe first")
    out = []
    for p in load()["pages"]:
        if not p["products"]:
            continue  # a page with no API product has nothing to call
        out.append(f"## {p['name']}  [page: {p['id']}]")
        if p["meta_description"]:
            out.append(p["meta_description"])
        if condition == "ai":
            out.append(f"Agent guide: {ai[p['id']]}")
        elif condition == "pagetext" and p["page_text"]:
            out.append(f"Page text: {p['page_text']}")
        for pr in p["products"]:
            out.append(f"- product `{pr['id']}`: {pr['name']}. {pr['description']}")
            seen = set()
            for a in pr["apis"]:
                key = (a["name"], a["description"])
                if key in seen:
                    continue  # the portal lists some API versions twice with identical text
                seen.add(key)
                out.append(f"    - API {a['name']}: {a['description']}")
        out.append("")
    return "\n".join(out)
