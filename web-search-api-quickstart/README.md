# Web Search API Quickstart

Made by Desearch, https://desearch.ai

Add web search to your own app in a few minutes. This is a tiny JSON service with one route, `GET /search?q=`, built on the Desearch endpoint `GET /web`. It returns clean `{title, url, snippet, domain}` results, removes duplicate URLs and caches each query for 10 minutes. Standard library only: no framework to install.

## Try the endpoint first
```bash
curl -s "https://api.desearch.ai/web?query=bittensor+subnet&start=0" \
  -H "Authorization: $DESEARCH_API_KEY"
```
The response is `{"data": [{"title", "link", "snippet"}, ...], "cost_usd", "usage_count", ...}`. The cost of the call is also in the `X-Desearch-Cost-Usd` response header.

Python (standard library):
```python
import json, os, urllib.parse, urllib.request
url = "https://api.desearch.ai/web?" + urllib.parse.urlencode({"query": "bittensor subnet", "start": 0})
req = urllib.request.Request(url, headers={"Authorization": os.environ["DESEARCH_API_KEY"]})
with urllib.request.urlopen(req, timeout=60) as r:
    print(r.headers.get("X-Desearch-Cost-Usd"))
    for item in json.load(r)["data"]:
        print(item["title"], item["link"])
```

JavaScript (Node 18+):
```js
const url = "https://api.desearch.ai/web?" + new URLSearchParams({ query: "bittensor subnet", start: "0" });
const r = await fetch(url, { headers: { Authorization: process.env.DESEARCH_API_KEY } });
console.log(r.headers.get("x-desearch-cost-usd"));
for (const item of (await r.json()).data) console.log(item.title, item.link);
```

## Run the service
```bash
python3 -m pip install -r requirements.txt   # only pytest, for the tests
export DESEARCH_API_KEY=your_key             # or DESEARCH_API_KEY_FILE=/path/to/key, or --key-file
python3 app.py --port 8000
curl -s "http://127.0.0.1:8000/search?q=bittensor+subnet&pages=2"
```
Open `http://127.0.0.1:8000/` for a small HTML search page. Or use it as a CLI:
```bash
python3 app.py --cli "bittensor subnet" --pages 2
```
Add `--log-dir runs/today` to save each API call (with the key redacted) for debugging.

## What `/search` returns
```json
{"query": "bittensor subnet", "pages": 2, "count": 37, "new_per_page": [19, 18], "repeats_dropped": 2,
 "cost_usd": 0.002, "latency_s": 8.87, "cached": false, "calls": 2,
 "results": [{"title": "...", "url": "https://...", "snippet": "...", "domain": "...", "rank": 1}]}
```
- `q` is required, 1 to 300 characters. `pages` is 1 to 3 (default 1). A bad request gets HTTP 400 and makes no API call.
- Page 1 is `start=0`, page 2 is `start=20`, page 3 is `start=40` (see Known issues for why the step is 20).
- Duplicate URLs (same host without `www`, same path) are dropped and counted in `repeats_dropped`.
- The same query (case and spacing ignored) within 10 minutes is served from memory: `"cached": true`, `"calls": 0`, no cost.

## Files
- `core.py`: query check, paging, result normalizing, dedupe, cache and HTML. No network.
- `app.py`: the HTTP service, the CLI and the Desearch client.
- `test_core.py`: offline tests, `python3 -m pytest -q`.
- `samples/`: one `/search` response and the matching HTML page.

## Cost
Each `GET /web` call cost $0.001 in our runs, whatever the number of results. One page is one call, so `pages=2` is $0.002 and a cache hit is $0.

## Known issues
- `start=10` is not a clean page 2: a page holds up to 20 results, so `start=10` mostly repeats `start=0` (15 and 18 of about 20 URLs repeated in our tests) and is still billed. This service steps by 20. Even then a few URLs can repeat (0 to 3 in our tests), so results are deduped.
- A blank query is not rejected by the API and is billed. This service checks the query before calling.
- A query with no real matches still returns about 20 unrelated results, not an empty list.
- There is no `count` parameter: pages had 18 to 20 results in our runs.
