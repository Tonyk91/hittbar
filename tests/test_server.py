"""The MCP server, called through the protocol - in-process and as a real stdio subprocess."""
import sys

import anyio
import pytest
from mcp import Client, StdioServerParameters

from hittbar.server import LANGUAGE, server

# The query Opus wrote for task t47 once the tool stated the language, and the one it wrote before
ENGLISH = "home insurance sales API for private customers Sweden, quote and purchase, three coverage levels"
SWEDISH = "hemförsäkring privat Sverige försäljning API offert tre skyddsnivåer köp i app"


def call(name, args, target=server):
    async def go():
        async with Client(target) as c:
            return await c.call_tool(name, args)
    return anyio.run(go)


def ids(result):
    return [r["product_id"] for r in result.structured_content["result"]]


def test_tools_are_listed_read_only_and_state_the_language():
    async def go():
        async with Client(server) as c:
            return (await c.list_tools()).tools
    tools = {t.name: t for t in anyio.run(go)}
    assert set(tools) == {"search_api_catalogue", "get_api_product"}
    # the sentence that moved Swedish recall@5 from 0.27-0.40 to 0.73-0.93
    assert LANGUAGE in tools["search_api_catalogue"].description
    assert all(t.annotations.read_only_hint for t in tools.values())


def test_english_query_finds_the_product_first():
    assert ids(call("search_api_catalogue", {"query": ENGLISH}))[0] == "buy-home-insurance-se"


def test_swedish_query_misses_it_which_is_why_the_description_says_english():
    assert "buy-home-insurance-se" not in ids(call("search_api_catalogue", {"query": SWEDISH}))


def test_limit_is_respected_and_capped():
    assert len(ids(call("search_api_catalogue", {"query": "car insurance", "limit": 3}))) == 3
    assert len(ids(call("search_api_catalogue", {"query": "car insurance", "limit": 500}))) == 20


def test_empty_query_is_a_tool_error():
    assert call("search_api_catalogue", {"query": "  "}).is_error


def test_get_api_product_returns_apis_without_duplicates():
    r = call("get_api_product", {"product_id": "buy-home-insurance-se"}).structured_content
    assert r["url"].startswith("https://developer.if-insurance.com/")
    assert r["apis"]
    keys = [(a["name"], a["description"]) for a in r["apis"]]
    assert len(keys) == len(set(keys))


def test_unknown_product_is_a_tool_error_that_points_to_search():
    r = call("get_api_product", {"product_id": "does-not-exist"})
    assert r.is_error
    assert "search_api_catalogue" in r.content[0].text


def test_runs_as_a_stdio_subprocess():
    params = StdioServerParameters(command=sys.executable, args=["-m", "hittbar.server"])
    assert ids(call("search_api_catalogue", {"query": ENGLISH}, target=params))[0] == "buy-home-insurance-se"
