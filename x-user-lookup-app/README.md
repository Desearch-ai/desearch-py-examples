# X User Lookup App

Made by Desearch, https://desearch.ai

Type a public X username and get a profile card, that account's recent posts, a posts-per-day count, the median likes and a CSV. Built on the Desearch endpoint `GET /twitter/user/posts`. Standard library only: no framework, no X account, no X API setup.

## What it does
- Accepts `name`, `@name` or an `x.com/name` profile link.
- Profile card from the response: name, bio, followers, following, total posts, join date.
- Recent posts with time (UTC), kind (post, reply, repost), text, likes, replies, reposts, views and a link in `x.com/i/status/<id>` form. `@mentions` in text are shown as `@user`.
- Follows `next_cursor` for up to 2 more pages (3 pages in total, about 50 posts). Stops early if the API returns no cursor or the same cursor again. Posts that repeat across pages are dropped and counted.
- Stats over the returned posts: posts per day, median likes, first and last post time.
- "Download CSV" exports the same lookup.
- Input is checked before any API call (blank, longer than 15 characters, characters other than letters, digits and `_`, pages outside 1 to 3). A bad form returns HTTP 400 and costs nothing.
- A username with no public account returns a "not found" page (HTTP 404 from the API, cost $0 in our test).

## Run
```bash
python3 -m pip install -r requirements.txt   # only pytest, for the tests
export DESEARCH_API_KEY=your_key             # or DESEARCH_API_KEY_FILE=/path/to/key
python3 app.py --port 8000                   # open http://127.0.0.1:8000
python3 app.py --cli desearch_ai --pages 3 --csv desearch_ai-posts.csv   # or as a CLI
```
Add `--log-dir runs/today` to save each API call (with the key redacted) for debugging.

The same data is available to AI assistants through the Desearch MCP tool `x-user-posts`. This app uses the REST endpoint only.

## Files
- `core.py`: username check, paging rules, profile card, post rows, stats, CSV and HTML. No network.
- `app.py`: the HTTP server, the CLI and the Desearch client.
- `test_core.py`: offline tests, `python3 -m pytest -q`.
- `samples/`: one lookup page, its CSV, and a short lookup summary.

## Cost
Billing is per post returned: a page of 16 to 18 posts cost $0.0024 to $0.0027 in our runs, so a 3-page lookup is about $0.0077. The cost of each call is in the `X-Desearch-Cost-Usd` response header.

## Response details
- The local app follows only cursors supplied by the API, drops repeated posts and counts them.
- Posts may arrive outside strict newest-first order. Sort by `created_utc` if order matters.
- The endpoint chooses its page size and has no `count` parameter.

## Hosted demo

For marketing, community and partnerships teams, the hosted page shows a public X profile and recent posts to help assess an account before outreach. The labelled fictional sample loads without an API call. Submit a username, `@name` or an `x.com/name` link for a live lookup.

The hosted endpoint is `GET /api/lookup?username=desearch_ai`. Each uncached lookup makes one GET to `https://api.desearch.ai/twitter/user/posts` with a server-only Authorization header. It does not follow cursors. The existing local server and CLI above retain their paging and CSV features.

The hosted implementation uses `xlookup/`, `api/lookup.py`, `public/` and `vercel.json`, following the web search demo architecture. Runtime dependencies are standard library only. Successful results are cached for 15 minutes by normalized lowercase username. Cache hits cost $0 and consume no limits. Invalid input returns 400 before any state or upstream access. A missing account returns 404 `not found`.

Default limits are 5 lookups per 10 minutes and 15 per day per network, 30 globally per 10 minutes, and a $1 shared daily spend cap. Shared Upstash Redis uses the separate `xlookup:` prefix and is required for hosting. State errors return paused 503 with a saved sample. Memory mode is only for local testing and is refused on Vercel. Set `DEMO_LIVE=0` to pause uncached lookups.

Cost comes from the upstream cost header, then body `cost_usd`, then the $0.003 fallback. A 404 uses its header cost or zero. The fallback is reserved in shared spend before the call and adjusted afterward. Concurrent requests or a call crossing the remaining budget can exceed the cap. The page shows the cached flag and request cost.

See [DEPLOY.md](DEPLOY.md) for all environment variables, Upstash setup, preview checks and deployment with an explicit target. Application handlers log no usernames or keys; Vercel's platform log may still record the path and query string.

Run all offline tests from this directory with `python3 -m pytest -q`.
