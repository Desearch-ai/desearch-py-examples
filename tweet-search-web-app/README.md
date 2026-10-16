# Tweet Search Web App

A one-page web app to search public X posts with filters, built on the Desearch X search endpoint (`GET /twitter`). Standard library only: no framework, no X account, no X API setup.

## What it does
- One search box, plus an optional "any of" list that becomes `(a OR b)` in the query.
- Filters: sort (Latest or Top), count (1 to 100), language, min likes, min replies, min reposts, verified, blue verified, video, image, quote, date range.
- Results show time (UTC), text, likes, replies and a link in `x.com/i/status/<id>` form. Author handles are not shown, and `@mentions` in text are shown as `@user`.
- "Download CSV" exports the same search.
- Input is checked before any API call (blank query, count out of range, bad language code, negative numbers, bad or reversed dates, future start date). A bad form returns HTTP 400 and costs nothing.
- Each result page says how many posts came back versus how many you asked for, and flags rows that fall outside your filters.

## Run
```bash
python3 -m pip install -r requirements.txt   # only pytest, for the tests
export DESEARCH_API_KEY=your_key             # or DESEARCH_API_KEY_FILE=/path/to/key
python3 app.py --port 8000
# open http://127.0.0.1:8000
```
Add `--log-dir runs/today` to save each API call (with the key redacted) for debugging.

## Files
- `core.py`: validation, query building, result rows, filter checks, CSV and HTML. No network.
- `app.py`: the HTTP server and the Desearch client.
- `test_core.py`: offline tests, `python3 -m pytest -q`.
- `samples/`: one search page, its CSV, and a filter-by-filter check.

## Cost
Billing is per post returned: 20 posts cost $0.003 in our runs. The cost of each call is in the `X-Desearch-Cost-Usd` response header.

## Known issues
- A search that matches nothing takes about 30 s and is billed as 10 posts.
- `verified` returns blue-check accounts; the legacy `verified` field on those posts is false. Use `blue_verified` if that is what you want.
- `sort=Top` with no date range can return posts from many years ago. Set a start date for recent top posts.
- `count=100` with `sort=Top` returned 48 posts in our test. Latest returned the full 100 but took about 28 s.
- Dates are whole UTC days.
