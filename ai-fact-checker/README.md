# AI Fact Checker

Made by Desearch | https://desearch.ai

Paste one claim and get the sources that back it or push back on it, each with a link, a short summary that keeps only the sentences tied to a returned source, and how the topic is discussed on X. It helps you find sources; it does not decide what is true.

It is a small web app (one HTML page plus one JSON endpoint) and a CLI. It runs locally with one command and deploys to Vercel as a static page plus one Python function. Standard library only, plain HTTP (no SDK).

## Desearch endpoints
- `POST /desearch/ai/search` with `tools: ["web"]`, `result_type: "LINKS_WITH_FINAL_SUMMARY"`, `streaming: false`, `count: 10`: web sources plus a cited summary.
- `GET /twitter` with `query` (the claim's first 4 key words), `sort: "Top"`, `count: 10`: posts about the topic.
- Optional: a second `POST /desearch/ai/search` with `tools: ["wikipedia"]` when "also search Wikipedia" is ticked (`wiki=1`). It is a separate call because asking for `["web", "wikipedia"]` in one call returned only Wikipedia links in our runs.

## Try the endpoint first
```bash
curl -s https://api.desearch.ai/desearch/ai/search \
  -H "Authorization: $DESEARCH_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt": "Octopuses have three hearts and blue blood", "tools": ["web"], "streaming": false, "result_type": "LINKS_WITH_FINAL_SUMMARY", "count": 10}'
```
The response is `{"search": [{"title", "link", "snippet", "highlights"}], "completion": "... [1](https://...)", "cost_usd", ...}`. The cost is also in the `X-Desearch-Cost-Usd` response header.

## Run it locally
```bash
python3 -m pip install -r requirements-dev.txt   # only pytest, for the tests
export DESEARCH_API_KEY_FILE=/path/to/key         # or DESEARCH_API_KEY=your_key, or --key-file
python3 app.py                                    # web app at http://127.0.0.1:8000
curl -s "http://127.0.0.1:8000/api/check?claim=Honey+never+spoils+if+stored+sealed"
python3 app.py --cli "Humans only use 10 percent of their brain" --wiki --json out.json --html out.html
python3 -m pytest -q                              # offline tests, no key needed
```
- `claim`: 8 to 200 characters with at least two words that carry meaning. Anything else gets HTTP 400 and makes no API call.
- `wiki=1`: also search Wikipedia (one more call). Wikipedia file, talk and portal pages and non-English pages are dropped.
- Add `--log-dir runs/today` to save each API call with the key redacted.

## What you get
```json
{"claim": "...", "no_strong_sources": false, "strong": 10, "labels": {"contradicts": 10},
 "summary": {"lines": [{"text": "...", "cites": ["https://..."]}], "hidden": 1},
 "sources": [{"rank": 1, "label": "contradicts", "title": "...", "url": "https://...", "domain": "...", "type": "web", "snippet": "...", "term_share": 1.0}],
 "posts": [{"text": "...", "author": "a user", "url": "https://x.com/i/status/..."}], "x_query": "great wall china visible",
 "x_returned": 10, "cost_usd": 0.0055, "calls": 2, "cached": false}
```
- **Sources** come from the web search, deduped. Each gets a **cue label**: `contradicts` if its text has debunk words (myth, misconception, debunked, false, no evidence...), `supports` if it holds most of the claim's key words without them, else `unclear`. It is a keyword hint, not a verdict.
- **Summary** is the `completion` split into sentences. A sentence is shown only if every link it cites is one of the returned sources; the rest are hidden and counted.
- **No strong sources found** is shown when fewer than two sources hold at least 60% of the claim's key words. A made-up claim lands here instead of looking confirmed.
- **X posts** are shown only if they contain all the search words and do not @-mention an account. Authors are shown as "a user". Post text is quoted as returned.

## Demo safety (for the hosted version)
The key is read on the server only (`DESEARCH_API_KEY`), never sent to the browser, and never written to a response or log line. In front of the paid calls:
- input checks (no call for blank or junk input);
- a per-IP limit (5 checks per 10 minutes, 15 per day) and a global limit (30 per 10 minutes);
- a daily spend cap from the `X-Desearch-Cost-Usd` header (`DEMO_DAILY_CAP_USD`, default $1.00, UTC day); if a response carries no cost, the call counts `DEMO_FALLBACK_COST_USD` (default $0.005) so the cap still works;
- a 6-hour cache: `Cache-Control: public, max-age=0, s-maxage=21600` on result responses, so a CDN serves repeat claims, plus an in-memory cache keyed by the normalized claim;
- a kill switch: `DEMO_LIVE=0` turns off live calls and points to `/sample.json`.
The per-IP limit, the global limit and the daily cap are stored in Upstash Redis when `KV_REST_API_URL` and `KV_REST_API_TOKEN` are set (or `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`), so they hold across Vercel instances. If that store is not configured, the function falls back to in-memory counters and logs a warning once. If the store is configured but a call fails, the endpoint returns 503 with the sample pointer and makes no paid call. The in-memory result cache is still per warm instance; the CDN cache and the key's balance are the outer limits. See `DEPLOY.md`.

## Files
- `factcheck/core.py`: input checks, request bodies, source cleanup, cue labels, citation check, X post filter, in-memory limiter, cap, cache. No network.
- `factcheck/limits.py`: shared Upstash Redis counters (stdlib urllib). Falls back to the in-memory limiter and cap when no store is configured.
- `factcheck/client.py`: plain-HTTP Desearch client (key redaction guard).
- `factcheck/service.py`: the `/api/check` endpoint logic shared by local and Vercel.
- `api/check.py`: Vercel Python function. `public/index.html`: the page. `vercel.json`: function settings.
- `app.py`: local server (page + `/api/check`) and CLI.
- `test_core.py`: offline tests. `samples/`: saved runs and an HTML page.

## Cost
In our runs (2026-10-18): $0.004 per `ai/search` call and $0.0015 per `GET /twitter` call with `count` 10, so **$0.0055 per check**, $0.0095 with Wikipedia. Cached checks cost nothing.

## Known issues
- `tools: ["web", "wikipedia"]` in one call returned 10 Wikipedia links and no web links (twice), so the app makes one call per tool.
- A custom `system_message` asking for per-source labels came back as "NO STRONG SOURCES" or with an empty source list, so the app uses the default summary and labels sources itself.
- A made-up claim still returns 10 loosely related pages and is billed like a normal search; the app shows "No strong sources found".
- An X search with no matches returns `[]` after about 30 seconds and is billed $0.0015. X results for a topic can be mostly off-topic, so the app filters them by the search words.
- `wikipedia` is accepted by the API but not yet listed in the documented `tools` values (the docs list `web` and `twitter`).
