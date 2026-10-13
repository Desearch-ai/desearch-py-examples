# Arxiv Chatter Digest

Made by Desearch · https://desearch.ai

A small Python CLI: give it a research topic, get back `papers.csv` and a Markdown digest of recent arXiv papers Desearch returned and public X posts that named them.

## What it does

1. **Find papers.** Calls the Desearch hosted MCP tool `ai-search` with `tools: ["arxiv"]` only and `result_type: "ONLY_LINKS"`, a few times with different wordings of the topic (default 8 calls). The arXiv source is used on its own, never mixed with web or wikipedia.
2. **Check papers.** Turns every arXiv link form (`/abs/`, `/html/`, `ar5iv`) into one arXiv id, drops listing pages, and looks the ids up in the public arXiv API (free, not a Desearch call) for the real title, authors and first-version date. Only papers whose date falls inside `--days` are kept (newest first, up to `--max-papers`).
3. **Read the abs page.** Desearch `extract` on `https://arxiv.org/abs/<id>` with `format: "text"`, `js: false`, one retry when the body is empty. The abstract goes into the digest.
4. **Look for X posts.** Desearch `x-search` per paper with a parenthesised OR group, `("<arxiv id>" OR "<short title>")`, `count` 20, `start_date` = the paper's date.
5. **Write output.** `papers.csv` (rank, arxiv id, title, abs URL, date, title match score, X post count, sample post links, extract status, fetched_at) and `digest.md` (top 10, at least 5 when there are that many papers). Post links use the handle-free form `https://x.com/i/status/<id>` and @handles in post text are replaced with `@user`.

Tip: check paper and post dates. The script reads each paper's date from arXiv and each post's date from X, filters on them in code, and shows them in the CSV and digest.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
echo "<your key from console.desearch.ai>" > ~/.desearch_key && chmod 600 ~/.desearch_key
export DESEARCH_API_KEY_FILE=~/.desearch_key     # or DESEARCH_API_KEY; the file wins when both are set
```

## Run

```bash
python arxivchatter.py "graph neural networks"
# options: --days 30  --max-papers 15  --posts 20  --prompts 8  --top 10  --include-older  --out runs
python arxivchatter.py --render runs/<run folder>    # rebuild papers.csv and digest.md from snapshot.json, no API calls
pytest -q test_arxivchatter.py                       # offline tests
```

Each run writes `runs/<timestamp>-<topic>/`: `papers.csv`, `digest.md`, `snapshot.json`, `arxiv-api.xml`, `calls.jsonl` (one line per Desearch call with args, latency, items and cost) and `raw/` (each tool result). The key is sent only in the Authorization header and the client refuses to write a file that contains it.

## Cost

`ai-search` returns `cost_usd` in its result. `x-search` and `extract` over MCP do not, so `calls.jsonl` adds `cost_calculated_usd` for X from the public pricing page (desearch.ai/pricing, checked 2026-10-12): AI Search $0.40 per 1,000 items, Extract $0.50 per 1,000 pages, X Search $0.15 per 1,000 posts, billed by posts returned with a 10-post minimum and never above `count`.

Measured on the sample run (2026-10-12 09:38 Tbilisi, 8 arxiv calls, 15 papers): `ai-search` $0.004 per call (10 items), $0.032 reported. Extract and X (calculated): 15 pages x $0.0005 = $0.0075, 15 X searches = $0.0225. About $0.062 for the run (calculated).

See `sample-output.md` for the run, `samples/` for its `papers.csv` and `digest.md`.

## Known issues

- An X search that finds nothing returns after about 30 s; searches with posts came back in 4-9 s. A 15-paper run takes about 2 minutes with 4 calls in parallel.
- The public arXiv API can answer HTTP 429 when called often; the script waits and retries (5, 20, 60 s).
