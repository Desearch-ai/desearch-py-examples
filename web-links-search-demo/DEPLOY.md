# Deploy web links search

Create a Vercel project with Root Directory `web-links-search-demo`, framework Other, no build command and the default output directory. Static files come from `public/`. The function is `api/search.py`; `vercel.json` includes `weblinks/**` and `public/sample.json`, with maxDuration 60. Upstream timeout is 50 seconds; browser timeout is 55 seconds.

Create an Upstash Redis database. Configure server environment variables in the intended Vercel environments and redeploy. Never put credentials in public files. The environment variable names are:

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

See the README environment table for defaults. Leave memory mode disabled on Vercel; it is refused there. Uncached calls require explicit live enablement. Missing Redis configuration and any state errors pause with the saved sample, without falling back to memory.

All Redis keys use `weblinks:`. Normalized lowercase prompts are hashed in cache keys. Cache TTL is 900 seconds and all up to ten shaped rows are stored, so changing count stays free. Invalid input and cache hits consume no limits. Cache hits bypass the cap and live switch. Empty results are not cached.

Defaults are 5 searches per network per 10 minutes, 15 per day, 30 globally per 10 minutes and a $1 daily cap. Redis uses fixed 10 minute and UTC day windows. Every admission attempt increments all three counters, including denied attempts; expiry is twice the window. Local memory uses sliding 10 minute and rolling 24 hour windows. IPv4 addresses are individual buckets; IPv6 uses /64 and mapped IPv4 uses IPv4. IPs are hashed. Forwarding header priority is `x-vercel-forwarded-for`, `x-forwarded-for`, `x-real-ip`, then socket address. Vercel must supply trusted forwarding headers; local serving binds to localhost.

The daily cap checks spend and reserves fallback before calling upstream, then adjusts to header cost, body cost or fallback, in that order. Spend expires after 48 hours. Checks and reservations are separate operations; concurrency or calls exceeding remaining budget can exceed the cap. A failed adjustment leaves the reservation recorded. Upstream errors return 502 with recorded cost and no sample. State errors return paused 503. No retries or redirects. API responses use `no-store`.

Run `python3 -m pytest -q` from this directory before deployment. Deploy a preview first, selecting the project and target explicitly:

```sh
vercel link --project <preview-project>
vercel deploy --target=preview
```

The first deploy of a new Vercel project becomes production. Keep `DEMO_LIVE` unset there until approved, including while preparing preview deployment.

Preview checks:

1. With live mode disabled, open `/` and `/sample.json`. Submit a valid prompt and confirm paused 503 with clearly labelled Saved sample rows and cost zero.
2. Submit an empty prompt, a prompt longer than 200 characters and invalid counts. Confirm 400 and cost zero.
3. Enable live mode with Redis and the server credential. Search a fresh neutral prompt. Confirm title, domain, snippet, optional date and cost. Repeat with different casing, spacing and count. Confirm cached true, sliced rows and cost zero.
4. Lower limits in preview and issue distinct uncached prompts to confirm 429. Set the cap to zero to confirm paused 503 without upstream access.
5. Remove Redis configuration or select memory mode on Vercel and confirm paused 503. Confirm upstream errors return 502 without sample rows, and empty searches clear old results.
6. Inspect public files and responses for credentials. Confirm result links only accept HTTP/HTTPS and use `noopener noreferrer`.

After preview review, select the intended production project and explicit target:

```sh
vercel link --project <production-project>
vercel deploy --target=production
```

Add `web-links-search.demos.desearch.ai` with the DNS records Vercel provides. Fresh live searches spend credits. Application handlers suppress request logging and log no prompts or keys. Vercel's platform log may still record the request path including the query.
