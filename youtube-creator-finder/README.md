# YouTube Creator Finder

Made by Desearch · https://desearch.ai

Describe the YouTube creators you want in plain words, and this Python CLI uses the Desearch API People Search to build a CSV of creators who match. Each row has the channel URL, subscribers, videos, views, country, a public email or website when the creator lists one, a fit score with reasons, the top matching video, and a few local quality flags.

You get creators matching your description, with public contacts when the creator lists one. It is not a full list of every creator, and emails are not verified.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# put your key from console.desearch.ai in a file only you can read
printf '%s' 'YOUR_KEY' > ~/.desearch_api_key && chmod 600 ~/.desearch_api_key
```

The key is read only from `--key-file` (default `~/.desearch_api_key`, or the path in `DESEARCH_KEY_FILE`). It is never printed or written to the logs.

## Run

```bash
python youtube_creator_finder.py \
  --query "Independent YouTube creators who review mechanical keyboards" \
  --count 5 --min-subscribers 5000 \
  --exclude-keyword shop --exclude-keyword store \
  --idempotency-key my-keyboards-run-1
```

Options: `--count` (5 to 200), `--min-score`, `--min-subscribers`, `--max-subscribers`, `--country` (repeatable), `--require-contact`, `--keyword` / `--exclude-keyword` (repeatable), `--exclude-file` (handles you already contacted, one per line or a previous output CSV), `--idempotency-key` (sending the same key again returns the first search), `--task-id` (fetch an existing search, free), `--dry-run` (print the request body, no key needed).

Endpoints used: `POST /desearch/people/search/youtube`, `GET /desearch/people/tasks/{task_id}`, `GET /desearch/people/tasks/{task_id}/results`, `GET /desearch/people/tasks/{task_id}/export?format=csv`.

## Output (in `output/`)

- `<task_id>-creators.csv`: handle, name, channel_url, score, subscribers, videos, views, country, email, website, top_video_url, top_video_title, reasons, quality_flags
- `<task_id>-export.csv`: the API's own CSV export
- `<task_id>-summary.md`: request, why the search stopped, warnings, cost reserved, billed and refunded
- `<task_id>-calls.jsonl`: every HTTP call with status, timing, cost headers and body (no key)

Quality flags are computed locally: `views_missing`, `few_videos` (1 video or fewer), `no_contact` (no email and no website), `possible_brand_or_store` (name, handle or bio mentions shop, store, official, brand and similar words), `low_score` (under 60). Review the flagged rows before outreach.

## Cost

The search reserves `count` creators at the route price when it starts and bills only the creators it delivers. In my run on 2026-10-23, `count` 5 reserved and billed $0.25 (5 creators, about 2.5 minutes). A search that finds nobody costs nothing. Current prices: https://desearch.ai/pricing.

## Sample

`samples/sample-creators.csv` and `samples/sample-summary.md` contain fictional example creators and example.com URLs.

## Tests

```bash
python -m pytest -q tests
```

The offline tests use recorded responses and make no network calls.
