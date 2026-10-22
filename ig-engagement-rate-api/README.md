# IG Engagement Rate

Made by Desearch | https://desearch.ai

A Vercel-deployable Python backend demo for recent public Instagram engagement. Uses only two Desearch REST GET routes: `/desearch/instagram/profile/{username}` and `/desearch/instagram/profile/{username}/posts?count=12`. No SDK, pagination, cursor, redirects or retries.

Run `DEMO_STATE=memory DEMO_LIVE=0 python app.py` for a free local preview. Open http://127.0.0.1:8000. To enable local lookups, set `DESEARCH_API_KEY` in your server environment and `DEMO_LIVE=1`. Keys are read at request time and never from files. See [DEPLOY.md](DEPLOY.md) for production shared state setup.

`GET /api/engagement?handle=yourhandle` accepts one handle, optionally starting with `@`, and normalizes to lowercase. URLs and invalid handles return 400. A profile with `is_private: true`, a profile 404, any non-200 posts response, or an empty post list returns 404 with `{"error":"account not found or private"}`. Profile authentication, balance, server and timeout failures return a paused 503 with the clearly labelled sample.

Results use `accounts`, with `handle`, `followers`, `posts_used`, `eligible_posts`, `engagement_rate_pct`, `by_format`, and `posts`. Each post contains only `url`, `type`, `likes`, `comments`, `taken_at`. Both post counts describe posts included in the rate; the table also includes excluded posts. Rates average `(likes + comments) / followers * 100` over eligible posts. Posts younger than 24 hours, hidden likes and likely pinned posts are excluded. The pinned heuristic detects up to three initial posts older than the following post, as in the reference calculator. Missing timestamps are excluded. Missing comments count as zero in the formula. No qualifying posts or zero followers returns `null` rates, displayed as n/a.

Featured handles in `public/sample.json` are free, dated EXAMPLE snapshots derived from recorded October 17 evidence. They are not current statistics. The first page load uses this file without an API call. Cached live results and featured accounts bypass paid limits. Live results expire after 24 hours and send `s-maxage=86400`; errors use `no-store`.

Offline tests: `cd ig-engagement-rate-api && python -m pytest -q`. Tests unset the API key and block real network access. Runtime uses only the Python standard library; requirements includes pytest for verification.
