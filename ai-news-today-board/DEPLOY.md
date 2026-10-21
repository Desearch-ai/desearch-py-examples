# Deploy

Set the Vercel root directory to `ai-news-today-board`. The Python function is `/api/board`, with a 60 second duration limit. Static files are in `public/`.

Set `DESEARCH_API_KEY` in the host environment. Credentials are read only at runtime. No credential files are used. Locally, run `python app.py` after setting the environment variable, or use `DEMO_LIVE=0` without a key to view the saved sample.

| Environment variable | Default | Purpose |
| --- | --- | --- |
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

Limits, cap and memory cache are per warm instance and best effort. A build can pass the cap before its final costs are known. The CDN cache is the primary guard: successful responses use `public, max-age=0, s-maxage=21600`. Cache hits precede pause and cap checks. Errors use `no-store`. No request lines or credentials are logged; build logs contain only call count and spending.

The saved sample is generated offline through `build_board` from `samples/sample-raw.json`. It is dated sample data, not today's coverage.
