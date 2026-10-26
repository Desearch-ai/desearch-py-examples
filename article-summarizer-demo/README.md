# Article summarizer demo

Made by Desearch | https://desearch.ai

Paste a public article link to see key sentences and sentences carrying numbers, quoted from the text Desearch read. The output is an extractive summary. Runtime uses only the Python standard library.

## How it works

`GET /api/summarize?url=https%3A%2F%2Fexample.com%2Fnews%2Farticle` validates the URL before state, limits or upstream access. Invalid links cost $0. Only public HTTP and HTTPS pages are accepted. Credentials, downloads, private addresses and unknown hosts are refused. DNS must resolve entirely to public addresses.

The server calls `GET https://api.desearch.ai/web/extract` with `url`, `format=text` and `js=false`. Authorization uses the raw server credential. Redirects are disabled. Each call has a 50 second timeout. A no-content reply is retried exactly once. Other unsuccessful replies return 502 without a sample.

A run with one extract cost $0.0005, measured on 2026-10-26. Two extracts can cost $0.001. Cost comes from the case-insensitive cost header, then JSON `cost_usd`, then `DEMO_FALLBACK_COST_USD`. The fallback reserves $0.001 before extraction and is adjusted to known total cost. If any cost is unknown, the total is at least the fallback. Failed adjustments retain the reservation. Checks and reservations are separate operations, so concurrency or a run exceeding remaining capacity can exceed the cap.

Pages under 150 words return a near-empty notice and a preview of up to 400 characters. Other pages return up to five key sentences and up to eight sentences containing figures. Bare years are skipped. Handles are hidden. Full article text is never returned, cached or logged.

## Limits and cache

Defaults are 5 requests per network per 10 minutes, 15 per day, 30 globally per 10 minutes and a $1 UTC daily cap. IPv6 uses /64 buckets and mapped IPv4 uses individual IPv4 buckets. IPs are hashed. Shared Upstash REST state uses the `articlesum:` prefix. Cache keys hash normalized URLs with lowercase scheme and host and no fragment. Shaped results alone are cached for 900 seconds. Near-empty results and errors are not cached. Cache hits cost $0 and bypass limits, the cap and the live switch.

Uncached calls require exactly `DEMO_LIVE=1`. Missing configuration, state failures and the daily cap return paused 503 with a labelled fictional saved sample. Rate limits return 429. Hosted state fails closed and never falls back to memory. Memory mode is refused on Vercel. Shared limits use fixed windows and increment all counters on admission attempts. Local limits use sliding windows. Forwarding header priority is `x-vercel-forwarded-for`, `x-forwarded-for`, `x-real-ip`, then the socket address; hosting must provide trusted headers.

## Run locally

```sh
python3 -m pip install -r requirements.txt
DEMO_STATE=memory DEMO_LIVE=0 python3 app.py
```

Open http://127.0.0.1:8000. A valid public link shows the saved sample while paused. For live mode supply the server credential and set `DEMO_LIVE=1`. The local server defaults to memory state and binds to localhost.

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

`articlesum/` holds the client, URL guard, summary functions, state, limits and service. `api/summarize.py` is the hosted handler. `app.py` serves locally. `public/` contains the page and fictional sample. `tests/` has offline tests and source parity checks. `vercel.json` configures hosting and security headers.

Run `python3 -m pytest -q`. No real API calls are made. Handlers suppress request logs. Hosting platform logs may still contain request paths and queries. See [DEPLOY.md](DEPLOY.md).
