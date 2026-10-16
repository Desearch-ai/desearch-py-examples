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

## Known issues
- A cursor the API does not recognise is not rejected: it returns the first page again and is billed. The app only sends cursors the API gave it.
- Pages can overlap: 1 to 3 posts repeated across 3 pages in our tests. The app drops repeats, but they are billed.
- Posts are not always in strict newest-first order (posts a few seconds apart can swap). Sort by `created_utc` if order matters.
- A page has 16 to 18 posts and there is no `count` parameter on this endpoint.
