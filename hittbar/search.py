"""Discovery by search: the agent cannot read the whole catalogue, it queries an index.

This is how discovery works once a catalogue outgrows a context window - an MCP registry
or a tool-search tool returns the top k entries and the agent only ever sees those. So the
question changes from "can the model pick" to "does the right product reach the top k".

BM25 over one document per API product, built from the same three views as the agent eval.
No model, no network, no cost - fully deterministic.

Usage: python -m hittbar.search
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter

from . import catalog
from .evaluate import ROOT, load_tasks

KS = (1, 3, 5)


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-zåäöæø0-9]+", text.lower())


def documents(condition: str) -> dict[str, str]:
    ai = catalog.ai_descriptions()
    docs = {}
    for p in catalog.load()["pages"]:
        page = f"{p['name']} {p['meta_description']}"
        if condition == "ai":
            page += " " + ai[p["id"]]
        elif condition == "pagetext":
            page += " " + p["page_text"]
        for pr in p["products"]:
            apis = " ".join(f"{a['name']} {a['description']}" for a in pr["apis"])
            docs[pr["id"]] = f"{page} {pr['name']} {pr['description']} {apis}"
    return docs


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.2, b: float = 0.75):
        self.ids = list(docs)
        self.tf = [Counter(tokens(docs[i])) for i in self.ids]
        self.len = [sum(tf.values()) for tf in self.tf]
        self.avg = sum(self.len) / len(self.len)
        df = Counter(t for tf in self.tf for t in tf)
        n = len(self.ids)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.k1, self.b = k1, b

    def rank(self, query: str) -> list[str]:
        q = tokens(query)
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            scores.append(s)
        # ties broken by id so the ranking is reproducible
        return [self.ids[i] for i in sorted(range(len(self.ids)), key=lambda i: (-scores[i], self.ids[i]))]


def evaluate() -> dict:
    tasks = [t for t in load_tasks() if t["accept"]]  # "none" has nothing to retrieve
    out = {}
    for cond in catalog.CONDITIONS:
        index = BM25(documents(cond))
        hits = {k: [] for k in KS}
        rows = []
        for t in tasks:
            ranking = index.rank(t["text"])
            rank = min((ranking.index(a) + 1 for a in t["accept"]), default=None)
            rows.append({"task": t["id"], "kind": t["kind"], "lang": t["lang"], "rank": rank})
            for k in KS:
                hits[k].append(rank is not None and rank <= k)
        def rate(xs):
            return round(sum(xs) / len(xs), 3) if xs else None
        out[cond] = {
            **{f"recall@{k}": rate(hits[k]) for k in KS},
            "recall@3_by_lang": {lang: rate([r["rank"] <= 3 for r in rows if r["lang"] == lang])
                                 for lang in sorted({r["lang"] for r in rows})},
            "recall@3_by_kind": {kind: rate([r["rank"] <= 3 for r in rows if r["kind"] == kind])
                                 for kind in sorted({r["kind"] for r in rows})},
            "median_rank": sorted(r["rank"] for r in rows)[len(rows) // 2],
            "rows": rows,
        }
    return out


def main() -> None:
    result = evaluate()
    path = ROOT / "runs" / f"search-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(result, indent=1) + "\n")
    for cond, r in result.items():
        print(cond, {k: v for k, v in r.items() if k != "rows"})
    print(f"-> {path}")


if __name__ == "__main__":
    main()
