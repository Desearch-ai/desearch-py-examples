# Deploying the AI Fact Checker demo (Vercel)

Made by Desearch | https://desearch.ai

Layout Vercel uses: `public/index.html` (static page), `api/check.py` (Python function at `/api/check`), `vercel.json` (function `maxDuration` 60 s, `includeFiles: factcheck/**`, security headers). No build step and no third-party packages.

## 1. Project
- New Vercel project from this folder (root directory = this example folder). Framework preset: Other. No build command.
- Domain: e.g. `fact-checker.demos.desearch.ai` or `demos.desearch.ai/...` (Temo's call).

## 2. Environment variables (Production)
| Name | Value | Notes |
|---|---|---|
| `DESEARCH_API_KEY` | the Desearch key | Server-side only. Never add a `NEXT_PUBLIC_`/client prefix. |
| `DEMO_LIVE` | `1` | `0` = kill switch: no API calls, the page points to `/sample.json`. |
| `DEMO_DAILY_CAP_USD` | `1.0` | Per warm instance, UTC day. |
| `DEMO_PER_IP_10MIN` | `5` | Per warm instance. |
| `DEMO_PER_IP_DAY` | `15` | Per warm instance. |
| `DEMO_GLOBAL_10MIN` | `30` | Per warm instance. |
Do not set `FACTCHECK_LOG_DIR` in production (it writes raw responses to disk).

## 3. What protects the key and the balance
- The key is read in `factcheck/client.py` and only sent in the `Authorization` header to `api.desearch.ai`. Responses never include it; the client refuses to write any file that contains it; the function logs one line per paid check (`calls`, `cost`, `spent_today`) and never the claim text or IP.
- Result responses carry `Cache-Control: public, max-age=0, s-maxage=21600`, so the Vercel CDN answers repeat claims (same normalized `claim` query string) for 6 hours without running the function. Errors, 429 and 503 are `no-store`.
- Limits and the daily cap are in memory, so each warm instance has its own counters (best effort). The hard outer limit is the key's balance; keep it small.

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
Then set `DEMO_LIVE=0`, redeploy or wait for the env change, and confirm `/api/check?claim=Honey+never+spoils+if+stored` returns 503 with `"sample": "/sample.json"`. Set it back to `1`.

## 5. Local run, same code
`DESEARCH_API_KEY_FILE=/path/to/key python3 app.py` serves the same page and `/api/check` at http://127.0.0.1:8000.
