# Deploying the AI Fact Checker demo (Vercel)

Made by Desearch | https://desearch.ai

Layout Vercel uses: `public/index.html` (static page), `api/check.py` (Python function at `/api/check`), `vercel.json` (function `maxDuration` 60 s, `includeFiles: factcheck/**`, security headers). No build step and no third-party packages (there is no `requirements.txt`, so Vercel installs nothing; `pytest` is in `requirements-dev.txt` for local tests only).

## 1. Project
| Setting | Value |
|---|---|
| Project name | `desearch-ai-fact-checker` |
| Git repo / Root Directory | `Desearch-ai/desearch-py-examples`, root directory `ai-fact-checker` |
| Framework preset | Other. Build command: none. Output directory: default (Vercel serves `public/`). Install command: default (nothing to install). |
| Runtime | Vercel Python runtime (default version), function `api/check.py` with `maxDuration` 60 s from `vercel.json`. One live check took about 10 s on 2026-10-19. |
| Domain | `fact-checker.demos.desearch.ai` (add it under Project → Domains; DNS: `CNAME fact-checker.demos` → `cname.vercel-dns.com` (or the exact target Vercel shows on the Domains page), unless `demos.desearch.ai` already uses Vercel nameservers or a wildcard, then Vercel adds it automatically) |

## 2. Upstash Redis (shared counters)
The per-IP limits (5 per 10 min, 15 per UTC day), the global limit (30 per 10 min) and the daily USD cap ($1) are stored in Upstash Redis so they hold across Vercel instances.

1. In the Vercel dashboard open Marketplace and add Upstash Redis.
2. Create a Redis database and link it to the project `desearch-ai-fact-checker`.
3. Linking the integration writes REST credentials onto that project. The function reads `KV_REST_API_URL` and `KV_REST_API_TOKEN`, and it also accepts `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`. If both pairs are set, `KV_REST_API_*` is used. Server-side only: do not add a `NEXT_PUBLIC_` prefix, and do not put the token in the page, in client code, or in logs.
4. Set `DEMO_IP_SALT` to a long random string. The client IP is hashed with SHA-256 and this salt before it is placed in a key name. If the salt is unset, a built-in fallback salt is used.
5. Redeploy. Vercel applies env changes only to new deployments.

Each counter is one Redis transaction (`POST /multi-exec`): `INCR` and `EXPIRE` together. The daily cap uses `INCRBYFLOAT` and `EXPIRE` on one key. Keys are fixed windows. The 10 min buckets are named by the window start. The per-IP day counter and the USD cap are named by the UTC day. The TTL matches the window: 600 seconds, or 86400 seconds (one UTC day) for daily keys. The function checks the cap and the limits before a paid call, and records the call cost after it.

On Vercel, where `VERCEL` is set or `VERCEL_ENV` is `production` or `preview`, the Redis URL and token are required. If neither `KV_REST_API_*` nor `UPSTASH_REDIS_REST_*` is configured, `/api/check` fails closed: HTTP 503, `Cache-Control: no-store`, and `"sample": "/sample.json"`, the same response as the kill switch (`DEMO_LIVE=0`). No paid call is made. The in-memory counters are not used on Vercel. Locally (`python3 app.py`, no `VERCEL` var), a missing store still falls back to those in-memory counters and logs a warning once. If the store is set but a call to it fails, the function fails closed the same way.

## 3. Environment variables (Production)
| Name | Value | Notes |
|---|---|---|
| `DESEARCH_API_KEY` | the Desearch key | Server-side only. Never add a `NEXT_PUBLIC_`/client prefix. |
| `DEMO_LIVE` | `1` | `0` = kill switch: no API calls, the page points to `/sample.json`. |
| `DEMO_DAILY_CAP_USD` | `1.0` | Shared via Upstash, UTC day. |
| `DEMO_PER_IP_10MIN` | `5` | Shared, fixed 10 min window. |
| `DEMO_PER_IP_DAY` | `15` | Shared, UTC day. |
| `DEMO_GLOBAL_10MIN` | `30` | Shared, fixed 10 min window. |
| `DEMO_FALLBACK_COST_USD` | `0.005` | Optional. What a call counts against the cap when the API returns no cost header and no body `cost_usd`. |
| `DEMO_IP_SALT` | a long random string | Optional. Salt for the SHA-256 of the client IP used in Redis key names. A built-in fallback is used when unset. |
| `KV_REST_API_URL` | from the Upstash integration | Server-side only. Preferred REST URL. |
| `KV_REST_API_TOKEN` | from the Upstash integration | Server-side only. Preferred REST token. Never log it. |
| `UPSTASH_REDIS_REST_URL` | alias of the URL | Accepted when `KV_REST_API_URL` is unset. Server-side only. |
| `UPSTASH_REDIS_REST_TOKEN` | alias of the token | Accepted when `KV_REST_API_TOKEN` is unset. Server-side only. Never log it. |
Only `DESEARCH_API_KEY` must be set for a local run. On Vercel, also set a Redis URL and token or `/api/check` returns 503 (see section 2). The other demo settings fall back to the defaults above when unset. Do not set `FACTCHECK_LOG_DIR` in production (it writes raw responses to disk). Vercel applies env changes only to new deployments, so redeploy after any change.

