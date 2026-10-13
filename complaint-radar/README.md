# Complaint Radar (Desearch API example)

Made by Desearch. Built with the [Desearch API](https://desearch.ai) (https://desearch.ai).

A small Python CLI you can run each morning. Give it a brand name (plus its support handle and other names if you like). It searches recent public X posts that pair the brand with complaint words, drops duplicates, sorts the posts into complaint themes with keyword rules and writes:

- a Markdown radar: posts per theme, volume by UTC day, the top complaint posts by engagement, the loudest posts per theme, and (optional) a sample of replies under the top posts
- a JSON snapshot with every post, theme, score and Desearch call
- a cost line from the `X-Desearch-Cost-Usd` response headers

It reads public posts only and does not post anything.

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
python complaintradar.py PlayStation --alias PSN --handle AskPlayStation --days 3 --replies 3
```

Output goes to `runs/<timestamp>-<brand>/`:

- `radar.md`: the radar (see `sample-output.md`, from my run on 2026-10-08 09:41 Asia/Tbilisi)
- `snapshot.json`: posts (id, url, author, theme, matched words, score, counts), per-day coverage, a sample of replies, field fill rates and every call with status, latency, items, units and cost
- `raw/`: raw responses (the key is never written; `--no-raw` to skip)

| Flag | Default | Meaning |
|---|---|---|
| `brand` | | brand name to search for |
| `--alias NAME` | | other names for the brand (repeatable) |
| `--handle H` | | the brand's own X handle; its posts are left out (`-from:H`) |
| `--keywords a,b` | 12 complaint words and phrases | complaint words, joined with `OR` |
| `--exclude a,b` | | words to leave out of the search (`-word`), for example off-topic noise |
| `--days N` | 3 | UTC days to cover, today included |
| `--lang xx` | | only posts in this language (`lang` param) |
| `--per-page N` | 20 | posts per call |
| `--pages-per-day N` | 3 | max calls per day |
| `--top N` | 10 | rows in the top posts table |
| `--replies N` | 0 | pull a sample of replies under the top N complaint posts that have replies |
| `--max-spend USD` | 0.10 | stop calling once the run has cost this much |
| `--out DIR` | `runs` | output folder |

Offline tests (no API calls): `pytest -q test_complaintradar.py`.

## How it works

Base URL `https://api.desearch.ai`, header `Authorization: <key>`.

1. The query is built as `(Brand OR alias) (kw1 OR "two words" ...) -from:handle -excluded`. The `query` param takes X search operators; in my tests quotes, `OR`, `-word`, `from:`, `to:`, `lang:`, `min_faves:`, `min_retweets:`, `min_replies:`, `filter:replies`, `#hashtag`, `@mention` and `max_id:` all returned matching posts.
2. One call per UTC day: `GET /twitter?query=<query>&sort=Latest&start_date=<day>T00:00:00Z&end_date=<next day>T00:00:00Z&count=20`. With `sort=Latest`, posts come back newest first (1537 of 1537 adjacent pairs in my probes).
3. If a page comes back full, the next page adds `max_id:<oldest id - 1>` to the query, up to `--pages-per-day` pages. The radar shows how far back each day was covered.
4. Optional: `GET /twitter/replies/post?post_id=<id>&count=20` under the top complaint posts gives a sample of replies.

Locally: reposts and the brand's own posts are dropped, then repeated ids and copy-paste texts. Each post gets the first matching theme in this order: outage, account, billing, bug, support, feature request, else other. A few phrases that use complaint words in another sense ("broken the record", "bug fixes") are ignored before matching. Engagement score = likes + 2 x replies + reposts + quotes + bookmarks. Keyword rules are simple, so skim the top posts: song titles and product names that contain a complaint word can land in a theme, and `--exclude` helps with those.

## Cost

Measured on 2026-10-08 (Asia/Tbilisi) from the `X-Desearch-Cost-Usd` response header:

- `python complaintradar.py PlayStation --alias PSN --handle AskPlayStation --days 3 --replies 3`: 10 calls, 187 billed units, $0.02805 (7 search calls returning 127 posts, 3 replies calls returning 20 replies each)

Each call's cost is in `snapshot.json` and on stderr. A full page of 20 posts cost $0.003 in my runs.

## Known issues

Measured on 2026-10-08 with `GET /twitter`; details and evidence are in `report.md`.

- One broad call can leave out posts inside its own time span. `query=Spotify broken&sort=Latest&count=50` (no dates) and `&count=100&start_date=2026-10-04` both left out the same 16 posts from 2026-10-06 08:13 to 18:49 UTC that calls bounded with `end_date=2026-10-06` returned. Day windows with `count=20` left out none in my checks, which is why the tool works one UTC day at a time.
- Date-only values are applied about 1 to 2 hours before midnight UTC: `start_date=2026-10-08` returned posts from 2026-10-07 22:09 UTC, and `end_date=2026-10-06` ended at 2026-10-06 21:59:56 UTC. `start_date` with a full ISO time (`2026-10-08T00:00:00Z`) or Unix seconds is applied to the second, so the tool sends ISO times.
- `end_date` uses only its date, as an exclusive bound in UTC: `end_date=2026-10-06T23:00:00Z` ended at 2026-10-05 23:59:57 UTC. Ranges inside one day are not possible with `end_date`; the tool only uses it at midnight.
- `start_date` values `2026/10/05`, `20261008`, `2026-10-05 12:00:00`, `2026-10-05T12:00:00+04:00`, Unix milliseconds, `yesterday` and `2026-13-45` returned HTTP 200 with an empty list. `10-08-2026` was read as 10 August. Use `YYYY-MM-DDTHH:MM:SSZ`.
- The response is a plain JSON array with no cursor, and a `cursor` param is ignored. The tool pages with `max_id:` in `query`; each next page repeated the previous page's oldest post once (22 of 22 page turns across five runs), and the tool drops it by id.
- `verified=true` returned the same posts as `blue_verified=true`, and `user.verified` was false on all 692 distinct posts I pulled.
- `sort=Top` (the default) returned posts from 2014 to 2026 for `Spotify broken`, and two identical Top calls shared 21 of 50 ids. The tool always sends `sort=Latest`; two identical Latest calls returned the same ids in the same order (50 of 50, 100 of 100).
- `view_count` was null on 54 of 692 posts, 51 of them created before 2023.
- Latency in my runs: `GET /twitter` 1.9 to 29.7 s per call (median 2.7 s); calls that found no posts took 7.8 to 8.3 s; `GET /twitter/replies/post` 3.9 to 15.9 s.
