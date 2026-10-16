# Social Listening Report

Made by [Desearch](https://desearch.ai).

Pick one brand or topic. The script pulls the public posts Desearch returned on X for the last 7 days and three pages of web results, then writes `output/mentions.csv` and `output/report.md` with posts by day, top posts by engagement, and top web domains. Authors are shown as Account A, Account B and so on.

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

The key is sent only in the `Authorization` header and is never written to output.

## Run

```bash
python3 social_listening.py config.json
python3 social_listening.py --from-raw path/to/raw.json   # offline rebuild, no API calls
```

`config.json` holds the brand name, the X query, `x_count`, the web query and the web `start` values.

A live run writes `output/` and `evidence/raw-<date>.json`. Both folders are gitignored.

| Flag | Default | Meaning |
|---|---|---|
| `config` | `config.json` | brand, queries and page starts |
| `--from-raw PATH` | | rebuild the sheet from a saved raw file |
| `--out DIR` | `output` | output folder |

Offline tests (no API calls): `pytest -q test_social_listening.py`.

## How it works

Base URL `https://api.desearch.ai`, header `Authorization: <key>`.

1. `GET /twitter?query=(duolingo OR "duo owl") lang:en&sort=Latest&count=50&start_date=<7 days ago>` and the same with `sort=Top&count=20`. Wrap OR terms in parentheses so they group with other filters.
2. `GET /web?query=duolingo&start=0`, then `start=10` and `start=20`. URLs are de-duplicated across pages.
3. Each row is marked on topic when the brand word appears in the post text, or in the page title, snippet or URL.

A live run also sends four probe calls (a nonsense X query, a nonsense web query, a blank X query and a blank web query) and stores them in the raw file.

## Sample output (2026-10-15, brand: Duolingo)

- X: 70 posts returned (50 Latest, 20 Top), 69 unique, 68 name the brand in the text.
- Web: 48 results over 3 pages, 38 unique URLs, all 38 name the brand. 27 were the brand's own pages or app store listings, 11 were third-party threads, videos and articles.
- The 50 Latest posts covered about 2.5 hours of posting, so for a busy brand run it more often or use Top for the week view.

See `sample-output.md` and `samples/`. The full `output/report.md` and `output/mentions.csv` are written on each run.
