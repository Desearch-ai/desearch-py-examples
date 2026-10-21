# AI News Today Board

Made by [Desearch](https://desearch.ai).

A small Python script for analysts and founders who want one list a day of what's new in AI, with links, instead of scrolling feeds. It runs a fixed plan of five AI sub-queries against the Desearch API, keeps the latest X posts above a like threshold and pages from a short list of tech news sites, dedupes them, tags each item with its sub-query and remembers what you have already seen.

The board shows the AI posts and pages Desearch returned for that run. It is not every AI story of the day.

## What you get

- `ai-news-YYYY-MM-DD.csv`: one row per item (source, sub-query tag, text or title as returned, link, site, time, likes, reposts, replies, engagement, new or seen, a rough keyword on-topic flag)
- `ai-news-YYYY-MM-DD.md`: the top 15 X posts by engagement (likes + reposts + replies) and recent coverage from the news sites, newest first
- `seen-urls.txt`: links already shown; a live run adds the new ones, so tomorrow's board marks only fresh items as new
- the raw responses as JSON, so you can rebuild the board offline

Authors are shown as "a user". Posts that mention an account are left out, so every quote stays exactly as returned.

## Setup

```bash
pip install -r requirements.txt
```

Set `DESEARCH_API_KEY` in your environment. The key is read only at runtime. The legacy `--key-file` flag is accepted but ignored.

## Run

```bash
python ai_news_board.py --out output
```

Offline, from the saved sample (no key, no cost):

```bash
python ai_news_board.py --from-raw samples/sample-raw.json --out output/sample
```

Options: `--count` X posts per sub-query (default 30), `--min-likes` (default 20), `--max-age-hours` (default 24), `--web-count` pages per sub-query (default 10), `--page-days` (default 7), `--sites` to override the news sites for one run, `--seen-file`, `--raw-out`. Edit `QUERY_PLAN` in the script to change the sub-queries.

## Choosing the news sites

The web search is limited to the sites in `NEWS_SITES`, a list near the top of `ai_news_board.py`. Edit that list to use your own sites, or pass `--sites site-one.example site-two.example` to override it for one run.

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

## Live demo

Run `python app.py` and open `http://127.0.0.1:8000`. Set `DEMO_LIVE=0` to view the saved sample without a key. See [DEPLOY.md](DEPLOY.md) for Vercel setup and environment settings.

The live board makes 10 parallel calls per build and caches results for six hours. Cost is read per call from the response header, then body `cost_usd`, with a configurable $0.005 fallback. The demo filters replies, a small profanity/NSFW word list and posts without links that have very low engagement. Some failed searches are marked as a partial result.
