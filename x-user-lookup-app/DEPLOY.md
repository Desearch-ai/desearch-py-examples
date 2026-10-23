# Deploy X Account Lookup

Made by Desearch | https://desearch.ai

Create a Vercel project with Root Directory `x-user-lookup-app`, framework Other, no build command and the default output directory. Static files come from `public/`. The Python function is `api/lookup.py`; `vercel.json` includes `xlookup/**`, `core.py` and the saved sample with a 60 second function duration. The upstream timeout is 45 seconds and the browser timeout is 55 seconds. The existing `app.py` remains the local server and CLI.

Create an Upstash Redis database. Set server environment variables for the intended Vercel environment, then redeploy. Never place credentials in public files.

| Variable | Default or purpose |
|---|---|
| `DESEARCH_API_KEY` | Server-only Desearch credential |
| `KV_REST_API_URL` | Upstash REST URL; also accepts `UPSTASH_REDIS_REST_URL` |
| `KV_REST_API_TOKEN` | Upstash REST token; also accepts `UPSTASH_REDIS_REST_TOKEN` |
| `DEMO_LIVE` | `1`; any other value pauses uncached lookups |
| `DEMO_PER_IP_10MIN` | `5` lookups per network per 10 minutes |
| `DEMO_PER_IP_DAY` | `15` lookups per network per day |
| `DEMO_GLOBAL_10MIN` | `30` lookups globally per 10 minutes |
| `DEMO_DAILY_CAP_USD` | `1.0` per UTC day |
| `DEMO_FALLBACK_COST_USD` | `0.003` when no valid upstream cost is available |
| `DEMO_STATE` | Leave unset for Redis; `memory` is for local testing only and refused on Vercel |

All Redis keys use `xlookup:`. Cache keys hash normalized lowercase usernames and expire after 900 seconds. Cache hits are free and bypass the limits and spend cap, including while live mode is paused. Invalid input returns 400 before touching state. Redis configuration, transport, decoding or other state errors return paused 503 with the saved sample. There is no automatic memory fallback.

IP buckets are individual IPv4 addresses or IPv6 /64 networks. Mapped IPv4 uses the IPv4 bucket. Forwarding headers are checked in order: `x-vercel-forwarded-for`, `x-forwarded-for`, `x-real-ip`, then the socket address. Vercel must supply trusted headers. Redis uses fixed 10 minute and UTC day windows; every admission attempt increments all three counters, including denied attempts. Counter expiry is twice the window. The local memory limiter uses sliding 10 minute and rolling 24 hour windows.

The daily cap checks shared spend, reserves the fallback amount before the upstream call, then adds the difference to the actual cost. Cost priority is a valid case-insensitive `x-desearch-cost-usd` header, then body `cost_usd`, then fallback. A 404 uses its header cost or zero and returns `not found`. Spend keys expire after 48 hours. Checks and reservations are separate Redis operations, so concurrent calls and calls costing more than the remaining budget can exceed the cap. A failed adjustment leaves the reservation recorded. No retries or redirects are followed. API responses use `no-store`.

Run the offline suite first:

```sh
cd x-user-lookup-app
python3 -m pytest -q
```

Deploy a preview first, selecting the project and target explicitly:

```sh
vercel link --project <preview-project>
vercel deploy --target=preview
```

Preview checks:

1. Set `DEMO_LIVE=0`. Open `/` and `/sample.json`; confirm fictional EXAMPLE data and cost $0. A valid uncached `/api/lookup?username=example` returns paused 503 with the sample.
2. Request `/api/lookup?username=bad-name`; confirm 400 and cost $0.
3. Enable live mode with Redis and the server key. Look up `desearch_ai`; confirm the profile, recent posts, UTC times and cost. Repeat using uppercase or `@desearch_ai`; confirm `cached: true` and cost $0.
4. In preview, lower the rate limits and use distinct valid uncached usernames to confirm 429. Set the daily cap to zero to confirm paused 503 without an upstream request.
5. Remove Redis configuration in preview and confirm paused 503. Memory mode on Vercel must also pause. Confirm errors clear previous results, and the sample button remains available.
6. Inspect public files and responses for credentials. Confirm links use HTTP/HTTPS and `noopener noreferrer`.

After reviewing preview, link the intended production project and deploy with an explicit production target:

```sh
vercel link --project <production-project>
vercel deploy --target=production
```

Configure a custom domain only with the DNS records provided by Vercel. Live checks consume credits for fresh valid lookups. Application handlers log no usernames or keys and suppress request logging. Vercel's platform log may still record the path, including the GET query string.
