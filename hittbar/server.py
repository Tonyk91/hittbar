"""An MCP server for If's API catalogue, built the way the measurements say it should be.

Two tools:

  search_api_catalogue(query)  BM25 over the pagetext view - the best search lens measured
                               (recall@5 0.91-0.93 with agent-written queries)
  get_api_product(product_id)  one product's page, APIs and descriptions

The tool description states the catalogue's language. That one sentence moved Swedish
recall@5 from 0.27-0.40 to 0.73-0.93 in hittbar.query, so it is not decoration: a test
fails if it goes missing.

Read-only, no network, no If API is ever called. Serves the 2026-09-24 snapshot.

Usage: python -m hittbar.server            (stdio, for Claude Desktop / Claude Code / any MCP client)
"""
from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import catalog
from .search import BM25, documents

LANGUAGE = "The catalogue is written in English."
SEARCH_DESCRIPTION = (
    "Keyword search over If Insurance's public API catalogue. Returns the best-matching API "
    f"products, best first. {LANGUAGE} Write the query in English, whatever language the "
    "request is in, and name the country when it matters: many products exist once per "
    "Nordic market (DK, NO, SE, FI). Use get_api_product to read a product's APIs."
)


class Hit(TypedDict):
    product_id: str
    name: str
    description: str
    page: str
    url: str


class Api(TypedDict):
    name: str
    description: str


class Product(TypedDict):
    product_id: str
    name: str
    description: str
    page: str
    category: str
    url: str
    apis: list[Api]


READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
MAX_LIMIT = 20

server = MCPServer(
    "hittbar",
    instructions=(
        "Unofficial, read-only view of If Insurance's public developer portal "
        f"(snapshot {catalog.load()['snapshot_date']}). {LANGUAGE}"
    ),
)


@lru_cache
def _index() -> BM25:
    return BM25(documents("pagetext"))


@lru_cache
def _products() -> dict[str, tuple[dict, dict]]:
    return {pr["id"]: (p, pr) for p in catalog.load()["pages"] for pr in p["products"]}


@server.tool(description=SEARCH_DESCRIPTION, annotations=READ_ONLY)
def search_api_catalogue(query: str, limit: int = 5) -> list[Hit]:
    if not query.strip():
        raise ToolError("query is empty")
    limit = max(1, min(limit, MAX_LIMIT))
    out = []
    for pid in _index().rank(query)[:limit]:
        page, pr = _products()[pid]
        out.append({"product_id": pid, "name": pr["name"], "description": pr["description"],
                    "page": page["name"], "url": page["url"]})
    return out


@server.tool(
    description="Read one API product from the catalogue: its page, description and every API "
                "it contains. Takes a product_id returned by search_api_catalogue.",
    annotations=READ_ONLY,
)
def get_api_product(product_id: str) -> Product:
    if product_id not in _products():
        raise ToolError(f"unknown product_id {product_id!r} - use search_api_catalogue to find one")
    page, pr = _products()[product_id]
    apis, seen = [], set()
    for a in pr["apis"]:
        key = (a["name"], a["description"])
        if key not in seen:  # the portal lists some API versions twice with identical text
            seen.add(key)
            apis.append({"name": a["name"], "description": a["description"]})
    return {"product_id": product_id, "name": pr["name"], "description": pr["description"],
            "page": page["name"], "category": page["category"], "url": page["url"], "apis": apis}


if __name__ == "__main__":
    server.run()
