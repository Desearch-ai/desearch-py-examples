# Deploy AI Search Engine demo #10

Create Vercel project `ai-search-engine-demo`, root directory `ai-search-engine-web-app`, framework Other, no build command, default output directory. Functions use the Python standard library; only `requirements-dev.txt` (pytest) is needed for development. Both functions include `{searchapp/**,public/sample.json}`. Search maxDuration is 30 seconds; Answer is 60 seconds.

Reuse the shared Upstash REST store. All keys use the `aisearch` namespace, with hashed network addresses and cache keys. Search and Answer share the limiter and UTC spend key.

| Environment variable | Value or purpose |
|---|---|
| DESEARCH_API_KEY | Server-only API key |
| KV_REST_API_URL | Shared Upstash REST URL |
| KV_REST_API_TOKEN | Shared Upstash REST token |
| DEMO_LIVE | Exactly 1 to enable paid calls; otherwise paused |
| DEMO_PER_IP_10MIN | 5 |
| DEMO_PER_IP_DAY | 15 |
| DEMO_GLOBAL_10MIN | 30 |
| DEMO_DAILY_CAP_USD | 1.0 shared across endpoints |
| DEMO_FALLBACK_COST_USD | 0.005 reserved before every paid call |

Leave `DEMO_STATE` unset on Vercel. Never set `SEARCHAPP_LOG_DIR`, `DESEARCH_API_KEY_FILE`, or any `NEXT_PUBLIC_*` key. Missing or unavailable shared state fails closed with 503 and the saved sample. Cache entries last 900 seconds; responses have no-store headers. Handlers suppress request logs.

Run `python3 -m pytest -q` offline, deploy a preview with the project selected explicitly, and review the page and `/sample.json`. Verify invalid requests, paused samples with dates, live searches, Answer, free cache hits, rate limits and the shared cap. Check URL wrapping at 375px. Refresh the sample using the README capture and build commands before publishing a new saved run.

Use the production domain `ai-search-engine.demos.desearch.ai`. Review the preview before deploying production and applying its domain configuration.
