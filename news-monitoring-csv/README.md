# News Monitoring to CSV

Made by [Desearch](https://desearch.ai).

A small Python script for analysts who follow a few news topics. For each topic it calls the Desearch API web search (`GET /web`) and X search (`GET /twitter`, `sort=Latest`, `start_date`), then appends only items it has not seen before to one CSV. A seen-URL file keeps the next run from repeating rows.

## Setup
```
pip install -r requirements.txt
```
Create an API key at console.desearch.ai and save it in a key file (default `~/.saba/desearch_api_key`, or pass `--key-file`). The script reads the key from that file only. Set `EXPECTED_KEY_PREFIX` in the script to the first 8 hex characters of your key's sha256 (or to `""`) so it refuses to run with the wrong key.

## Run
```
python news_monitor.py --topics "open source llm release" "ai chip export controls"
```
Options: `--since YYYY-MM-DD` (start date for X posts, default yesterday), `--count` (X posts per topic, default 30), `--csv` (default `output/news.csv`), `--seen` (default `output/seen.json`).

Run it from cron (for example every 2 hours) and the CSV grows with new items only.

Offline, no API calls:
```
python news_monitor.py --from-raw samples/raw-sample.json
```

## Output columns
`topic, kind (web or post), source_domain, title, url, published_date, snippet, first_seen`

- `published_date` is filled for X posts (ISO, UTC). Web results came back without a date in testing, so that column is empty for web rows and `first_seen` is the time this script first saw the item.
- Duplicates are removed by normalized URL, within a run and across runs.

## What to expect
- Web results are the pages Desearch returned for the topic at run time. They mix fresh articles with older guides and reference pages, so add words like "news" or a month to the topic if you want fresher pages.
- X results are the latest posts Desearch returned since `start_date`, up to `count`. They are a sample, not every post.
- Blank topics are skipped before any call.
