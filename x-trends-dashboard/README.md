# X Trends Dashboard

Made by [Desearch](https://desearch.ai).

See what is trending on X in several places side by side. The script asks the Desearch API for the top 30 trends in each place, marks trends that show up in two or more places, pulls a few of the latest posts for the top shared trends, and writes a static HTML dashboard plus CSV and JSON. Run it again later with `--previous` to see what moved.

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
python3 trends_dashboard.py config.json --label run-1
python3 trends_dashboard.py config.json --label run-2 --no-probes --no-samples \
        --previous evidence/raw-run-1.json
python3 trends_dashboard.py --from-raw path/to/raw.json   # offline rebuild, no API calls
```

`config.json` holds the places (WOEID to name), `count` (30 to 100), how many shared trends get sample posts, and the posts per sample. `--no-probes` skips the three check calls used while testing. `--no-samples` skips the post searches.

A live run writes `output/` and `evidence/raw-<label>.json`. Both folders are gitignored.

| Flag | Default | Meaning |
|---|---|---|
| `config` | `config.json` | places, count, sample size |
| `--label NAME` | `run-1` on a live run | names the output files and the raw file |
| `--from-raw PATH` | | rebuild the dashboard from a saved raw file |
| `--previous PATH` | | earlier raw file, used to mark new trends and rank changes |
| `--no-probes` | off | skip the three check calls |
| `--no-samples` | off | skip latest-post searches for shared trends |
| `--out DIR` | `output` | output folder |

Offline tests (no API calls): `pytest -q test_trends_dashboard.py`.

## How it works

Base URL `https://api.desearch.ai`, header `Authorization: <key>`.

1. `GET /twitter/trends?woeid=<id>&count=30` for each place. The response names the location it answered for; the script compares it with the requested WOEID and leaves any mismatch out of the comparison.
2. Trends are matched across places ignoring case, spaces and a leading `#`, so `#Topic` and `Topic` count as one.
3. For the top 3 shared trends, `GET /twitter?query=<trend>&sort=Latest&count=10` adds sample posts. Authors are shown as Account A, Account B and so on; handles and links are removed.
4. With `--previous`, each row gets its earlier rank or `new`.

A live run also sends three probe calls (a nonsense post search, `count=29`, and an unknown WOEID) unless you pass `--no-probes`. Those probes are stored in the raw file.

## Output

- `output/dashboard-<label>.html`: side-by-side table with shared trends highlighted, shared list, sample posts, changes.
- `output/trends-<label>.csv`: snapshot, woeid, place, woeid_matches, rank, trend, tweet_volume.
- `output/dashboard-<label>.json`: summary, shared trends, sample posts.
- `output/moves-<label>.csv`: rank now vs previous snapshot (only when `--previous` is set).

## Sample (measured 2026-10-16, 11:51 Asia/Tbilisi)

5 places, 150 trend rows, 6 trends shared by 2 or more places. One trend appeared in all 5 places. A second snapshot 45 seconds later had 1 new row and 19 rows at a different rank. A full snapshot with 3 sample searches cost $0.027 by response headers.

See `sample-output.md` and `samples/`. Open `samples/dashboard-run-1.html` in a browser for the side-by-side table.
