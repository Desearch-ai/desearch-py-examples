# Deploying the AI Search Engine demo (Vercel)

Made by Desearch | https://desearch.ai

Layout Vercel uses: `public/index.html` (static page), `api/search.py` and `api/answer.py` (Python functions at `/api/search` and `/api/answer`), `vercel.json` (`maxDuration` 30 s for search and 60 s for answer, `includeFiles: searchapp/**`, security headers). No build step and no third-party packages.

## 1. Project
| Setting | Value |
|---|---|
| Vercel project | `desearch-ai-search-engine` |
| Git repo / Root Directory | `Desearch-ai/desearch-py-examples`, `ai-search-engine-web-app` |
| Framework preset | Other. No build command, no install command. Leave Output Directory on the default: with a `public/` folder present, Vercel serves only `public/`. Do not override it to `.`, or DEPLOY.md, README.md and the source would be public |
| Runtime | Python, Vercel's default version. `vercel.json` sets `maxDuration` 30 s for `api/search.py` and 60 s for `api/answer.py` |
| Domain | `search.demos.desearch.ai` |
| DNS | `CNAME search -> cname.vercel-dns.com` in the `demos.desearch.ai` zone (or the target Vercel shows under Domains). Not needed if `demos.desearch.ai` is already on Vercel DNS or has a wildcard |

There is no `requirements.txt` on purpose: the functions use only the standard library. `requirements-dev.txt` (pytest) is for the tests and is not installed by Vercel.

## 2. Environment variables (Production)
Only `DESEARCH_API_KEY` is required. The others have the defaults below when unset.

| Name | Default | Notes |
|---|---|---|
| `DESEARCH_API_KEY` | (required) | Server-side only. Never add a `NEXT_PUBLIC_`/client prefix. |
| `DEMO_LIVE` | `1` | `0` = kill switch: no API calls, the page shows `/sample.json`. |
| `DEMO_DAILY_CAP_USD` | `1.0` | Per warm instance (each function has its own), UTC day. |
| `DEMO_PER_IP_10MIN` | `10` | Per warm instance. |
| `DEMO_PER_IP_DAY` | `40` | Per warm instance. |
| `DEMO_GLOBAL_10MIN` | `60` | Per warm instance. |
| `DEMO_FALLBACK_COST_USD` | `0.005` | What a call counts against the daily cap when the API reports no cost at all (no `X-Desearch-Cost-USD` header and no `cost_usd` in the body). |

Never set `SEARCHAPP_LOG_DIR` or `DESEARCH_API_KEY_FILE` in production (the first writes raw responses to disk, the second is for local runs).
Vercel applies env var changes only to new deployments, so redeploy after changing any of them (including `DEMO_LIVE`).

## 3. What protects the key and the balance
- The key is read in `searchapp/client.py` and only sent in the `Authorization` header to `api.desearch.ai`. Responses never include it; the client refuses to write any file that contains it; the functions log one line per paid call (`cost`, `spent_today`) and never the query or IP.
- `POST /search` returns its cost only in the JSON body (`cost_usd`), not in `X-Desearch-Cost-Usd`. The client reads the header first, then the body. If neither is there, the call counts `DEMO_FALLBACK_COST_USD` against the cap, so a missing cost can never switch the cap off.
- Result responses carry `Cache-Control: public, max-age=0, s-maxage=21600`, so the Vercel CDN answers repeat requests for 6 hours without running a function. The CDN keys on the exact URL, so `q=Rate+limiting` and `q=rate+limiting` are two CDN entries; the in-memory cache inside a warm instance still treats them as one. Errors, 400, 429 and 503 are `no-store`.
- The per-IP limit uses the first `X-Forwarded-For` address. Vercel sets that header itself and does not pass a client's own value through.
- Limits and the daily cap are in memory, so each warm instance has its own counters (best effort), and they reset when Vercel starts a fresh instance. Search and answer are separate functions, so each has its own $1.00 cap; set `DEMO_DAILY_CAP_USD=0.5` if the total must stay at $1.00. With N warm instances the real ceiling is about N times that. The hard outer limit is the key's balance; keep it small.

## 4. Smoke test after deploy (about $0.009)
```bash
U=https://<demo-host>
curl -s -o /dev/null -w "%{http_code}\n" $U/                                          # 200
curl -s -i "$U/api/search?q=" | head -1                                               # 400, no cost
curl -s -D - "$U/api/search?q=python+3.14+free+threading&range=year" -o s1.json | grep -i -E "^HTTP|cache-control|x-vercel-cache"
python3 -c "import json;d=json.load(open('s1.json'));print(d['cost_usd'],len(d['results']),d['stats'])"   # 0.005 10 {...}
curl -s -D - "$U/api/search?q=python+3.14+free+threading&range=year" -o /dev/null | grep -i x-vercel-cache   # HIT on repeat
curl -s "$U/api/answer?q=python+3.14+free+threading" -o a1.json && python3 -c "import json;d=json.load(open('a1.json'));print(d['cost_usd'],len(d['links']),d['declined'])"   # 0.004 10 ...
grep -c "$(cut -c1-8 <<<"$DESEARCH_API_KEY")" s1.json a1.json                          # 0 and 0
```
Then set `DEMO_LIVE=0`, redeploy, and confirm `/api/search?q=rate+limiting` returns 503 with `"sample": "/sample.json"` and the page shows the saved run. Set it back to `1` and redeploy.

## 5. Local run, same code
`DESEARCH_API_KEY_FILE=/path/to/key python3 app.py` serves the same page, `/api/search` and `/api/answer` at http://127.0.0.1:8000.
