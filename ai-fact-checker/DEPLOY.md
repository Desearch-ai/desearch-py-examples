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

## 2. Environment variables (Production)
| Name | Value | Notes |
|---|---|---|
| `DESEARCH_API_KEY` | the Desearch key | Server-side only. Never add a `NEXT_PUBLIC_`/client prefix. |
| `DEMO_LIVE` | `1` | `0` = kill switch: no API calls, the page points to `/sample.json`. |
| `DEMO_DAILY_CAP_USD` | `1.0` | Per warm instance, UTC day. |
| `DEMO_PER_IP_10MIN` | `5` | Per warm instance. |
| `DEMO_PER_IP_DAY` | `15` | Per warm instance. |
| `DEMO_GLOBAL_10MIN` | `30` | Per warm instance. |
| `DEMO_FALLBACK_COST_USD` | `0.005` | Optional. What a call counts against the cap when the API returns no cost header and no body `cost_usd`. |
Only `DESEARCH_API_KEY` must be set; the others fall back to the defaults above when unset. Do not set `FACTCHECK_LOG_DIR` in production (it writes raw responses to disk). Vercel applies env changes only to new deployments, so redeploy after any change.

## 3. What protects the key and the balance
- The key is read in `factcheck/client.py` and only sent in the `Authorization` header to `api.desearch.ai`. Responses never include it; the client refuses to write any file that contains it; the function logs one line per paid check (`calls`, `cost`, `spent_today`) and never the claim text or IP.
- Result responses carry `Cache-Control: public, max-age=0, s-maxage=21600`, so the Vercel CDN answers repeat requests for the exact same URL for 6 hours without running the function (the in-memory cache also catches the same claim written with different case or punctuation, inside one warm instance). Errors, 429 and 503 are `no-store`.
- Limits and the daily cap are in memory, so each warm instance has its own counters and a cold start resets them (best effort, no KV). With N warm instances the real ceiling is about N x $1/day. The hard outer limit is the key's balance; keep it small.
- The per-IP limit uses the first `X-Forwarded-For` address. Vercel overwrites that header with the real client IP, so callers cannot spoof it there (locally they can).

## 4. Smoke test after deploy (about $0.006)
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

## 5. Local run, same code
`DESEARCH_API_KEY_FILE=/path/to/key python3 app.py` serves the same page and `/api/check` at http://127.0.0.1:8000.
