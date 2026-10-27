# Topic to RSS

Made by Desearch. Built on the [Desearch API](https://desearch.ai).

Turn a topic into an RSS 2.0 feed of dated search results. Undated pages are removed, normalized URLs and titles are deduplicated, and pages are sorted newest first. Descriptions use the first highlight, capped at 500 characters.

## Setup and usage

Use Python 3.10 or newer. No packages are required. Set `DESEARCH_API_KEY` in your environment before running. This is the only environment variable used. Credentials are never stored in the cache.

```sh
cd topic-to-rss
python3 topic_rss.py 'bittensor' -o feed.xml
python3 topic_rss.py 'bittensor' --days 7 --count 20
python3 topic_rss.py 'bittensor' -o feed.xml --no-cache
```

Without `-o`, XML goes to stdout. Cost and latency go to stderr. Example output:

```text
cost_usd=0.01 latency_s=1.234 cache_hit=False
cost_usd=0 latency_s=0.001 cache_hit=True
```

`sample-feed.xml` uses the checked-in fixture and a fixed build date. Its six items demonstrate filtering and deduplication. Sample display text uses plain hyphens and simplified wording.

## Local server

```sh
python3 topic_rss.py --serve --port 8000
curl 'http://127.0.0.1:8000/feed?topic=bittensor'
```

The server binds to localhost. `/feed` returns `application/rss+xml`. Missing, blank, or over-200-character topics return HTTP 400. API failures return HTTP 502. API HTTP errors include the status and are never retried.

## Requests, cache, and cost

Requests use POST `https://api.desearch.ai/search`, balanced mode, highlights, and a date window from today minus `--days` through today. Counts must be 10, 15, or 20. Authorization contains the key directly. Set your own User-Agent header when using plain urllib.

A six-hour cache in `.cache/` beside the script stores result JSON. The SHA-256 key includes the topic and all request parameters, including the date window. Fresh hits reuse results without billing and report cost zero. `--no-cache` bypasses cache reads and writes. Changing parameters or crossing a date boundary can cause another request. Delete `.cache/` to clear results. Simultaneous misses can each send a billable request.

Each uncached refresh at count 20 cost $0.01 in our test on 2026-10-23. Costs may vary; inspect `cost_usd`.

## Limits

- Translation proxy links are unwrapped when possible and dropped when their original URL cannot be recovered.
- Results are the newest dated pages the search returns, not every new article.
- A made-up topic still returns 20 loosely related results and is billed.
- Syndicated copies of one story may appear under different URLs.
- Dates have day precision and appear as midnight UTC in RSS.
- URL deduplication removes trailing slashes, fragments, and `utm_*` parameters and lowercases hosts. Title deduplication ignores case and suffixes starting with ` | ` or ` - `. The first matching result wins before sorting.

## Offline tests

From `topic-to-rss`:

```sh
python3 -m unittest discover -s tests
```

Tests mock the upstream API and exercise HTTP handlers with in-memory requests, without network access.
