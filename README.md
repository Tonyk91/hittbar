# Hittbar

**Can an AI agent find the right API in If Insurance's public catalogue, and what would actually make it better at it?**

*Hittbar* is Swedish for *findable*.

If's [developer portal](https://developer.if-insurance.com/) lists 44 product pages and 68 API
products. Its CMS already has a field called `aiDescription` on every product page, and on the
day of this snapshot it was **empty on all 44**. The obvious move is to fill it. This repo
measures whether that would help, before anyone spends the effort.

> Unofficial. Built from the portal's public pages only; the portal's `llms.txt` allows
> summarisation, indexing, generation and Q&A. No If API is ever called. Snapshot: 2026-09-24.

## The short answer

1. **When the agent reads the whole catalogue, today's descriptions already work.** Claude Opus 5
   picked the right product for **66 of 66 tasks, in every condition and every run**, including
   the traps. Adding `aiDescription` made each call 77% larger, 64% more expensive and slower,
   for no gain.
2. **When the agent has to search, language is the gap, not description quality.** The catalogue
   is English only. Given a search tool with no hint about language, Opus wrote Swedish or
   Norwegian queries for **14 of 24** Nordic-language tasks, and Swedish tasks reached the top 5
   only **27–40%** of the time. **One sentence in the tool description**, *"The catalogue is
   written in English"*, took that to **73–93%** and made every query English.
