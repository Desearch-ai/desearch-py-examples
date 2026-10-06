# TikTok Trend Board

Made by Desearch ([https://desearch.ai](https://desearch.ai))

A small Python script for analysts that shows what is moving on TikTok. It pulls the TikTok trending feed for two regions (US and GB by default) through the Desearch API, counts which hashtags show up across those posts, drills into the top 3 topical hashtags, reads comments on the most-played post, and writes a dated board: Markdown, CSVs and a top-hashtag PNG chart.

What it does:

1. Trending feed (`GET /desearch/tiktok/trending?region=US&count=30`) for each region.
2. Hashtag posts (`GET /desearch/tiktok/hashtag/{tag}?count=20`, tag in the path without `#`) for the top 3 topical hashtags. Generic reach tags such as #fyp are counted but not drilled into.
3. Comments (`GET /desearch/tiktok/comments/{video_id}?count=20`) on the most-played trending post.
4. Computes hashtag counts per region with summed plays, likes and shares, post age, like rate, duplicates and field coverage, and logs status, latency, items returned and cost per call from the `X-Desearch-*` response headers.

The official Python SDK (desearch-py 1.2.1) has no TikTok methods yet, so the script calls the REST API directly with `requests`.

## Setup

Run everything from this folder (`tiktok-trend-board/`). Python 3.10+.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Environment variable (by name only, never commit it):

- `DESEARCH_API_KEY`: your API key from console.desearch.ai (API Keys page).

## Run

```bash
export DESEARCH_API_KEY=...   # paste your key, or load it from your secret store
python tiktok_board.py        # writes to ./output
```

Options: `--regions US GB`, `--count 30` (trending posts per call, 1 to 100), `--pulls 1` (trending calls per region; each call returns a different sample), `--tag-count 20`, `--top-tags 3`, `--no-comments`, `--out output`, `--from-raw output/raw-YYYY-MM-DD.json` (re-run the analysis on a saved pull with no API calls).

One run with the defaults on 2026-10-05 made 6 API calls, took about 27 seconds and returned 107 items. Billing is per item returned; the script prints the exact total from the `X-Desearch-Cost-Usd` headers.

## Output (`output/`)

- `board-YYYY-MM-DD.md`: the board (feed summary, top hashtags and posts per region, hashtag drill-down, comments, data quality)
- `posts-YYYY-MM-DD.csv`: every trending and hashtag post with plays, likes, shares, saves, age and parsed hashtags
- `hashtags-YYYY-MM-DD.csv`: hashtag counts per region with summed plays, likes and shares
- `comments-YYYY-MM-DD.csv`: comments on the top post
- `top-hashtags-YYYY-MM-DD.png`: top hashtags per region (generic reach tags in grey)
- `costs-YYYY-MM-DD.csv`: status, latency, items returned, billed units and cost per call
- `raw-YYYY-MM-DD.json`: raw API data for `--from-raw`

## Sample output (run of 2026-10-05, excerpt)

Full board: [sample-output.md](sample-output.md), chart: [top-hashtags-2026-10-05.png](top-hashtags-2026-10-05.png).

```
| Region | Posts returned | Unique posts | Duplicates | Median age (days) | Newest | Oldest | Total plays (unique) | Median like rate |
| US | 16 | 14 | 2 | 31 | 7.5 d | 68 d (2026-07-28) | 62,500,895 | 12.4% |
| GB | 16 | 10 | 6 | 53 | 0.1 d | 76 d (2026-07-20) | 105,600,235 | 11.9% |

| Hashtag | Posts returned | Unique | Carry the tag in caption | Median age (days) | Oldest |
| #footballtiktok | 20 | 20 | 20/20 | 0 | 96 d |
| #argentinavsspain | 20 | 20 | 20/20 | 1 | 8 d |

- `hashtags[]` field filled on 0 of 24 unique trending posts; hashtags above are parsed from captions.
- Sounds: `music.title` present on 0 of 24 unique trending posts (the field is not returned, so sounds cannot be ranked).
```

The saved sample was rebuilt with `--from-raw` from that run, without its cost log.

## Known limits

- `hashtags[]` came back empty on every trending post in testing on 2026-10-05, so hashtags are parsed from the caption text.
- `music` was not returned on 2026-10-05, so the board cannot rank sounds.
- `createTime` is Unix seconds (an integer), not an ISO string as shown in the docs.
- The trending feed is a sample, not a full ranking. On 2026-10-05 back-to-back calls for the same region shared 0 to 2 posts, a response returned fewer posts than `count`, and one response could repeat a post. The script removes repeats; use `--pulls` for a bigger sample.
- `region` must be exactly 2 characters and `count` 1 to 100, otherwise HTTP 422. An unknown 2-letter region such as `ZZ` returns an empty list with HTTP 200, not an error.
- No TikTok methods in desearch-py 1.2.1; the script uses plain HTTP.
