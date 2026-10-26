# YouTube Creator Finder

Made by Desearch · https://desearch.ai

Describe the YouTube creators you want in plain words, and this Python CLI uses the Desearch API People Search to build a CSV of creators who match. Each row has the channel URL, subscribers, videos, views, last_upload, country, a public email or website when the creator lists one, a fit score with reasons, the top matching video, and a few local quality flags.

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

Before the paid search, the script prints to stderr:

```text
Cost estimate: this search reserves $0.25 (5 creators x $0.05). It bills $0.15 to $0.25 if it finds creators (minimum 3), $0 if it finds none; the unused part of the reservation is returned. Spend cap (--max-cost): $0.25.
Start this paid search? [y/N]
```

`--max-cost` defaults to $0.25, the cost of the default count 5. A reservation above the cap exits 4 before any call or key read. For count 20, use `--count 20 --max-cost 1.00`. Pass `--yes` to skip the prompt; it is required in scripts, cron or CI, otherwise the script exits 1 without spending. Only the creation POST is paid; task status, results, export and cancel are free. `--dry-run` prints the body and estimate without a key or prompt, even above the cap.

Options: `--max-cost` (positive USD reservation cap, default 0.25), `--yes` (start without asking), `--max-inactive-months` (default 12, 0 off), `--count` (5 to 200), `--min-score`, `--min-subscribers`, `--max-subscribers`, `--country` (repeatable), `--require-contact`, `--keyword` / `--exclude-keyword` (repeatable), `--exclude-file` (handles you already contacted, one per line or a previous output CSV), `--idempotency-key` (sending the same key again returns the first search), `--task-id` (fetch an existing search, free), `--dry-run` (print the request body, no key needed).

Exit codes: 0 completed; 1 not confirmed (declined or non-interactive without `--yes`); 2 API, key or input error, or task ended not completed; 3 timeout; 4 estimate above `--max-cost`.

Endpoints used: `POST /desearch/people/search/youtube`, `GET /desearch/people/tasks/{task_id}`, `GET /desearch/people/tasks/{task_id}/results`, `GET /desearch/people/tasks/{task_id}/export?format=csv`.

## Output (in `output/`)

- `<task_id>-creators.csv`: handle, name, channel_url, score, subscribers, videos, views, last_upload, country, email, website, top_video_url, top_video_title, reasons, quality_flags
- `<task_id>-inactive.csv`: same columns, created only when the inactivity filter drops creators
- `<task_id>-export.csv`: the API's own CSV export
- `<task_id>-summary.md`: request, why the search stopped, warnings, cost reserved, billed and refunded
- `<task_id>-calls.jsonl`: every HTTP call with status, timing, cost headers and body (no key)

`last_upload` is the newest parseable `published_at` date among the matching videos Desearch returns, using the timestamp's own date; missing dates are `unknown` and kept with the `upload_date_unknown` flag. It is not the channel's full upload list. An active channel whose matching video is old can be dropped, so check inactive.csv before discarding anyone. `--max-inactive-months` defaults to 12 calendar months before today in Asia/Tbilisi (same day, clamped to month end); 0 turns it off. Dropped creators are excluded from creators.csv and stdout.

Quality flags are computed locally: `upload_date_unknown`, `views_missing`, `few_videos` (1 video or fewer), `no_contact` (no email and no website), `possible_brand_or_store` (name, handle or bio mentions shop, store, official, brand and similar words), `low_score` (under 60). Review the flagged rows before outreach.

## Cost

YouTube Creator Search costs $0.05 per qualified creator, with a minimum of 3 creators ($0.15) when it finds anyone, and $0 when it finds none. It reserves count x $0.05 at the start and returns the unused part when the search ends. Source: https://desearch.ai/pricing, checked 2026-10-26. Observed runs on 2026-10-23 and 2026-10-26 with count 5 reserved and billed $0.25 (POST cost_usd and X-Desearch-Cost-Usd both 0.25). Creators removed by the inactivity filter are still billed.

## Sample

`samples/sample-creators.csv` and `samples/sample-summary.md` contain fictional example creators and example.com URLs.

## Tests

```bash
python -m pytest -q tests
```

The offline tests use recorded responses and make no network calls.
