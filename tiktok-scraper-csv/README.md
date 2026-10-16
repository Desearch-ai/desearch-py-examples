# TikTok Scraper to CSV

Made by [Desearch](https://desearch.ai).

Turn one keyword and one hashtag into a single clean CSV of public TikToks that the Desearch API returned, plus a short summary (median views, top 10 by engagement rate, posting-hour spread). No scraper to maintain: two REST endpoints and one Python file.

## What it calls
- `POST /desearch/tiktok/search` with `{"query": ..., "count": ...}`
- `GET /desearch/tiktok/hashtag/{tag}?count=...`
- Paging: the responses are plain lists with no cursor field. Passing the running offset as `cursor` (for example `"15"` for page 2) worked in testing.

## Setup
```bash
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # from console.desearch.ai
```
(Or set `DESEARCH_KEY_FILE` to a file that holds the key.)

## Run
```bash
python tiktok_to_csv.py --keyword "skincare routine" --hashtag skincare --count 15 --pages 2
python tiktok_to_csv.py --from-raw evidence/raw-run-1.json   # rebuild CSV offline, no API calls
```
Optional: `--empty-check <made-up-tag>` makes one extra call to see how an empty hashtag behaves.

## Output
`output/tiktok-<hashtag>-<label>.csv`, one row per unique video:

`video_id, link, source (search / hashtag / search+hashtag), creator, caption, create_time_utc, posting_hour_utc, views, likes, comments, shares, saves, engagement_rate, duration_s`

- Creators are labelled "Creator 1", "Creator 2" and so on; handles and links inside captions are masked.
- `engagement_rate` = (likes + comments + shares) / views.
- Rows are deduped by video id across pages and sources.

Sample (2026-10-16 run, "skincare routine" + #skincare, 2 pages of 15 each): 60 rows returned, 59 unique videos, every stat field filled. See `output/tiktok-skincare-run-1-summary.md`.

## Notes
- Check the cost per call on your console before scaling `--count` and `--pages`; every response carries `X-Desearch-Cost-Usd`.
- The hashtag feed is not date sorted; in our run it mixed videos from several years. Filter on `create_time_utc` if you want recent posts only.
