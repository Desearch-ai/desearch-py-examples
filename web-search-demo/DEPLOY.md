# Deploy Web Search Demo

Made by Desearch | https://desearch.ai

Create a Vercel project from this repository with Root Directory `web-search-demo`, framework Other, no build command and the default output directory. Add `web-search.demos.desearch.ai` to the project's domains and configure the DNS records shown by Vercel. Static files come from `public/`; `api/search.py` is the Python function. `vercel.json` includes `websearch/**` and `public/sample.json` with a 60 second function duration. The single upstream request has a 45 second timeout; the browser aborts after 55 seconds.

Create an Upstash Redis database and copy its REST URL and token into Vercel's server environment. Use a database or namespace dedicated to this demo when resetting production state. Set these variables in the intended deployment environments, then redeploy:

| Variable | Value / purpose |
|---|---|
| `DESEARCH_API_KEY` | Desearch secret, server runtime only |
| `UPSTASH_REDIS_REST_URL` | Upstash Redis REST endpoint (`KV_REST_API_URL` alias) |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash Redis REST token (`KV_REST_API_TOKEN` alias) |
| `DEMO_LIVE` | `1` live, `0` paused; cache hits remain free |
| `DEMO_PER_IP_10MIN` | Default `5` |
| `DEMO_PER_IP_DAY` | Default `15` |
| `DEMO_GLOBAL_10MIN` | Default `30` |
| `DEMO_DAILY_CAP_USD` | Default `1.0` |
| `DEMO_FALLBACK_COST_USD` | Default `0.001` |
| `DEMO_STATE` | Leave unset for Redis; never use `memory` on Vercel |

State copies the reference demos' Upstash REST pipeline protocol and environment aliases. All keys use the `websearch:` namespace; IP buckets and normalized query/page cache keys are hashed. IPv4 addresses use individual buckets; IPv6 addresses use /64 buckets, with mapped IPv4 handled as IPv4. The client IP helper matches page-to-markdown: first `x-vercel-forwarded-for`, then `x-forwarded-for`, then `x-real-ip`, then the socket address. Vercel must supply trusted forwarding headers. The local server trusts the same headers and binds to localhost.

Redis rate limits use fixed 10 minute windows and UTC day windows. Each admission attempt increments all three counters, including denied attempts, and counter expiry is twice the window. Invalid inputs and cache hits never reach the limiter. The local memory limiter uses the reference sliding windows, including a rolling 24 hour visitor limit. Cache TTL is 600 seconds in both modes. Errors and API responses use `no-store` so HTTP caching does not interfere with cost reporting or limits.

The daily cap reads shared spend before the paid call and adds header cost afterwards, or the $0.001 fallback if the header is unusable. Spend resets by UTC date and expires after 48 hours. As in the reference state implementation, checks and updates do not reserve spend atomically across instances. Concurrent calls or an unexpectedly expensive call can exceed the configured cap; keep the key balance appropriate for the demo. Failed upstream calls are also accounted for using their cost header or fallback. There are no automatic retries. Redis errors at any stage return paused 503; no automatic memory fallback is allowed.

Smoke checks after deployment:

1. With `DEMO_LIVE=0`, open `/` and `/sample.json`. Confirm the saved `bittensor subnet` result is labelled EXAMPLE and costs $0. An uncached valid API query returns paused 503 including the sample.
2. Send `/api/search?q=x&page=1` and a request with `page=3`. Both must return 400 with `X-Desearch-Cost-Usd: 0`, without consuming limits.
3. Enable live mode with configured Redis and key. Search a fresh query on page 1. Confirm title, link and snippet, the limits line and the header-derived cost. Repeat with changed query capitalization and spacing; confirm `cached: true` and cost $0. Page 2 must use a distinct cache entry and one upstream call.
4. In a preview project, use a low per-IP limit and distinct uncached queries to confirm 429. Set `DEMO_DAILY_CAP_USD=0` to confirm paused 503 with sample and no upstream request.
5. In preview, remove or invalidate Redis configuration and confirm valid searches return paused 503. Setting `DEMO_STATE=memory` on Vercel must also return paused 503.
6. Confirm an upstream authentication or service failure returns paused 503, and every error clears earlier displayed results. The sample remains available through the explicit sample button.
7. Inspect public files and API responses for secrets. Application handlers suppress request logging and never return upstream error bodies. Hosting access logs may independently contain query strings; review provider settings. Rendered result links accept only HTTP/HTTPS and use `rel="noopener noreferrer"`.

Run the fully offline suite before deploying: `python -m pytest -q web-search-demo/tests` from the repository root. Live smoke checks spend credits only when explicitly enabling live mode and issuing fresh valid queries.
