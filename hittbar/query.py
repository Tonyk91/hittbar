"""Agent-written search queries: does the language gap survive a model writing the query?

The raw-text search lens found 0/7 Swedish tasks in the top 3. The obvious objection is
that no agent searches with the user's words verbatim - it writes its own query. So here
the model sees only the task and a search tool's description, never the catalogue, and
writes the query. Two tool descriptions:

  plain  - says what the tool searches, nothing about language
  hint   - the same, plus one sentence: the catalogue is written in English

The queries then go through the same BM25 index as before, under all three catalogue
views. Only retrieval is measured: whether the right product reaches the top k. Picking
among visible candidates is already covered by the full-context eval, which scored 66/66.

Usage: python -m hittbar.query [--runs 3]
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic

from . import catalog
from .agent import MODEL
from .evaluate import PRICES, ROOT, load_tasks
from .search import BM25, KS, documents

TOOL = ("You are an integration agent. You have one tool, search_api_catalogue(query), a "
        "keyword search over If Insurance's API catalogue that returns the five best-matching "
        "API products. Write the single query you would send for the developer's need below.")
VARIANTS = {"plain": TOOL, "hint": TOOL + " The catalogue is written in English."}


def write_query(client: anthropic.Anthropic, system: str, task_text: str) -> tuple[str, float]:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": task_text}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
            "type": "object", "properties": {"query": {"type": "string"}},
            "required": ["query"], "additionalProperties": False}}},
    )
    if resp.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason={resp.stop_reason}")
    u = resp.usage
    pin, pout = PRICES[MODEL]
    cost = (u.input_tokens * pin + u.output_tokens * pout) / 1e6
    return json.loads(next(b.text for b in resp.content if b.type == "text"))["query"], cost


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    tasks = [t for t in load_tasks() if t["accept"]]
    client = anthropic.Anthropic()
    jobs = [(v, k, t) for v in VARIANTS for k in range(args.runs) for t in tasks]
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda j: write_query(client, VARIANTS[j[0]], j[2]["text"]), jobs))
    queries = [{"variant": v, "run": k, "task": t["id"], "lang": t["lang"], "kind": t["kind"],
                "query": q, "cost_usd": c} for (v, k, t), (q, c) in zip(jobs, results)]

    by_id = {t["id"]: t for t in tasks}
    summary = {}
    for cond in catalog.CONDITIONS:
        index = BM25(documents(cond))
        for v in VARIANTS:
            rows = []
            for q in (q for q in queries if q["variant"] == v):
                ranking = index.rank(q["query"])
                rank = min(ranking.index(a) + 1 for a in by_id[q["task"]]["accept"])
                rows.append({**q, "rank": rank})

            def rate(rs, k):
                return round(sum(r["rank"] <= k for r in rs) / len(rs), 3) if rs else None
            summary[f"{cond}/{v}"] = {
                **{f"recall@{k}": rate(rows, k) for k in KS},
                "recall@5_by_lang": {lang: rate([r for r in rows if r["lang"] == lang], 5)
                                     for lang in ("en", "sv", "no")},
                "recall@5_per_run": [rate([r for r in rows if r["run"] == k], 5) for k in range(args.runs)],
            }

    out = ROOT / "runs" / f"query-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"model": MODEL, "runs": args.runs,
                               "cost_usd": round(sum(q["cost_usd"] for q in queries), 4),
                               "summary": summary, "queries": queries},
                              indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1))
    print(f"cost ${sum(q['cost_usd'] for q in queries):.2f} -> {out}")


if __name__ == "__main__":
    main()