3. **For search, more relevant words beat words written for agents.** The control condition
   (the page's own prose) retrieved better than the generated `aiDescription`.

What this would mean for the catalogue: state the language in whatever tool or MCP server
exposes it; don't prioritise hand-written agent guides at this size; when the catalogue outgrows
a context window, index the page text that already exists.

**And then I built the thing the numbers point to:** an MCP server over the catalogue
(`hittbar/server.py`) whose search indexes the page text and whose tool description states the
language. [Below](#the-mcp-server).

## The setup

**Catalogue.** `hittbar/scrape.py` reads the portal's public `/llms-full.txt`, then each product
page's embedded Next.js data: page, API products, their APIs and descriptions → `data/catalog.json`.

**Tasks.** 66 developer needs in `data/tasks.jsonl`, 55 English, 7 Swedish, 4 Norwegian, in four
kinds:

| Kind | n | Example |
|---|---|---|
| direct | 22 | *A vet clinic wants to check what a dog's insurance covers on the day of treatment.* |
| sibling | 29 | *…system to system, no end-user login* vs *…the customer logs in with BankID* |
| country | 7 | *Quote contents insurance for a rented flat in Helsinki.* (DK/NO/SE/FI variants exist) |
| none | 8 | *Let a customer in Finland buy car insurance.* Finland is price-only; the right answer is "none". |

**The tasks were committed (9e32d60) before any `aiDescription` was generated**, so they could
not be tuned to the result.

**Three views of the catalogue**, identical except for one addition:

| Condition | What the agent sees |
|---|---|
| `published` | The portal as it is: page, product and API names and descriptions |
| `ai` | + a generated `aiDescription` per page (`hittbar/describe.py`, drafts in `data/ai_descriptions.json`) |
| `pagetext` | + the page's own prose. **The control:** extra text of the same size class, not written for agents |

If `ai` beat `published` only because it adds words, `pagetext` would beat it by as much.

**Grading is deterministic.** Each task lists the product ids that satisfy it; an empty list means
only "none" is right. The agent's answer is constrained by a JSON schema whose product field is an
enum of real ids, so a wrong answer is always a real, wrong product. No LLM judge anywhere.

## Results

### 1. Full catalogue in context: `hittbar/evaluate.py`

Claude Opus 5, effort `low`, three runs per condition, 198 calls per condition.

| Condition | Correct | Wrong product | "None" when an API existed | Invented a match | Cost / 66 tasks | p95 latency |
|---|---|---|---|---|---|---|
| published | **66/66 ×3** | 0 | 0 | 0 | $0.72 | 2.8 s |
| ai | 66/66 ×3 | 0 | 0 | 0 | $1.17 | 6.8 s |
| pagetext | 66/66 ×3 | 0 | 0 | 0 | $1.30 | 3.7 s |

A ceiling. The eval cannot separate the conditions, and I checked that the 100% is real by reading
the reasons on the hardest traps: a used-car warranty page that has no product (the right answer
lives on another page), managing a subscription to roadside events (not the events themselves),
and Finnish car insurance, which can be priced but not bought.

### 2. Search with the developer's own words: `hittbar/search.py`

BM25 over one document per product, no model. A deliberately naive baseline.

| Condition | Right product first | In top 3 | In top 5 | Swedish tasks, top 3 |
|---|---|---|---|---|
| published | 50% | 74% | 79% | **0 / 5** |
| ai | 60% | 71% | 81% | 0 / 5 |
| pagetext | 53% | 67% | 76% | 0 / 5 |

### 3. Search with a query the agent writes: `hittbar/query.py`

The objection to table 2 is that no agent searches with the user's words verbatim. So here Opus
sees only the task and a search tool's description, never the catalogue, and writes the query.
Three runs, 58 answerable tasks each. Recall@5:

| Condition | Tool says nothing about language | Tool says *"The catalogue is written in English"* |
|---|---|---|
| published | 0.86 (Swedish 0.40) | 0.86 (Swedish 0.73) |
| ai | 0.80 (Swedish 0.27) | 0.87 (Swedish **0.93**) |
| pagetext | 0.89 (Swedish 0.40) | **0.92** (Swedish **0.93**) |

Per-run recall@5 with the hint: published 0.83–0.88, ai 0.85–0.91, pagetext **0.91–0.93**. The
`ai` range overlaps `published`; `pagetext` does not.

The mechanism, from the queries themselves (`runs/query-*.json`):

```
Task (sv):  Sälj hemförsäkring till privatpersoner i Sverige, med tre skyddsnivåer, direkt i vår app.
No hint:    hemförsäkring privat Sverige försäljning API offert tre skyddsnivåer köp i app
Hint:       home insurance sales API for private customers Sweden, quote and purchase, three coverage levels
```

## What I could not claim

- **That `aiDescription` is useless.** It is useless *here*: 44 pages fit in one context window,
  and a frontier model reads them all. A smaller model, a much larger catalogue, or embedding
  search could change that. None of those was measured.
- **That the Swedish numbers are precise.** 5 Swedish and 3 Norwegian answerable tasks, three
  runs each, is 15 and 9 samples. The direction is large and consistent across runs; the exact
  percentages are not.
- **That the tasks are unbiased.** One author wrote all 66 after reading the catalogue, so they
  lean towards the vocabulary of the current descriptions. That bias favours `published`, which
  makes result 1 conservative and result 3's control win slightly less surprising.
- **That BM25 is how If would search.** It is the simplest lexical baseline. An embedding index
  would likely narrow the language gap on its own; that is the next experiment, not a result.

## Found in the catalogue along the way

- **One API published on two pages.** *Manage Insrt Ancillary Insurances* appears under both
  `other/` and `self-service/` with the same slug.
- **A page with no API product.** *Manage Used Car Warranty Sweden* describes Check, Register and
  Cancel operations but publishes no product. An agent sent there finds nothing to call. The
  full-context agent correctly routed warranty tasks to *Manage Insrt Warranty Insurances* instead.
- **Page text that describes another market.** The Swedish car insurance page's related-content
  block talks about Norwegian customers. The scraper drops related-page blocks for that reason:
  an index built on the raw page would learn that Sweden means Norway.
- **Product descriptions that repeat the name.** Five products, for example *Buy Car Insurance NO*,
  have a description identical to their title. The full-context agent coped; a search index gets
  nothing from them.

## The MCP server

`hittbar/server.py` exposes the snapshot to any MCP client over stdio. Two read-only tools:

| Tool | What it does |
|---|---|
| `search_api_catalogue(query, limit=5)` | BM25 over the `pagetext` view, the best search lens above. Returns product id, name, description, page and URL |
| `get_api_product(product_id)` | One product's page, category and every API in it, duplicates removed |

Every design choice comes from a measurement, not from taste:

- **The search tool's description says *"The catalogue is written in English."*** and tells the
  agent to write the query in English and name the country. That is result 3 turned into a
  default. A test fails if the sentence is removed.
- **It indexes the page text, not a generated `aiDescription`.** That is result 3's control.
- **Both tools return typed, schema-described output**, and an unknown `product_id` is a tool
  error that tells the agent to search instead, not an empty answer.

The tests (`tests/test_server.py`) go through the MCP protocol, in-process and as a real stdio
subprocess, and replay the README's own example: Opus's English query for task t47 ranks
`buy-home-insurance-se` first; its Swedish query does not reach the top 5.

Connect it to Claude Code:

```bash
claude mcp add hittbar -e PYTHONPATH=/path/to/hittbar -- /path/to/hittbar/.venv/bin/python -m hittbar.server
```

or to any client that takes a stdio command, from the repo root: `.venv/bin/python -m hittbar.server`.

**Not built, deliberately:** access control. The public catalogue needs none, and a real version
in front of If's partner specs would sit behind the portal's existing OAuth (client credentials or
auth code with PKCE) rather than invent its own. Also not built: an embedding index, which is the
next experiment above, not a result.

## Cost

| Step | Calls | Cost |
|---|---|---|
| Full-context eval, 3 conditions × 3 runs | 594 | $9.57 |
| Agent-written queries, 2 variants × 3 runs | 348 | $0.88 |
| BM25 search, all conditions | 0 | $0 |

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest              # 23 tests, no key, no network
.venv/bin/python -m hittbar.search      # free, deterministic
.venv/bin/python -m hittbar.server      # the MCP server, stdio

export ANTHROPIC_API_KEY=...
.venv/bin/python -m hittbar.evaluate --runs 3   # ~$10
.venv/bin/python -m hittbar.query --runs 3      # ~$1
.venv/bin/python -m hittbar.scrape              # refresh the snapshot
.venv/bin/python -m hittbar.describe            # regenerate the aiDescription drafts
```

The model is `claude-opus-5` by default; set `HITTBAR_MODEL` to change it.

```
hittbar/scrape.py      public portal -> data/catalog.json
hittbar/catalog.py     the three views, byte-stable so the catalogue prefix caches
hittbar/describe.py    aiDescription drafts, grounded in each page's own text
hittbar/agent.py       pick one product or "none", schema-constrained
hittbar/evaluate.py    full-context eval, deterministic scoring, cost and latency
hittbar/search.py      BM25 lens, no model
hittbar/query.py       agent-written queries through the same index
hittbar/server.py      MCP server: search + product lookup, read-only
data/tasks.jsonl       66 tasks, frozen before generation
runs/                  every run behind every number above
```

MIT.
