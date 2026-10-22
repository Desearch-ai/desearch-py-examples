# Web Search Demo

Made by Desearch | https://desearch.ai

A Vercel Python live demo for [web-search-api-quickstart](../web-search-api-quickstart/), following the `ig-engagement-rate-api` and `page-to-markdown-api` layout. Each uncached search makes exactly one GET to `https://api.desearch.ai/web?query=<q>&start=<0|10>` with a server-only `Authorization` header. No SDK, retries or redirects. Only `title`, `link` and `snippet` are returned for each result.

Run locally from this directory:

```sh
python -m pip install -r requirements.txt
DEMO_STATE=memory DEMO_LIVE=0 python app.py
```

Open http://127.0.0.1:8000. The page loads the labelled saved `bittensor subnet` sample without spending credits. To enable local searches, export `DESEARCH_API_KEY` in the server environment and run `DEMO_STATE=memory DEMO_LIVE=1 python app.py`. The app never reads keys from files, exposes them in client code or logs requests. Use `python3` if that is your Python executable.

`GET /api/search?q=bittensor%20subnet&page=1` accepts a stripped query of 2 to 200 characters and page `1` or `2` (default `1`). Page 2 requests only `start=10`; it does not fetch both pages. Invalid input returns 400 before accessing shared state or consuming limits. Results live in a `results` list, alongside `query`, `page`, `cached`, `sample`, `status`, `limits` and `cost_usd_this_request`.

Queries are lowercased and whitespace-collapsed for cache keys, combined with page. Redis cache entries expire after 600 seconds. Cache hits cost $0 and bypass rate limits and the daily cap. Valid uncached requests return 429 when limited. Missing key, disabled live mode, exhausted daily cap, upstream failure or unavailable Redis returns paused 503 with the clearly labelled sample included. The page clears results on every error; the sample button can display the saved example explicitly.

Cost comes only from the upstream `X-Desearch-Cost-Usd` header. Missing, negative, nonfinite or malformed values use `DEMO_FALLBACK_COST_USD` (default $0.001), including failed upstream calls. Every API response exposes this request's cost through `X-Desearch-Cost-Usd` and `cost_usd_this_request`. Invalid, denied and cache-hit requests cost $0. Actual header cost is added to shared daily spend before returning live results. The cap uses the reference demos' read/check/add approach, so concurrent requests or a call that crosses the remaining budget can exceed it.

Server environment variables:

| Variable | Default / purpose |
|---|---|
| `DESEARCH_API_KEY` | Required for live searches; server-only secret |
| `UPSTASH_REDIS_REST_URL` | Shared Redis REST URL; alias `KV_REST_API_URL` |
| `UPSTASH_REDIS_REST_TOKEN` | Shared Redis REST token; alias `KV_REST_API_TOKEN` |
| `DEMO_LIVE` | `1`; set `0` to pause uncached live searches |
| `DEMO_STATE` | Redis by default; `memory` for local development only |
| `DEMO_PER_IP_10MIN` | `5` paid searches per visitor per 10 minutes |
| `DEMO_PER_IP_DAY` | `15` paid searches per visitor per day |
| `DEMO_GLOBAL_10MIN` | `30` paid searches globally per 10 minutes |
| `DEMO_DAILY_CAP_USD` | `1.0` shared spend per UTC day |
| `DEMO_FALLBACK_COST_USD` | `0.001` per upstream response without a valid cost header |

Redis is required unless local memory mode is explicitly selected. `VERCEL` or `VERCEL_ENV` refuses memory mode. Redis configuration or operation failures pause the demo instead of falling back to memory. See [DEPLOY.md](DEPLOY.md) for window semantics and Vercel setup.

Runtime uses the Python standard library; requirements includes pytest for verification. Offline tests mock HTTP and block real network requests. From the repository root:

```sh
python -m pytest -q web-search-demo/tests
```
