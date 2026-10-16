# SERP API Rank Checker

Made by Desearch | https://desearch.ai

A small Python CLI that takes a list of keywords and one domain, calls the Desearch API web search endpoint (`GET /web`) for each keyword, dedupes the results by URL and tells you the best rank your domain got in the search results Desearch returned. A second run can diff ranks against the first. Output is JSON plus CSV.

It does not claim to match the live ranking of any particular search engine. It reports the search results Desearch returned at the time of the run.

## Setup
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # pytest only, the CLI itself uses the standard library
```
Get an API key at console.desearch.ai. Provide it by name, never in code:
- `DESEARCH_API_KEY`, or
- `DESEARCH_API_KEY_FILE` (path to a file holding the key).

## Run
```bash
python rank_check.py --keywords samples/keywords.txt --domain desearch.ai
# a later run, diffed against the first one
python rank_check.py --keywords samples/keywords.txt --domain desearch.ai --diff runs/<first-run>/summary.json
```
Options: `--pages` (pages per keyword, default 2), `--step` (offset between pages, default 20), `--out` (default `runs/`).

Each run writes `runs/<timestamp>/`: `results.csv` (keyword, rank, title, url, domain, page_start), `results.json`, `summary.json` (best rank per keyword, per-page new/duplicate counts, call count, cost total from the `X-Desearch-Cost-Usd` header, optional diff), `calls.jsonl` and `raw/` (every response, key redacted).

## Why `--step 20`
In my runs on 2026-10-16 a `GET /web` page held up to 20 results. With `start=10` the second page mostly repeated the first (0 to 6 new URLs out of about 20). With `start=20` most results were new. So the default walks 0, 20. Duplicates are removed either way, and `summary.json` shows how many new URLs each page added.

## Cost (measured 2026-10-16)
Each `GET /web` call carried `X-Desearch-Cost-Usd: 0.001`. Ten keywords with two pages is 20 calls, $0.02 per run. Median latency across 40 calls was 1.92 s (min 1.06 s, max 8.25 s).

## No-code equivalent
The Desearch MCP server exposes the same search as the `web-search` tool (`{"query": "..."}`), so you can ask an agent in your editor for the results of one keyword without this script.

## Tests
```bash
python -m pytest -q
```
Tests cover `core.py` only and never touch the network.

## Known issues
- A blank query returns an empty list with status 200 instead of an error, so the CLI skips blank lines in the keyword file before calling.
- A query with no sensible matches still returns about 20 loosely related results, so "not in top N" is the useful signal, not an empty list.

See `sample-output.md` for a real run.
