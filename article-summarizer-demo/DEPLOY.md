# Deploy article summarizer

Create Vercel project `desearch-ai-article-summarizer`. Set Root Directory to `article-summarizer-demo`, framework Other, no build command and the default output directory. Static files are in `public/`. The function is `api/summarize.py`, with maxDuration 60 and included files `{articlesum/**,public/sample.json}`.

Create shared Upstash Redis state. Configure these environment variable names in the intended environments, then redeploy:

- `DESEARCH_API_KEY`
- `KV_REST_API_URL` or `UPSTASH_REDIS_REST_URL`
- `KV_REST_API_TOKEN` or `UPSTASH_REDIS_REST_TOKEN`
- `DEMO_LIVE`
- `DEMO_PER_IP_10MIN`
- `DEMO_PER_IP_DAY`
- `DEMO_GLOBAL_10MIN`
- `DEMO_DAILY_CAP_USD`
- `DEMO_FALLBACK_COST_USD`
- `DEMO_STATE`

The first deploy stays paused until `DEMO_LIVE=1`. Do not select memory state on Vercel. Missing or unavailable shared state returns paused 503 with the saved sample. See the README for limits, cost accounting and cache behavior.

Run the offline tests before deployment. Deploy a preview with the project and target selected explicitly. Check the page and `/sample.json`, invalid links returning 400, paused 503 with Saved sample, a live article, a free cache hit, near-empty pages, rate limits and the daily cap. Confirm unsuccessful extraction returns 502 without sample content. Check that links wrap on a 375px screen.

After preview review, deploy to the explicit production target. Add `article-summarizer.demos.desearch.ai` using the DNS records supplied by Vercel. Handlers suppress request logging. Hosting platform logs may still contain request paths and queries.
