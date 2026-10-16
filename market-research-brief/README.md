# Market Research Brief

Made by [Desearch](https://desearch.ai).

Pick one market. The script pulls several pages of web results, removes repeated URLs, sets aside store and manufacturer pages, reads the text of the top third-party pages, adds a small sample of recent X posts, and writes `output/brief.md`: brands named most often, recurring buyer concerns, price mentions, and the list of sources it read.

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
python3 market_brief.py config.json
python3 market_brief.py --from-raw path/to/raw.json   # offline rebuild, no API calls
```

`config.json` holds the market name, the web query, the `start` values, the brand list, the store and brand domains to set aside, the concern terms and `max_extract`.

A live run writes `output/` and `evidence/raw-<date>.json`. Both folders are gitignored.

| Flag | Default | Meaning |
|---|---|---|
| `config` | `config.json` | market, queries, brands and domains |
| `--from-raw PATH` | | rebuild the brief from a saved raw file |
| `--out DIR` | `output` | output folder |

Offline tests (no API calls): `pytest -q test_market_brief.py`.

## How it works

Base URL `https://api.desearch.ai`, header `Authorization: <key>`.

1. `GET /web?query=best home espresso machine` with `start=0`, `10`, `20` and `30`. Pages overlap, so URLs are de-duplicated.
2. URLs on store or brand domains (from `config.json`) are set aside; the first 12 others go to `GET /web/extract?url=...&format=text&js=false`.
3. Pages with under 200 characters of text are skipped. Some pages return no text at all; the script just moves on.
4. `GET /twitter?query=("espresso machine" OR "espresso maker") lang:en&sort=Latest&count=20` adds a few recent posts.
5. Counts brand names and concern terms per page, and collects dollar amounts from page text.

A live run also sends two probe calls (extract on a bad URL, and a web search with an empty query) and stores them in the raw file.

## Sample output (2026-10-15)

- 79 web results returned, 44 unique URLs
- 12 pages requested, 8 with usable text
- Brands named on the most pages: Breville (4), Gaggia (3), Bambino (3)

Full brief: `sample-output.md`. Paging, extract status and a few result rows are in `samples/`. Each run writes `output/brief.md`, `output/web-pages.csv`, `output/web-paging.csv` and `output/extracts.csv`.
