# Deploy

Set the Vercel root directory to `ai-news-today-board`. The Python function is `/api/board`, with a 60 second duration limit. Static files are in `public/`.

Set `DESEARCH_API_KEY` in the host environment. Credentials are read only at runtime. No credential files are used. Locally, run `python app.py` after setting the environment variable, or use `DEMO_LIVE=0` without a key to view the saved sample.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `UPSTASH_REDIS_REST_URL` or `KV_REST_API_URL` | Required for shared state | Upstash Redis REST endpoint URL. The UPSTASH value takes precedence |
| `UPSTASH_REDIS_REST_TOKEN` or `KV_REST_API_TOKEN` | Required for shared state | Redis REST token with read and write access. The UPSTASH value takes precedence |
| `DEMO_STATE` | Redis | Set to `memory` only for local or offline development to use per process limits, spending and cache |
| `DEMO_LIVE` | `1` | `0` pauses paid builds and serves a 503 pointing to `/sample.json` |
| `DEMO_DAILY_CAP_USD` | `1.0` | Stop new builds when recorded daily spending reaches this amount |
| `DEMO_PER_IP_10MIN` | `5` | Requests per IP over ten minutes |
| `DEMO_PER_IP_DAY` | `15` | Requests per IP over 24 hours |
| `DEMO_GLOBAL_10MIN` | `30` | Requests across IPs over ten minutes |
| `DEMO_FALLBACK_COST_USD` | `0.005` | Cost used when a billable response has no reported cost |
| `DEMO_X_FILTER` | `1` | `0` disables the display filter for profanity, NSFW words, replies and low engagement posts without links |
| `DEMO_X_MIN_ENGAGEMENT` | `5` | Minimum likes + reposts + replies for a post without a content link |

Tune the small whole-word, case-insensitive list in `newsboard/xfilter.py`. This basic filter cannot guarantee suitability of every post. Account mentions remain excluded and authors appear as "a user".

Each build makes ten calls in parallel. Cost uses the response header first, then body `cost_usd`, then the fallback. Status 401/402/403 counts zero against the cap and pauses the response with a sample link. Other successful calls in that build still count. Some failed searches produce `partial: true`; losing every X search or every web search produces 502.

Limits, daily spending and result cache use shared Upstash Redis REST state under the `news:` namespace. IP addresses and cache keys are hashed with SHA256. Limits use fixed ten minute and 24 hour windows. Spending rolls over at midnight UTC and expires after two days. Results expire after six hours. Redis requests have a three second timeout. Missing configuration, connection failures, invalid tokens and Redis errors return the paused 503 response with a saved sample link before any paid build begins. Live mode never falls back to memory automatically.

Set `DEMO_STATE=memory` explicitly for local or offline development without Redis. Injecting in-memory limiter, cap or cache objects when constructing the service also explicitly opts into memory defaults for the other stores. When `VERCEL` has any non-empty value, `DEMO_STATE=memory` is refused and requests return the paused 503 response with the saved sample before any paid call, while explicitly injected test stores remain supported.

Limits and spending are best effort: a build can pass the cap before its final costs are known, and simultaneous builds on separate instances can run before either caches its result. The CDN cache is the primary guard: successful responses use `public, max-age=0, s-maxage=21600`. Cache hits precede pause and cap checks. Errors use `no-store`. No request lines or credentials are logged; build logs contain only call count and spending.

The saved sample is generated offline through `build_board` from `samples/sample-raw.json`. It is dated sample data, not today's coverage.
