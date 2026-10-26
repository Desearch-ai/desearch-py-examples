# AI Fact Checker

Made by Desearch | https://desearch.ai

Paste one claim and get related sources, each with a link, and a short summary that keeps only sentences tied to a returned source. It helps you find sources; it does not decide what is true. Optional X search is off by default.

It is a small web app (one HTML page plus one JSON endpoint) and a CLI. It runs locally with one command and deploys to Vercel as a static page plus one Python function. Standard library only, plain HTTP (no SDK).

## Desearch endpoints

- `POST /desearch/ai/search` with `tools: ["web"]`, `result_type: "LINKS_WITH_FINAL_SUMMARY"`, `streaming: false`, `count: 10`: web sources plus a cited summary.
- Optional: a second `POST /desearch/ai/search` with `tools: ["wikipedia"]` when "also search Wikipedia" is ticked (`wiki=1`). It is a separate call because asking for `["web", "wikipedia"]` in one call returned only Wikipedia links in our runs.
- Optional: `GET /twitter` with `query` (the claim's first 4 key terms), `sort: "Top"`, `count: 10`. The server calls it only when `DEMO_X_ENABLED=1` or `DEMO_X_ENABLED=true`; the CLI calls it only with `--x`.

## Try the endpoint first

```bash
curl -s https://api.desearch.ai/desearch/ai/search \
  -H "Authorization: $DESEARCH_API_KEY" -H "Content-Type: application/json" \
  -d '{"prompt": "Octopuses have three hearts and blue blood", "tools": ["web"], "streaming": false, "result_type": "LINKS_WITH_FINAL_SUMMARY", "count": 10}'
```

The response includes `search` entries with `title`, `link`, `snippet`, and `highlights`, plus a `completion` with Markdown citations and `cost_usd`. Cost is also available in the `X-Desearch-Cost-Usd` response header.

## Run it locally

```bash
export DESEARCH_API_KEY_FILE=/path/to/key         # or DESEARCH_API_KEY, or --key-file
python3 app.py                                    # web app at http://127.0.0.1:8000
curl -s "http://127.0.0.1:8000/api/check?claim=Honey+never+spoils+if+stored+sealed"
python3 app.py --cli "Humans only use 10 percent of their brain" --wiki --json out.json --html out.html
python3 app.py --cli "Honey never spoils if stored sealed" --x
python3 -m pytest -q                              # offline, if pytest is already installed
python3 -m unittest                              # standard library fallback, no installation needed
```

- `claim`: 8 to 200 characters with at least two words that carry meaning. Anything else gets HTTP 400 and makes no API call.
- `wiki=1`: also search Wikipedia (one more call). Wikipedia file, talk and portal pages and non-English pages are dropped.
- X is off by default. The server accepts only `1` or `true` (case-insensitive) for `DEMO_X_ENABLED`. The CLI uses `--x` independently of that server setting. An API query parameter cannot enable X.
- Add `--log-dir runs/today` to save each API call with the key redacted.

## What you get

```json
{"claim": "...", "no_strong_sources": false, "strong": 10,
 "summary": {"lines": [{"text": "...", "cites": ["https://..."]}], "hidden": 1, "verdict_hidden": 1, "cited_urls": ["https://..."]},
 "sources": [{"rank": 1, "title": "...", "url": "https://...", "domain": "...", "type": "web", "snippet": "...", "quote": "...", "term_share": 1.0}],
 "stats": {"returned": 10, "kept": 10, "duplicates": 0, "skipped": {}},
 "x_enabled": false, "cost_usd": 0.004, "latency_s": 10.0, "calls": 1, "cached": false}
```

- **Sources** are deduped and shown neutrally: rank, title link, domain and snippet. No per-source stance or verdict is assigned.
- **Summary** is the `completion` split into sentences. Judgment words and verdict phrasing are filtered with case-insensitive word boundaries, and dropped sentences are counted separately in `summary.verdict_hidden`. Remaining sentences are shown only if every link they cite is a returned source; uncited or mis-cited sentences are counted in `summary.hidden`. This checks citation destinations, not whether a source establishes the sentence's accuracy. Repeated citations and punctuation artefacts are cleaned up. The search request includes a `system_message` asking for a neutral summary of what sources say, with citations and without a verdict.
- **Source count** says "N sources returned." With fewer than two displayed sources it also says "Few sources returned. Read them before you share anything." Legacy `term_share`, `strong` and `no_strong_sources` fields remain for JSON compatibility and are unused by the displays.
- **Text cleanup** decodes HTML entities, strips tags (including tags encoded as entities) and collapses whitespace in titles, snippets, highlights, summaries and posts. Display text is escaped, and source links accept only HTTP or HTTPS URLs.
- **X posts**, when enabled, must contain at least two distinct meaningful claim terms, or all terms if the claim has fewer than two. Stopwords are excluded and whole terms are matched. A small built-in profanity and slur filter uses case-insensitive word boundaries and catches simple obfuscations. Posts with account mentions are also dropped. Authors are shown as "a user". Returned display text has HTML removed.
- When X is off, `/twitter` is never called, post fields are omitted, and the page hides the X section. When on, the result adds `posts`, `x_query`, `x_returned` and `x_dropped`. An empty or unavailable X result does not block web sources.

## Demo controls (for the hosted version)

The key is read on the server only (`DESEARCH_API_KEY`), never sent to the browser, and never written to a response or log line. In front of the paid calls:

- input checks (no call for blank or junk input);
- a per-IP limit (5 checks per 10 minutes, 15 per day) and a global limit (30 per 10 minutes);
- a daily spend cap from the `X-Desearch-Cost-Usd` header (`DEMO_DAILY_CAP_USD`, default $1.00, UTC day); unknown 2xx/4xx cost counts `DEMO_FALLBACK_COST_USD` (default $0.005), except 401/402/403 and 429;
- a 6-hour cache: `Cache-Control: public, max-age=0, s-maxage=21600` on result responses, plus an in-memory cache keyed by the normalized claim and the Wikipedia and X settings;
- a kill switch: `DEMO_LIVE=0` turns off live calls and points to `/sample.json`.

The per-IP limit, the global limit and the daily cap are stored in Upstash Redis when `KV_REST_API_URL` and `KV_REST_API_TOKEN` are set (or `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`), so they hold across Vercel instances. On Vercel, if that store is not configured, `/api/check` returns 503 with the sample pointer and makes no paid call. A local run with no store falls back to in-memory counters and logs a warning once. If the store fails before paid calls, the endpoint returns that same 503. The in-memory result cache is still per warm instance; the CDN cache and the key's balance are the outer limits. See `DEPLOY.md`.

Before paid calls, the checker atomically reserves the worst-case cost in Redis with one Lua `EVAL` through `POST /multi-exec`. It reserves `max(DEMO_RESERVE_COST_USD, DEMO_FALLBACK_COST_USD)` per job: one web call, plus one each for Wikipedia and enabled X. A refused reservation returns 503 with `"sample": "/sample.json"` and `Cache-Control: no-store`, with no paid call. Afterwards it reconciles the reservation to actual cost, never below zero, on the UTC day reserved. Unknown 2xx/4xx cost counts the fallback, except 401/402/403 and 429 which count zero; unknown 5xx cost and connection failures count zero. The only remaining overshoot is a check whose actual cost exceeds its reservation. If settlement fails after a paid result, the result is returned and the full reservation stays counted.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEMO_RESERVE_COST_USD` | `0.01` | Worst-case reservation per paid call, at least `DEMO_FALLBACK_COST_USD`. |

## Files

- `factcheck/core.py`: input checks, request bodies, source and text cleanup, citation check, X post filters, limiter, cap, cache and report rendering. No network.
- `factcheck/limits.py`: shared Upstash Redis counters (stdlib urllib). Local runs fall back to the in-memory limiter and cap when no store is configured. On Vercel a missing store fails closed.
- `factcheck/client.py`: plain HTTP Desearch client (key redaction guard).
- `factcheck/service.py`: the `/api/check` endpoint logic shared by local and Vercel.
- `api/check.py`: Vercel Python function. `public/index.html`: the page. `vercel.json`: function settings.
- `app.py`: local server (page + `/api/check`) and CLI.
- `test_core.py`: offline tests compatible with pytest and unittest. `samples/`: saved data adapted offline to the current format, plus an HTML page.

## Cost and timing

A check with X off costs **$0.004**, or **$0.008 with Wikipedia**. Enabling X adds $0.0015, for $0.0055 or $0.0095 with Wikipedia. Cached checks cost nothing. Keeping X off skips the approximately 30 second X call.

Three live runs on October 21, 2026 measured `ai/search` at 9.4 to 10.1 seconds. Each X call took approximately 30.2 seconds and returned 0 posts. A customer saw 11 seconds and 26 seconds with X on. The page says **about 10 to 15 seconds** for a normal check; allow **up to 40 seconds** with X enabled. Wikipedia adds a parallel search call, so timing can vary.

## Search limitations

- `tools: ["web", "wikipedia"]` in one call returned 10 Wikipedia links and no web links (twice), so the app makes one call per tool.
- A made-up claim can still return loosely related pages. A source count does not establish source quality or the claim's accuracy; read the sources.
- X searches can be slow or return unrelated posts. X is off by default; the relevance and profanity filters apply when enabled.
- `wikipedia` is accepted by the API but is not listed in the documented `tools` values used for the original example.
