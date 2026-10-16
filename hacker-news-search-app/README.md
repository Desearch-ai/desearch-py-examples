# Hacker News Search App

Made by Desearch, https://desearch.ai

Search Hacker News discussions on any topic from code or a small web page. The app calls the Desearch API endpoint `POST /desearch/ai/search` with only the `hackernews` tool, keeps only `news.ycombinator.com/item?id=` links, removes duplicate items and shows the title, link, snippet and highlights. Export to JSON or CSV. Standard library only.

## Try the endpoint first
```bash
curl -s https://api.desearch.ai/desearch/ai/search \
  -H "Authorization: $DESEARCH_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt": "rust async runtime", "tools": ["hackernews"], "streaming": false, "result_type": "ONLY_LINKS", "count": 10}'
```
The response is `{"search": [{"title", "link", "snippet", "highlights": [...]}, ...], "cost_usd", "usage_count", ...}`. The cost is also in the `X-Desearch-Cost-Usd` response header.

## Run it
```bash
python3 -m pip install -r requirements.txt     # only pytest, for the tests
export DESEARCH_API_KEY_FILE=/path/to/key       # or DESEARCH_API_KEY=your_key, or --key-file
python3 app.py --cli "rust async runtime" --count 10 --csv out.csv --json out.json
python3 app.py --port 8000                      # HTML page at http://127.0.0.1:8000/
curl -s "http://127.0.0.1:8000/search?q=sqlite+in+production"
curl -s "http://127.0.0.1:8000/search.csv?q=sqlite+in+production"
```
- `q`: 1 to 300 characters. For alternatives, group terms in parentheses: `(sqlite OR duckdb) production`. Unbalanced parentheses are rejected.
- `count`: 10, 20 or 30 results per call (default 10).
- `date`: optional, `PAST_WEEK`, `PAST_MONTH` or `PAST_YEAR` (see Known issues).
- A bad request gets HTTP 400 and makes no API call. The same request within 10 minutes is served from memory at no cost.
- Add `--log-dir runs/today` to save each API call (key redacted).

## Output
```json
{"q": "sqlite in production", "count": 10, "date": "", "returned": 10, "kept": 10, "non_item_links": 0,
 "duplicates": 0, "cost_usd": 0.004, "latency_s": 6.24, "cached": false,
 "results": [{"rank": 1, "item_id": "39835496", "title": "How (and why) to run SQLite in production",
              "url": "https://news.ycombinator.com/item?id=39835496", "snippet": "...", "highlights": ["..."]}]}
```
Results are story pages and single comments. A comment result has a shortened comment text as its title.

## Files
- `core.py`: input checks, request body, HN item filter, dedupe, CSV/JSON export, HTML. No network.
- `app.py`: the CLI, the HTTP page and the Desearch client.
- `test_core.py`: offline tests, `python3 -m pytest -q`.
- `samples/`: a CLI JSON and CSV export and an HTML page.

## Cost
In our runs each call cost $0.0004 per result: $0.004 for `count` 10 and $0.008 for `count` 20.

## Known issues
- `date_filter` did not narrow results: `PAST_WEEK` returned items from earlier years. Treat results as a topic archive, not recent news.
- A made-up topic still returned 10 unrelated items and was billed like a normal search, so there is no "no results" signal.
- `hackernews` is accepted by the API but is not yet listed in the documented `tools` values (the docs list `web` and `twitter`).
- Each call took about 6 to 7 seconds in our tests, so the app caches results for 10 minutes.
