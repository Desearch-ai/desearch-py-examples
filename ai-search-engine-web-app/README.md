# AI Search Engine Web App

Made by Desearch | https://desearch.ai

A small, self-hosted search box for your product, docs site or agent. Type a search and get ranked web pages, each with its published date (when the page has one) and the passage that best matches your search. An optional **Answer** button adds a short answer that is shown only next to the links it cites.

It is one HTML page plus two JSON endpoints (`/api/search`, `/api/answer`) and a CLI. It runs locally with one command and deploys to Vercel as a static page plus two Python functions. Standard library only, plain HTTP.

## Desearch endpoints
- `POST /search` (the Search API): `query`, `mode` (`fast` or `balanced`), `count` (10, 15 or 20), `start_date` / `end_date` (YYYY-MM-DD, filters on the page's published date), `highlights: true`. Each result has `url`, `title`, `published_date` (can be `null`) and `highlights` (the best-matching passage). The cost is in the JSON body as `cost_usd`.
- `POST /desearch/ai/search` with `tools: ["web"]`, `streaming: false`, `result_type: "LINKS_WITH_FINAL_SUMMARY"`, `count: 10`: links plus a `completion` that cites them as `[n](url)`. Used only by the Answer button.

## Try the endpoint first
```bash
curl -s https://api.desearch.ai/search \
  -H "Authorization: $DESEARCH_API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "open source LLM released this week", "mode": "fast", "count": 10, "start_date": "2026-10-12", "end_date": "2026-10-18"}'
```
The response is `{"results": [{"url", "title", "published_date", "highlights": ["..."]}], "cost_usd": 0.005, "usage_count": 10, "service": "Search API", "currency": "USD"}`.

If you call it from Python's `urllib`, send a `User-Agent` header. Without one the request is blocked with HTTP 403 (`error code: 1010`) before it reaches the API. `searchapp/client.py` sets one.

## Run it locally
```bash
python3 -m pip install -r requirements.txt       # only pytest, for the tests
export DESEARCH_API_KEY_FILE=/path/to/key         # or DESEARCH_API_KEY=your_key, or --key-file
python3 app.py                                    # web app at http://127.0.0.1:8000
curl -s "http://127.0.0.1:8000/api/search?q=python+3.14+free+threading&range=year"
curl -s "http://127.0.0.1:8000/api/answer?q=python+3.14+free+threading"
python3 app.py --cli "python 3.14 free threading performance" --range year --answer --json out.json
python3 -m pytest -q                              # offline tests, no key needed
```

### `/api/search` parameters
| Param | Values | Default |
|---|---|---|
| `q` | 2 to 300 characters, at least one letter or number | required |
| `mode` | `fast`, `balanced` | `fast` |
| `count` | `10`, `15`, `20` | `10` |
| `range` | `any`, `day`, `week`, `month`, `year` (counted back from today, UTC) | `any` |
| `from`, `to` | `YYYY-MM-DD` (instead of `range`) | none |

Anything else gets HTTP 400 and makes no API call. `/api/answer` takes `q` only.

## What you get
```json
{"query": "python 3.14 free threading performance", "mode": "fast", "start_date": "2025-10-19", "end_date": null,
 "results": [{"rank": 1, "title": "...", "url": "https://...", "domain": "...", "published_date": "2025-10-25",
              "passage": "Early benchmarks show ...", "in_window": true}],
 "stats": {"returned": 10, "shown": 10, "duplicates": 0, "no_date": 0, "outside_window": 0},
 "cost_usd": 0.005, "cached": false}
```
- **Results** are shown in the order the API returned them. The page also has a "newest first" order.
- A result without `published_date` is labelled **date not given**. A dated result outside your window would be labelled **outside date window** (none were in our runs).
- **Passages** are the first `highlights` entry, whitespace collapsed and cut to about 420 characters. The text is otherwise shown as returned.

The Answer endpoint returns `links` (the answer call's own links), `summary.lines` (sentences whose citations all point at those links), `summary.hidden` (sentences dropped), `no_strong_sources` (fewer than two links hold most of the search words) and `declined` with `declined_text` (the answer service sent its "Closest on-topic source reviewed" reply instead of a summary). The page also says how many answer links are in the search results.

## Demo safety (for the hosted version)
The key is read on the server only (`DESEARCH_API_KEY`), never sent to the browser, and never written to a response or log line. In front of the paid calls:
- input checks (no call for blank or junk input);
- a per-IP limit (10 requests per 10 minutes, 40 per day) and a global limit (60 per 10 minutes);
- a daily spend cap (`DEMO_DAILY_CAP_USD`, default $1.00, UTC day) summed from each response's cost (`cost_usd` in the body for `POST /search`, which sends no cost header);
- a 6-hour cache: `Cache-Control: public, max-age=0, s-maxage=21600` on results, so a CDN serves repeats, plus an in-memory cache keyed by the normalized query and options;
- a kill switch: `DEMO_LIVE=0` turns off live calls and the page shows the saved run in `public/sample.json`.
On a serverless host the limit, cap and in-memory cache are per warm instance, so they are best effort; the CDN cache and the key's balance are the outer limits. See `DEPLOY.md`.

## Files
- `searchapp/core.py`: input checks, request bodies, result cleanup, citation check, limiter, cap, cache. No network.
- `searchapp/client.py`: plain-HTTP Desearch client (User-Agent, key redaction guard, cost from header or body).
- `searchapp/service.py`: the `/api/search` and `/api/answer` logic shared by local and Vercel.
- `api/search.py`, `api/answer.py`: Vercel Python functions. `public/index.html`: the page. `vercel.json`: function settings.
- `app.py`: local server and CLI. `test_core.py`: offline tests. `samples/`: a saved run.

## Cost
In our runs (2026-10-19): **$0.005 per search** (`POST /search`, 10 results, either mode) and **$0.004 per answer** (`POST /desearch/ai/search`, web, count 10). Cached requests cost nothing. With the default $1.00 daily cap that is up to 200 uncached searches a day.

## Known issues
- `fast` and `balanced` returned the same 10 pages in a different order for all 5 queries we tried, and repeating the same `fast` search also changed the order. So the app does not promise a stable ranking. It shows the order the API returned and offers "newest first".
- Some results have no `published_date` (1 to 2 of 10 on evergreen queries). With a date window set, every result in our runs was dated inside it.
- Passages often lack a space after punctuation (`3.14,with`). The app shows them as returned.
- A made-up search still returns 10 pages and is billed like a normal search.
- A search of only spaces returned HTTP 503 from the API (not billed). The app rejects it before calling.
- In 3 of 3 Answer calls the answer service did not write a summary. It replied that the sources did not cover the question and named one "closest" source, even when its links were on topic. The app shows that reply as "No summary for this search" with the links.
- The Python SDK (desearch-py 1.2.1) has no method for `POST /search` yet, so this app uses plain HTTP.