## 4. What protects the key and the balance
- The key is read in `factcheck/client.py` and only sent in the `Authorization` header to `api.desearch.ai`. Responses never include it; the client refuses to write any file that contains it; the function logs one line per paid check (`calls`, `cost`, `spent_today`) and never the claim text, the IP, or the Redis token.
- Result responses carry `Cache-Control: public, max-age=0, s-maxage=21600`, so the Vercel CDN answers repeat requests for the exact same URL for 6 hours without running the function (the in-memory cache also catches the same claim written with different case or punctuation, inside one warm instance). Errors, 429 and 503 are `no-store`.
- Limits and the daily cap live in Upstash Redis (section 2), so every warm instance shares them. The in-memory result cache is still per instance. The hard outer limit is the key's balance; keep it small.
- The per-IP limit uses the first `X-Forwarded-For` address. Vercel overwrites that header with the real client IP, so callers cannot spoof it there (locally they can). That address is hashed (SHA-256 with `DEMO_IP_SALT`, or the built-in fallback salt) before it is used in a Redis key.

## 5. Smoke test after deploy (about $0.006)
```bash
U=https://<demo-host>
curl -s -o /dev/null -w "%{http_code}\n" $U/                                   # 200
curl -s -i "$U/api/check?claim=" | head -1                                     # 400, no cost
curl -s -D - "$U/api/check?claim=Octopuses+have+three+hearts+and+blue+blood" -o r1.json | grep -i -E "^HTTP|cache-control|x-vercel-cache"
python3 -c "import json;d=json.load(open('r1.json'));print(d['calls'],d['cost_usd'],len(d['sources']))"   # 2 0.0055 10
curl -s -D - "$U/api/check?claim=Octopuses+have+three+hearts+and+blue+blood" -o /dev/null | grep -i x-vercel-cache   # HIT on repeat
grep -c "$(cut -c1-8 <<<"$DESEARCH_API_KEY")" r1.json                           # 0
```
Then set `DEMO_LIVE=0`, redeploy (env changes only reach new deployments), and confirm `/api/check?claim=Honey+never+spoils+if+stored` returns 503 with `"sample": "/sample.json"`. Set it back to `1`.

Per-IP limit (about $0.028 for five paid checks; the sixth is refused). Use a different claim each time so the CDN does not answer from cache. The first five lines are HTTP 200. The sixth is HTTP 429 with `Cache-Control: no-store`.
```bash
for i in 1 2 3 4 5 6; do
  echo "check $i"
  curl -s -D - -o /dev/null "$U/api/check?claim=Honey+never+spoils+check+$i+stored+sealed" | grep -i -E "^HTTP|cache-control"
done
```

Daily cap (no paid call). Set `DEMO_DAILY_CAP_USD=0`, redeploy, then:
```bash
curl -s -D - "$U/api/check?claim=Honey+never+spoils+if+stored" -o cap.json | grep -i -E "^HTTP|cache-control"
# 503 and cache-control: no-store
grep sample cap.json
# "sample": "/sample.json"
```
Set `DEMO_DAILY_CAP_USD` back to `1.0` and redeploy.

## 6. Local run, same code
`DESEARCH_API_KEY_FILE=/path/to/key python3 app.py` serves the same page and `/api/check` at http://127.0.0.1:8000. Without the Redis env vars, and only when `VERCEL` is unset and `VERCEL_ENV` is not `production` or `preview`, the process logs one warning and uses the in-memory counters.
