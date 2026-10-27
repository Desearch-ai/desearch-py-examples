# Web links search demo

Made by Desearch | https://desearch.ai

Type a prompt and get ranked web links with titles, domains, snippets and source dates when available. Runtime uses only the Python standard library. Requirements includes pytest for offline verification.

## Hosted demo

https://web-links-search.demos.desearch.ai (once deployed)

`GET /api/search?prompt=open+source+vector+databases&count=3` accepts a normalized prompt of 1 to 200 characters and a count from 1 to 10, default 10. Control characters are rejected. Validation happens before any state, limits or upstream access and costs $0.

Each uncached live search makes one POST to `https://api.desearch.ai/desearch/ai/search/links/web`, with a server-only raw Authorization key and body `{"prompt": "...", "tools": ["web"], "count": 10}`. The upstream requires at least ten, so the server always requests ten and slices the shaped rows to the requested count. No retries or redirects; timeout is 50 seconds. Only public result fields are returned.

## Limits and cache

Defaults: 5 searches per network per 10 minutes, 15 per day, 30 globally per 10 minutes and a $1 daily cap. IPv6 uses /64 buckets; mapped IPv4 uses individual IPv4 buckets. Shared Upstash Redis is required when hosted. Keys use `weblinks:` with hashed IPs and hashed lowercase, whitespace-collapsed prompts. All up to ten shaped rows are cached for 900 seconds, independently of requested count. Cache hits cost $0 and bypass limits and the spend cap, even while live mode is paused. Empty results are successful but are not cached.

Uncached live requests require `DEMO_LIVE=1`. Missing configuration, disabled live mode, exhausted cap or state errors return paused 503 with a clearly labelled fictional saved sample. Limits return 429. Upstream errors return 502 without a sample. The page clears previous results on errors and empty searches.

Cost priority: valid case-insensitive `X-Desearch-Cost-Usd` header, body `cost_usd`, then fallback $0.005. Failed calls are accounted for too. The fallback is reserved before calling upstream, then adjusted to actual cost. Reservations are not atomic across instances; concurrent calls or costs beyond the remaining budget can exceed the cap. Failed adjustments leave the reservation recorded. Responses include `cost_usd_this_request` and the cost header, with `no-store`.

A live search cost $0.004 in a test run on 2026-10-26 (from the X-Desearch-Cost-Usd header).

## Run locally

```sh
python3 -m pip install -r requirements.txt
DEMO_STATE=memory DEMO_LIVE=0 python3 app.py
```

Open http://127.0.0.1:8000. Submit a valid prompt to view the saved sample while paused. For live searches, supply `DESEARCH_API_KEY` through the server environment and run `DEMO_STATE=memory DEMO_LIVE=1 python3 app.py`. Keys are never read from files or placed in the page. Memory mode is local only and refused on Vercel.

| Variable | Default or purpose |
|---|---|
| `DESEARCH_API_KEY` | Server-only Desearch credential |
| `KV_REST_API_URL` | Upstash REST URL; alias `UPSTASH_REDIS_REST_URL` |
| `KV_REST_API_TOKEN` | Upstash REST token; alias `UPSTASH_REDIS_REST_TOKEN` |
| `DEMO_LIVE` | Unset pauses; exactly `1` enables uncached live calls |
| `DEMO_STATE` | Redis by default; `memory` only locally |
| `DEMO_PER_IP_10MIN` | `5` per network per 10 minutes |
| `DEMO_PER_IP_DAY` | `15` per network per day |
| `DEMO_GLOBAL_10MIN` | `30` globally per 10 minutes |
| `DEMO_DAILY_CAP_USD` | `1.0` per UTC day |
| `DEMO_FALLBACK_COST_USD` | `0.005` if no valid upstream cost |

Run offline tests from this directory: `python3 -m pytest -q`. Tests use fakes and block network access. See [DEPLOY.md](DEPLOY.md) for preview and production setup. Application handlers log no prompts or keys. Vercel's platform log may still record the request path including the query.
