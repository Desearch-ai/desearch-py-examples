# Reddit search demo

Made by Desearch | https://desearch.ai

Type a topic to get up to 10 public Reddit threads, with subreddit, title, link and a snippet when available. Dates are not shown because the API returns none. Poster names are hidden. Runtime uses only the Python standard library.

## How it works

`GET /api/search?topic=keeping+houseplants+alive+in+winter` validates plain words before state or upstream access. Whitespace is collapsed. Topics must contain 1 to 200 characters, no control characters and no `site:` operator. Invalid input costs $0 and consumes no limits.

One `GET https://api.desearch.ai/web` sends `query=site:reddit.com <topic>` and `start=0`. Authorization uses the raw server credential. Redirects and retries are disabled. Timeout is 45 seconds. Only public Reddit thread paths survive filtering. Links are canonicalized and deduplicated by thread ID, keeping the first 10. Login titles are rebuilt from link slugs and labelled. There is no thread reading or generated text.

An uncached search cost $0.001, measured 2026-10-26. Cost comes from the case-insensitive cost header, then body `cost_usd`, then the fallback. The server reserves the fallback before calling and adjusts to known cost. Failed adjustments retain the reservation. Checks and reservations are separate operations, so concurrent runs or a cost exceeding remaining capacity can exceed the cap.

## Limits and cache

Defaults are 5 requests per network per 10 minutes, 15 per day, 30 globally per 10 minutes and a $1 UTC daily cap. IPv6 uses /64 buckets. Mapped IPv4 uses individual IPv4 buckets. IPs are hashed. Shared Upstash REST state uses `redditsearch:`. Cache keys hash normalized lowercase topics. Only shaped results are stored for 900 seconds. Paid empty results are cached. Errors are not cached. Cache hits cost $0 and bypass limits, the cap and the live switch.

Uncached calls require exactly `DEMO_LIVE=1`. Missing configuration, unavailable state and the daily cap return paused 503 with a labelled saved sample dated 2026-10-26. Rate limits return 429. Unsuccessful upstream responses return 502 without sample content. Hosted state fails closed. Memory mode is refused on Vercel. Shared limits use fixed windows and increment all counters on admission attempts. Local limits use sliding windows. Forwarding header priority is `x-vercel-forwarded-for`, `x-forwarded-for`, `x-real-ip`, then the socket address. Hosting must supply trusted forwarding headers.

## Run locally

```sh
python3 -m pip install -r requirements.txt
DEMO_STATE=memory DEMO_LIVE=0 python3 app.py
```

Open http://127.0.0.1:8000. A valid topic shows the saved sample while paused. Supply the server credential and set `DEMO_LIVE=1` for live searches. The local server defaults to memory state and binds to localhost.

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
| `DEMO_FALLBACK_COST_USD` | `0.001` if no valid upstream cost |

## Files and verification

`redditsearch/` contains the client, thread shaping, state, guards and service. `api/search.py` is the hosted handler. `app.py` serves locally. `public/` holds the page and real saved sample. `tests/fixtures/` holds the original search response. `tests/` checks offline behavior and source parity. `vercel.json` configures hosting and security headers.

Run `python3 -m pytest -q`. Tests block network access. Handlers suppress request logs. Hosting platform logs may still contain request paths and topics. See [DEPLOY.md](DEPLOY.md).

For the MCP `ai-search` path with a short summary, see the sibling [Reddit search MCP example](../reddit-search-mcp/README.md).
