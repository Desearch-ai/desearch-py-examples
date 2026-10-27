# Web Search Demo

Made by Desearch | https://desearch.ai

A Vercel Python live demo for [web-search-api-quickstart](../web-search-api-quickstart/), following the `ig-engagement-rate-api` and `page-to-markdown-api` layout. Each uncached search makes exactly one GET to `https://api.desearch.ai/web?query=<q>&start=<0|20>` with a server-only `Authorization` header. No SDK, retries or redirects. Only `title`, `link` and `snippet` are returned for each result.

Run locally from this directory:

```sh
python -m pip install -r requirements.txt
DEMO_STATE=memory DEMO_LIVE=0 python app.py
```

Open http://127.0.0.1:8000. The page loads the labelled saved `bittensor subnet` sample without spending credits. To enable local searches, export `DESEARCH_API_KEY` in the server environment and run `DEMO_STATE=memory DEMO_LIVE=1 python app.py`. The app never reads keys from files, exposes them in client code or logs requests. Use `python3` if that is your Python executable.

`GET /api/search?q=bittensor%20subnet&page=1` accepts a stripped query of 2 to 200 characters and page `1` or `2` (default `1`). Pages use a fixed size of 20 results. Page 2 requests only `start=20`; it does not fetch both pages. Invalid input returns 400 before accessing shared state or consuming limits. Results live in a `results` list, alongside `query`, `page`, `cached`, `sample`, `status`, `limits` and `cost_usd_this_request`.

Queries are lowercased and whitespace-collapsed for cache keys, combined with page. Redis cache entries expire after 600 seconds. Cache hits cost $0 and bypass rate limits and the daily cap. Valid uncached requests return 429 when limited. Missing key, disabled live mode, exhausted daily cap, upstream failure or unavailable Redis returns paused 503 with the clearly labelled sample included. The page clears results on every error; the sample button can display the saved example explicitly.

Cost comes only from the upstream `X-Desearch-Cost-Usd` header. Every API response exposes this request's cost through `X-Desearch-Cost-Usd` and `cost_usd_this_request`. Invalid, denied and cache-hit requests cost $0.

Before each uncached paid call, the cap reserves the worst-case amount: `DEMO_RESERVE_COST_USD` (default $0.005), or the fallback cost if that is higher. Redis checks the budget and reserves spend atomically through one Lua EVAL in a REST pipeline call. A refused reservation returns paused 503 with the sample, `sample_url`, `Cache-Control: no-store` and cost $0, without calling upstream. Spend uses UTC dates and expires after 48 hours.

After the call, a valid cost header reconciles the reservation to the actual cost, including zero. This refunds any difference and never makes spend negative. A missing or invalid cost header on an HTTP response keeps the full reservation counted, while the reported request cost uses `DEMO_FALLBACK_COST_USD` (default $0.001). Connection failures with no response release the reservation and report $0. If settlement fails after a successful paid call, the result is still returned and the full reservation stays counted. The only remaining source of overshoot is a call whose header cost exceeds its reservation: settlement adds that call's overrun and logs only the reservation and actual cost numbers. Concurrent overruns can each add their own difference. There are no automatic retries.

Server environment variables:

| Variable | Default / purpose |
|---|---|
| `DESEARCH_API_KEY` | Required for live searches; server-only secret |
| `UPSTASH_REDIS_REST_URL` | Shared Redis REST URL; alias `KV_REST_API_URL` |
| `UPSTASH_REDIS_REST_TOKEN` | Shared Redis REST token; alias `KV_REST_API_TOKEN` |
| `DEMO_LIVE` | `1`; set `0` to pause uncached live searches |
| `DEMO_STATE` | Redis by default; `memory` for local development only |
| `DEMO_PER_IP_10MIN` | `5` paid searches per network per 10 minutes |
| `DEMO_PER_IP_DAY` | `15` paid searches per network per day |
| `DEMO_GLOBAL_10MIN` | `30` paid searches globally per 10 minutes |
| `DEMO_DAILY_CAP_USD` | `1.0` shared spend per UTC day |
| `DEMO_RESERVE_COST_USD` | `0.005` reserved before each paid call, at least the fallback |
| `DEMO_FALLBACK_COST_USD` | `0.001` per upstream response without a valid cost header |

Redis is required unless local memory mode is explicitly selected. `VERCEL` or `VERCEL_ENV` refuses memory mode. Redis configuration or admission failures pause the demo instead of falling back to memory. Settlement failures preserve successful paid results and log only the exception type. See [DEPLOY.md](DEPLOY.md) for window semantics and Vercel setup.

Runtime uses the Python standard library; requirements includes pytest for verification. Offline tests mock HTTP and block real network requests. From the repository root:

```sh
python -m pytest -q web-search-demo/tests
```

Our function logs no queries and suppresses request logging. Vercel's own platform request log may still record the request path including the query string for GET requests.
