"""Snapshot If's public developer portal into data/catalog.json.

Everything here is public: the portal publishes /llms-full.txt for AI agents, and its
llms.txt header says `ai-use: allow-summarization, allow-indexing, allow-generation,
allow-qa, disallow-fine-tuning`. Nothing in this repo calls an If API - only the
public catalogue pages are read, once, politely.

Each product page carries its data in Next.js `__NEXT_DATA__`. Two levels matter:
- a *page* (44 of them) is where the CMS field `aiDescription` lives;
- an *API product* (several per page) is what an agent would actually call.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path

import httpx

BASE = "https://developer.if-insurance.com"
OUT = Path(__file__).resolve().parent.parent / "data" / "catalog.json"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def strip_html(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def next_data(page_html: str) -> dict | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, re.S)
    return json.loads(m.group(1)) if m else None


def own_text(server_data: dict) -> str:
    """The page's own prose, in document order.

    Skips relatedPagesContentArea: those blocks are *other* pages' teasers. On the
    Swedish car insurance page they talk about Norwegian customers, which is exactly
    the confusion a discovery eval should not inherit from its own context.
    """
    parts: list[str] = []

    def walk(o, path=""):
        if "relatedPagesContentArea" in path or path.endswith(("shareDescription", "crosslinkPreamble")):
            return
        if isinstance(o, dict):
            if o.get("propertyDataType") in ("PropertyXhtmlString", "PropertyLongString") \
                    and isinstance(o.get("value"), str):
                t = strip_html(o["value"])
                if len(t) > 30 and t not in parts:
                    parts.append(t)
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for v in o:
                walk(v, path)

    walk(server_data)
    return "\n".join(parts)


def parse_page(url: str, page_html: str) -> dict | None:
    d = next_data(page_html)
    if not d:
        return None
    pp = d["props"]["pageProps"]
    if pp.get("page", {}).get("_typeName") != "ProductPage":
        return None
    sd = pp["page"]["_serverData"]
    path = url.split("/apis/", 1)[1].strip("/")
    products = []
    for p in pp.get("products") or []:
        det = p["details"]
        products.append({
            "id": slug(det.get("productName") or p["apimProduct"]["displayName"]),
            "name": det.get("productName") or p["apimProduct"]["displayName"],
            "description": (det.get("shortDescription") or "").strip(),
            "apis": [{"name": a.get("displayName", ""), "description": (a.get("description") or "").strip()}
                     for a in p.get("apimApis") or []],
        })
    return {
        # the leaf slug is not unique: manage-insrt-ancillary-insurances is published
        # under both other/ and self-service/, so the id carries the category
        "id": f'{path.split("/")[0].lower()}/{path.split("/")[-1]}',
        "url": url,
        "category": path.split("/")[0],
        "name": sd.get("name", ""),
        "meta_description": strip_html((sd.get("metaDescription") or {}).get("value", "")),
        "ai_description": strip_html((sd.get("aiDescription") or {}).get("value", "")),
        "page_text": own_text(sd),
        "products": products,
    }


def main() -> None:
    with httpx.Client(headers={"User-Agent": "hittbar-research (public catalogue snapshot)"},
                      timeout=30, follow_redirects=True) as c:
        index = c.get(f"{BASE}/llms-full.txt").text
        urls = sorted({u.rstrip("/") + "/" for u in re.findall(rf"{BASE}/apis/[^)\s]+", index)
                       if "documentation" not in u})
        pages = []
        for u in urls:
            p = parse_page(u, c.get(u).text)
            if p:
                pages.append(p)
            time.sleep(0.5)

    # product ids must be unique across the whole catalogue - the eval scores on them
    seen: dict[str, str] = {}
    for p in pages:
        for pr in p["products"]:
            if pr["id"] in seen and seen[pr["id"]] != p["id"]:
                pr["id"] = f'{pr["id"]}--{p["category"].lower()}'
            seen[pr["id"]] = p["id"]

    snapshot = {"source": BASE, "snapshot_date": time.strftime("%Y-%m-%d"), "pages": pages}
    OUT.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n")
    n_prod = sum(len(p["products"]) for p in pages)
    n_ai = sum(1 for p in pages if p["ai_description"])
    print(f"{len(pages)} pages, {n_prod} API products, aiDescription filled on {n_ai}/{len(pages)} -> {OUT}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
