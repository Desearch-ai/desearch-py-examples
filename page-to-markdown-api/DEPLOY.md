# Deploy Page to Markdown

Made by Desearch | https://desearch.ai

Import this repository into Vercel and select `page-to-markdown-api` as the Root Directory. Choose the Other framework preset, no build command, and the default output directory so Vercel serves `public/`. The Python function is `api/convert.py`. `vercel.json` includes its package, shared converter and saved sample, and allows 60 seconds.

Configure these server environment variables in Vercel, then redeploy:

| Name | Purpose and safe default |
|---|---|
| `DESEARCH_API_KEY` | Server-only secret, configured in Vercel. Never put it in public files. |
| `KV_REST_API_URL` or `UPSTASH_REDIS_REST_URL` | Redis REST URL, required for shared state. Upstash names take precedence. Server only. |
| `KV_REST_API_TOKEN` or `UPSTASH_REDIS_REST_TOKEN` | Redis REST token, required for shared state. Upstash names take precedence. Server only. |
| `DEMO_STATE` | Default shared Redis state. Set exactly `memory` only for local or offline development with per-process state. |
| `DEMO_LIVE` | Default `1`; set `0` to pause all live conversions. |
| `DEMO_DAILY_CAP_USD` | Default `1.0` per UTC day, shared across instances. |
| `DEMO_FALLBACK_COST_USD` | Default `0.0005` when billing information is absent. |
| `DEMO_PER_IP_10MIN` | Default `5`. |
| `DEMO_PER_IP_DAY` | Default `15` per fixed UTC day. |
| `DEMO_GLOBAL_10MIN` | Default `30`. |

For an offline preview, set `DEMO_STATE` to `memory` and `DEMO_LIVE` to `0` and run `python app.py`. Open the local address printed by the server. The CLI remains available in `page2md.py`.

Each live cache miss sends one Extract GET with the existing Authorization header, no redirects and no retries. Header billing takes precedence over body billing and the fallback. A 404 costs zero; authentication and balance errors pause the demo. Empty pages are billed and cached too. The daily cap prevents subsequent calls once reached; the last call can exceed the remaining balance because actual cost is known only afterward.

Every request, including rejected and cached ones, counts toward the shared rate limits. Redis uses fixed 10 minute windows and fixed UTC day windows. IP addresses and normalized cache keys are hashed with SHA-256 under the `p2m:` namespace. The normalized URL cache expires after six hours, and daily spend keys expire after two days.

Live mode fails closed with the saved paused response when Redis configuration is missing or Redis fails, including authentication errors. There is no automatic memory fallback. Explicitly injected in-memory limiter, cap or cache objects also select memory defaults for tests and local development.

Concurrent requests across instances can pass a budget check before another call records its cost. Keep the shared key balance small as the hard outer ceiling. Cache misses are serialized within an instance. The handler trusts the first forwarded IP set by Vercel; do not expose the local development server through an untrusted proxy.

Responses use `no-store` to keep submitted URLs out of CDN caches. The application does not log request lines, URLs, IPs or raw API bodies and writes no submitted URLs to disk. Hosting access logs may retain query strings independently; review the hosting provider's log settings. DNS checks reject any non-public answer and any exposed unsafe final URL. Extract performs the remote fetch, so redirects it does not expose cannot be inspected here.

Run offline checks from the repository root with `python -m pytest page-to-markdown-api -q` and `DESEARCH_API_KEY` unset.

Submitted URLs allow no explicit port or only the scheme's default port (80 for HTTP and 443 for HTTPS), reject other or malformed ports before DNS resolution, and omit default ports from normalized URLs.
