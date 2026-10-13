# Reply Ledger (Desearch API example)

Made by Desearch. Built with the [Desearch API](https://desearch.ai) (https://desearch.ai).

A small Python CLI. Give it a public X handle. It pulls the account's recent public posts and replies from the Desearch API and writes a Markdown reply ledger:

- replies vs original posts vs thread replies vs reposts (median likes, views, bookmarks)
- who the account replies to most
- reply volume by day
- the top 10 replies by engagement, with the parent post they answered
- busy own posts with no reply from the account in the pulled sample
- field fill rates and a cost line

It reads public posts and replies only. It does not post anything and does not show impressions or profile visits.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai
```

Environment variables (names only):

| Variable | Meaning |
|---|---|
| `DESEARCH_API_KEY` | your API key |
| `DESEARCH_API_KEY_FILE` | optional: path to a file holding the key, used when `DESEARCH_API_KEY` is not set |

## Run

```bash
python replyledger.py NASA --days 30
```

Output goes to `runs/<timestamp>-<handle>/`:

- `ledger.md`: the reply ledger (see `sample-output.md`, from my run on 2026-10-07)
- `snapshot.json`: every item in the window (kind, engagement score, counts, ids, urls), the parent posts, and every Desearch call with status, latency, items, units and cost
- `raw/`: raw responses (the key is never written; `--no-raw` to skip)

| Flag | Default | Meaning |
|---|---|---|
| `handle` | | X handle, with or without `@` |
| `--days N` | 30 | look-back window (UTC days) |
| `--pages N` | 5 | max timeline pages of about 20 posts |
| `--parents N` | 5 | parent posts to look up for the top replies (0 = off) |
| `--max-spend USD` | 0.25 | stop calling once the run has cost this much |
| `--out DIR` | `runs` | output folder |

Offline tests (no API calls): `pytest -q test_replyledger.py`.

## How it works

Base URL `https://api.desearch.ai`, header `Authorization: <key>`.

1. `GET /twitter/user/posts?username=<handle>` then `&cursor=<next_cursor>`: the timeline, newest first, about 20 posts per page. The tool stops when a page reaches past the window.
2. `GET /twitter/replies?user=<handle>&count=100&query=since:<YYYY-MM-DD>`: the account's replies in the window. `query` takes X search operators; `since:` keeps results inside the window.
3. `GET /twitter/post?id=<in_reply_to_status_id>`: the parent post for the top replies.

Items are merged by id, kept only if authored by the handle and created inside the window, then split by `is_retweet`, `in_reply_to_status_id` and `in_reply_to_screen_name` (a reply to the handle itself counts as a thread reply). Engagement score = likes + 2 x replies + reposts + quotes + bookmarks. "Busy threads" are own original posts with replies where no pulled item is a reply from the account in the same `conversation_id`.

## Cost

Measured on 2026-10-07 (Asia/Tbilisi) from the `X-Desearch-Cost-Usd` response header:

- `python replyledger.py NASA --days 30`: 11 calls, 121 billed units, $0.01815
- `python replyledger.py SpotifyCares --days 14 --pages 3`: 7 calls, 45 billed units, $0.00675

Each call's cost is in `snapshot.json` and on stderr.

## Known issues

Measured on 2026-10-07; details and evidence are in `report.md`.

- `GET /twitter/replies?user=<handle>&count=100&query=since:<date>` returned 10 to 21 items per call in my runs, fewer than `count`, and the endpoint has no cursor. Treat the ledger as a sample of recent replies.
- Two identical `GET /twitter/replies` calls returned different id sets (for `user=NASA&count=100`: 40 of 100 ids shared). Runs of the ledger can differ slightly.
- Without a `query`, `GET /twitter/replies?user=<handle>&count=100` returned items spread over many years (median 2015 for `NASA`), so the tool always sends `since:`.
- For a handle that does not exist, `GET /twitter/user/posts` returns 404 at $0, while `GET /twitter/replies?count=100` returns 200 with an empty list and bills 10 units ($0.0015). The tool calls `/twitter/user/posts` first and stops on 404.
- `GET /twitter/post?id=` returned 503 for some parent ids (1 of 5 per run), at $0. The ledger then shows the parent as a link.
- `view_count` is null on posts from before 2023.
- `GET /twitter/replies?count=100` took 6.5 to 32.2 s per call in my runs.
