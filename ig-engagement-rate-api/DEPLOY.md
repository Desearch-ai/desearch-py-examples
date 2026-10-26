# Deploy IG Engagement Rate

Made by Desearch | https://desearch.ai

Import the repository into Vercel, select `ig-engagement-rate-api` as Root Directory, choose Other framework, no build command and the default output directory. Static content comes from `public/`; `api/engagement.py` is the Python function. The function includes `igrate/**` and `public/sample.json` and has a 60 second hosting duration. The upstream lookup has a total 45 second deadline, shared between the two calls; the browser also aborts after 45 seconds.

Set server environment variables, then redeploy:

| Variable | Purpose |
|---|---|
| `DESEARCH_API_KEY` | Runtime server-only Desearch key. Never add to client files. |
| `UPSTASH_REDIS_REST_URL` | Required shared Redis REST endpoint. `KV_REST_API_URL` is an alias. |
| `UPSTASH_REDIS_REST_TOKEN` | Required Redis REST token. `KV_REST_API_TOKEN` is an alias. |
| `DEMO_LIVE` | Default `1`; `0` pauses live requests. Featured and cached results remain free. |
| `DEMO_PER_IP_10MIN` | Default `2`, per-IP 10 minute limit. |
| `DEMO_PER_IP_DAY` | Default `5`, per-IP UTC day limit. |
| `DEMO_GLOBAL_10MIN` | Default `10`, global 10 minute limit. |
| `DEMO_DAILY_CAP_USD` | Default `1.0`, UTC daily shared spend cap. |
| `DEMO_FALLBACK_COST_USD` | Default `0.0135` per response without billing metadata. |
| `DEMO_STATE` | Shared Redis by default. `memory` is for local development only, refused on Vercel. |

Limits default to 2 paid lookups per IP per 10 minutes, 5 per IP per UTC day, and 10 globally per 10 minutes. Production uses the same Redis fixed-window counter pipelines as `page-to-markdown-api/pagemd/state.py`; every attempted admission increments all three counters, including denied attempts. Local memory state copies the reference `guards.py` approach. IPv6 uses /64 buckets. IP buckets and cache handles are hashed under the separate `igrate:` namespace. Missing state configuration or failed Redis means paused 503, without an automatic memory fallback.

The daily cap copies the reference `ok`/`add` storage approach and defaults to $1 through `DEMO_DAILY_CAP_USD`, with the same handling of invalid values. Before either paid call, a read-only cap check requires at least $0.027 of headroom. After the run, actual response costs are added: `x-desearch-cost-usd` header first, body `cost_usd` second, then the fallback per call. A timeout charges at least $0.027. Spend uses the UTC day at accounting time and expires after 48 hours. These checks do not reserve budget atomically across concurrent instances; concurrent calls or higher actual prices can exceed the cap. There are no retries or pagination.

The estimate comes from measured October 17 billing: $0.00207 profile plus $0.00207 per post, $0.02691 for 12 posts. Keep the shared key balance small as the outer spending ceiling and update the estimate if pricing changes.

The client immediately projects decoded responses onto allowed numeric profile fields and five allowed post fields. It never caches or logs raw responses, captions, tagged users or children. It uses the presence of children only to classify an otherwise unknown carousel. Logs from the application suppress request lines and handles. Hosting access logs can independently contain query strings; review provider settings. The local server trusts forwarded headers for parity with Vercel; use it on localhost only. Vercel must set trusted forwarding headers at its edge.

Local preview: `DEMO_STATE=memory DEMO_LIVE=0 python app.py`. Production QA should verify the configured budget, paused mode, featured snapshot and Redis failure behavior before enabling live traffic. Tests run offline and do not spend API credits.
