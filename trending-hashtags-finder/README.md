# Trending Hashtags Finder

Made by Desearch | https://desearch.ai

A small Python CLI that asks the Desearch API which topics are trending on X in the countries you choose, keeps only the hashtags, then pulls the latest posts for the top ones so you can see whether people are actually using them right now, in which language, and which other hashtags travel with them.

It answers one question: "Which hashtag should I post with today, and is it still active?"

## What it does

1. `GET /twitter/trends` once per country (WOEID), 30 to 100 trends each.
2. Keeps trends whose name starts with `#`, merges them across countries, and ranks hashtags that trend in more than one country first, then by best rank.
3. For the top N hashtags, `GET /twitter` with `sort=Latest`, `count` and a `start_date`. `start_date` is a whole UTC day, so the tool also drops posts older than `--hours` in code.
4. Writes `shortlist.md`, `shortlist.csv` and `summary.json` with: countries and rank, sample size, distinct accounts, minutes since the newest post, posts per hour in the sample, median likes, main language, co-used hashtags, two example post links and a plain verdict (use, cooling, skip).

Standard library only for the CLI. Logic lives in `core.py`, which never touches the network and is covered by offline tests.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # pytest, for the tests only
export DESEARCH_API_KEY=...       # your key from console.desearch.ai
```

The key is read from the `DESEARCH_API_KEY` environment variable (or from a file path in `DESEARCH_API_KEY_FILE`). It is sent as the `Authorization` header and is never written to disk: raw responses are saved with `Authorization: <redacted>` and the client refuses to write any file that contains the key.

## Run

```bash
python find_hashtags.py --countries US=23424977,GB=23424975,IN=23424848,JP=23424856,Worldwide=1 --top 6 --sample 20 --hours 6
```

| Flag | Default | Meaning |
|---|---|---|
| `--countries` | `US=23424977` | `LABEL=WOEID` pairs. Worldwide is `1`. |
| `--trends` | 50 | Trends per country (the API accepts 30 to 100). |
| `--top` | 6 | Hashtags to check with X search. |
| `--sample` | 20 | Latest posts per hashtag. |
| `--hours` | 6 | Only count posts from the last N hours. |
| `--out` | `runs` | Output folder; each run gets a timestamped subfolder with `raw/` and `calls.jsonl`. |
| `--check-empty TAG` | off | Also search one made-up hashtag, to see what an empty result returns and costs. |

Tests (offline):

```bash
python -m pytest -q
```

## Sample output

See `sample-output.md` and `samples/` (5 countries, 2026-10-16 14:34 Asia/Tbilisi).

## Cost

Each call returns its price in the `X-Desearch-Cost-Usd` response header and the CLI prints a running total. The sample run (5 trend lists of 50, 6 hashtag searches of up to 20 posts, 1 empty check) came to $0.0539 in header totals.

## Known issues

- A location X does not publish trends for returns HTTP 422 `WOEID is not supported` (for example Georgia, 23424823). Pick a nearby country or Worldwide.
- `count` below 30 on `/twitter/trends` returns HTTP 422.
- A search for a hashtag nobody uses can take about 30 s before it returns an empty list, and it is billed.
- Only a handful of trends are hashtags (5 of 50 per country in the sample run), so asking for 100 trends does not always give you more hashtags.
