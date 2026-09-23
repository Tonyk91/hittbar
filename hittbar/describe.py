"""Draft the aiDescription field for every page - the CMS field that is empty on 44/44 today.

The generator sees one page's own public content plus the names of the other pages, so it
can say what the page is NOT for. It never sees the task set: tasks were committed before
this file first ran.

Output is a draft for a human to review, not a finished text. Every claim must come from
the page's own content; the prompt forbids inventing endpoints, scopes or markets.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import anthropic

from . import catalog
from .agent import MODEL

PROMPT = """You are writing the `aiDescription` field for one page of If Insurance's public API \
developer portal. The field is read by AI agents that must decide which API product to \
integrate for a developer's need. It is not marketing copy.

Write 60-120 words of plain text, in this order:
1. What the page's API products do, in concrete verbs (quote, buy, look up, register, notify).
2. Who calls them and how they authenticate, if the source says so (system to system, end user \
with BankID, partner with an agreement).
3. The market: which country or countries, and state plainly if it is one country only.
4. If the page has several products, one short clause per product id saying when to pick it.
5. "Not for:" - the nearest confusions, pointing to the other page ids by id, if any exist.

Use only facts stated in the source below. Do not invent endpoints, scopes, markets or \
features. If the source is vague, be brief rather than filling the gap.

# This page
{page}

# Other pages in the catalogue (id - name)
{others}
"""


def page_source(p: dict) -> str:
    lines = [f"id: {p['id']}", f"name: {p['name']}"]
    if p["meta_description"]:
        lines.append(f"meta: {p['meta_description']}")
    if p["page_text"]:
        lines.append(f"page text: {p['page_text']}")
    if not p["products"]:
        lines.append("products: none published on this page")
    for pr in p["products"]:
        lines.append(f"product {pr['id']}: {pr['name']}. {pr['description']}")
        for a in {(a["name"], a["description"]) for a in pr["apis"]}:
            lines.append(f"  API {a[0]}: {a[1]}")
    return "\n".join(lines)


def describe(client: anthropic.Anthropic, p: dict, others: str) -> str:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": PROMPT.format(page=page_source(p), others=others)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": {
            "type": "object", "properties": {"ai_description": {"type": "string"}},
            "required": ["ai_description"], "additionalProperties": False}}},
    )
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"{p['id']}: stop_reason={resp.stop_reason}")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))["ai_description"]


def main() -> None:
    client = anthropic.Anthropic()
    pages = catalog.load()["pages"]
    out = {}
    with ThreadPoolExecutor(6) as ex:
        futs = {}
        for p in pages:
            others = "\n".join(f"{o['id']} - {o['name']}" for o in pages if o["id"] != p["id"])
            futs[p["id"]] = ex.submit(describe, client, p, others)
        for pid, f in futs.items():
            out[pid] = f.result()
    path = catalog.DATA / "ai_descriptions.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out)} aiDescriptions -> {path} (model {MODEL})", file=sys.stderr)


if __name__ == "__main__":
    main()
