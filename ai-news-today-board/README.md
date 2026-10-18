# AI News Today Board

Made by [Desearch](https://desearch.ai).

A small Python script for analysts and founders who want one list a day of what's new in AI, with links, instead of scrolling feeds. It runs a fixed plan of five AI sub-queries against the Desearch API, keeps the latest X posts above a like threshold and pages from a short list of tech news sites, dedupes them, tags each item with its sub-query and remembers what you have already seen.

The board shows the AI posts and pages Desearch returned for that run. It is not every AI story of the day.

## What you get

- `ai-news-YYYY-MM-DD.csv`: one row per item (source, sub-query tag, text or title as returned, link, site, time, likes, reposts, replies, engagement, new or seen, a rough keyword on-topic flag)
- `ai-news-YYYY-MM-DD.md`: the top 15 X posts by engagement (likes + reposts + replies) and the news pages, newest first
- `seen-urls.txt`: links already shown; a live run adds the new ones, so tomorrow's board marks only fresh items as new
- the raw responses as JSON, so you can rebuild the board offline

Authors are shown as "a user". Posts that mention an account are left out, so every quote stays exactly as returned.

## Setup

```bash
pip install -r requirements.txt
# Put your Desearch API key (from console.desearch.ai) in a key file, one line:
printf '%s' 'YOUR_KEY' > ~/.desearch_api_key && chmod 600 ~/.desearch_api_key
```

The script reads the key only from a key file (`--key-file PATH`, default `~/.desearch_api_key`). It does not read environment variables.

## Run

```bash
python ai_news_board.py --key-file ~/.desearch_api_key --out output
```

Offline, from the saved sample (no key, no cost):

```bash
python ai_news_board.py --from-raw samples/sample-raw.json --out output/sample
```

Options: `--count` X posts per sub-query (default 30), `--min-likes` (default 20), `--max-age-hours` (default 24), `--web-count` pages per sub-query (default 10), `--page-days` (default 7), `--sites` the news sites for the web search, `--seen-file`, `--raw-out`. Edit `QUERY_PLAN` in the script to change the sub-queries.

## Endpoints

- `GET /twitter` with `query`, `sort=Latest`, `count`, `min_likes`, through the desearch-py SDK (`x_search`). Pass `min_likes` as a string; leave the yes/no filters out.
- `POST /desearch/ai/search` with `tools: ["web"]`, `include_domains` and `result_type: "ONLY_LINKS"`. The SDK's `ai_search` (desearch-py 1.2.1, checked 2026-10-18) has no `include_domains` argument, so the script calls this endpoint over REST with `requests`.

One run is 10 calls (5 sub-queries x 2 sources). Each response reports its cost in the `X-Desearch-Cost-Usd` header (the SDK exposes it with `include_metadata=True`), and the script prints the total.

## Notes from testing (2026-10-18)

- Every call returned the number of items asked for (30 posts, 10 pages).
- `sort=Latest` with `min_likes` returned posts going back several days, so the script keeps only the last 24 hours (`--max-age-hours`).
- Every post respected `min_likes`.
- Every web page came from the `include_domains` list.
- About two thirds of the web results had a `published_date`, and the time window did not narrow them to recent pages: many were weeks or months old. The script uses `published_date`, falls back to a date in the URL, drops pages older than 7 days and keeps undated pages, marked "no date".
- A broad query like the raw phrase "ai news today" brought back mostly off-topic posts. Specific sub-queries did much better, so the board uses a query plan.
- Some posts are only a link with no text; the script leaves them out.

## Sample output

`samples/sample-ai-news.md` and `samples/sample-ai-news.csv` are the board rebuilt from `samples/sample-raw.json` (a run on 2026-10-18): 15 top posts with their engagement, time and link, then the news pages with site, date and link. The full live run log is in `samples/live-run-2026-10-18.md`.

## Tests

```bash
python -m unittest discover -s tests
```
