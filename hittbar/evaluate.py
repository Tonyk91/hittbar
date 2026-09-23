"""Run every task under every condition, several times, and score deterministically.

Grading needs no model: a task lists the product ids that satisfy it, and an empty list
means the only right answer is "none". Scoring is exact string membership.

Usage: python -m hittbar.evaluate [--runs 3] [--conditions published,ai,pagetext]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import anthropic

from . import catalog
from .agent import MODEL, choose

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "data" / "tasks.jsonl"

# $ per million tokens: input, output. Cache writes cost 1.25x input, reads 0.1x.
PRICES = {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0)}


def load_tasks() -> list[dict]:
    return [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]


def correct(task: dict, product: str) -> bool:
    return product == "none" if not task["accept"] else product in task["accept"]


def page_correct(task: dict, product: str) -> bool:
    """Right page, possibly wrong product on it - the level aiDescription lives at."""
    if not task["accept"]:
        return product == "none"
    if product == "none":
        return False
    return catalog.page_of(product) in {catalog.page_of(a) for a in task["accept"]}


def cost(r: dict) -> float:
    pin, pout = PRICES[MODEL]
    return (r["input_tokens"] * pin + r["cache_write_tokens"] * pin * 1.25
            + r["cache_read_tokens"] * pin * 0.1 + r["output_tokens"] * pout) / 1e6


def summarise(rows: list[dict], tasks: list[dict]) -> dict:
    by_id = {t["id"]: t for t in tasks}
    out: dict = {}
    for cond in sorted({r["condition"] for r in rows}):
        rs = [r for r in rows if r["condition"] == cond]
        runs = sorted({r["run"] for r in rs})
        per_run = [sum(r["correct"] for r in rs if r["run"] == k) / len(tasks) for k in runs]
        kinds = defaultdict(list)
        for r in rs:
            kinds[by_id[r["task"]]["kind"]].append(r["correct"])
        answerable = [r for r in rs if by_id[r["task"]]["accept"]]
        unanswerable = [r for r in rs if not by_id[r["task"]]["accept"]]
        out[cond] = {
            "accuracy_per_run": [round(x, 3) for x in per_run],
            "accuracy_mean": round(sum(per_run) / len(per_run), 3),
            "page_accuracy_mean": round(sum(r["page_correct"] for r in rs) / len(rs), 3),
            "by_kind": {k: round(sum(v) / len(v), 3) for k, v in sorted(kinds.items())},
            # the two ways abstention goes wrong are not the same failure
            "false_none": sum(r["product"] == "none" for r in answerable),
            "invented_match": sum(r["product"] != "none" for r in unanswerable),
            "calls": len(rs),
            "cost_usd": round(sum(cost(r) for r in rs), 4),
            "p95_latency_s": round(sorted(r["latency_s"] for r in rs)[int(0.95 * (len(rs) - 1))], 2),
        }
    return out


def run_condition(client, cond: str, tasks: list[dict], runs: int) -> list[dict]:
    rows = []
    # one call first so the catalogue prefix is written to cache before the fan-out
    jobs = [(k, t) for k in range(runs) for t in tasks]
    first, rest = jobs[0], jobs[1:]

    def one(job):
        k, t = job
        c = choose(client, cond, t["text"])
        r = {"condition": cond, "run": k, "task": t["id"], **asdict(c)}
        r["correct"] = correct(t, c.product)
        r["page_correct"] = page_correct(t, c.product)
        return r

    rows.append(one(first))
    with ThreadPoolExecutor(8) as ex:
        rows.extend(ex.map(one, rest))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--conditions", default=",".join(catalog.CONDITIONS))
    args = ap.parse_args()

    tasks = load_tasks()
    client = anthropic.Anthropic()
    rows = []
    for cond in args.conditions.split(","):
        t0 = time.time()
        rows += run_condition(client, cond, tasks, args.runs)
        print(f"{cond}: {time.time() - t0:.0f}s", file=sys.stderr)

    summary = summarise(rows, tasks)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "runs" / f"run-{stamp}.json"
    out.write_text(json.dumps({
        "model": MODEL, "runs": args.runs,
        "tasks_sha256": hashlib.sha256(TASKS.read_bytes()).hexdigest(),
        "catalog_snapshot": catalog.load()["snapshot_date"],
        "summary": summary, "rows": rows,
    }, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=1))
    print(f"-> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
