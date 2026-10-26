# Deploy Reddit search

Create Vercel project `reddit-search-demo`. Set Root Directory to `reddit-search-demo`, framework Other, no build command and the default output directory. Static files are in `public/`. The function is `api/search.py`, with maxDuration 60 and included files `{redditsearch/**,public/sample.json}`.

Reuse the existing shared Upstash store that the other hosted demos use, under the same `KV_REST_API_URL` and `KV_REST_API_TOKEN` names. This demo keeps its own `redditsearch:` key prefix. Configure these environment variable names in the intended environments, then redeploy:

- `DESEARCH_API_KEY`
- `KV_REST_API_URL`
- `KV_REST_API_TOKEN`
- `DEMO_LIVE`
- `DEMO_PER_IP_10MIN`
- `DEMO_PER_IP_DAY`
- `DEMO_GLOBAL_10MIN`
- `DEMO_DAILY_CAP_USD`
- `DEMO_FALLBACK_COST_USD`

The first deploy stays paused until `DEMO_LIVE=1`. Use `DEMO_FALLBACK_COST_USD=0.001`. Leave `DEMO_STATE` unset on Vercel. Missing or unavailable shared state returns paused 503 with the saved sample.

Run offline tests before deployment. Deploy a preview with the project and target selected explicitly. Check the page, `/sample.json`, invalid topics returning 400, paused 503 with Saved sample and its date, live results, an empty result, a free cache hit, rate limits and the daily cap. Confirm unsuccessful searches return 502 without a sample. Check that long titles wrap at 375px.

After preview review, deploy to the explicit production target. Post the DNS records supplied by Vercel for `reddit-search.demos.desearch.ai` for approval before they are added. Handlers suppress request logs. Hosting platform logs may still contain request paths and topics.
