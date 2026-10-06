# Token Narrative Pulse

Made by Desearch ([https://desearch.ai](https://desearch.ai))

A small Python script for crypto analysts. For a token watchlist it pulls the last 24 hours of X posts and Reddit threads through the Desearch API, then writes a daily Markdown report, a CSV of posts and a PNG chart.

What it does:

1. X search (`GET /twitter`, via the `desearch-py` SDK `x_search`) with `sort=Top` and `sort=Latest` for each watchlist term, `start_date` = yesterday (UTC).
2. AI Search (`POST /desearch/ai/search`, via `ai_search`) with `tools=["reddit"]` and `tools=["twitter","reddit"]`, `date_filter=PAST_24_HOURS`, a summary, and a system message asking for a Bullish / Bearish / Neutral breakdown with cited links.
3. Computes mentions per token, unique authors, top 5 posts by engagement, duplicate and template-bot checks, and language mix. Posts older than 24h are dropped client side.
4. Logs latency and cost per call from the `X-Desearch-Cost-Usd` response header and prints the total spend.

Default watchlist (edit `WATCHLIST` in `pulse.py`): `$TAO`, `Bittensor`, `Desearch` (Subnet 22), `Chutes SN64`.

## Setup

Run the commands in this README from the `token-narrative-pulse` folder.

Python 3.10+.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Environment variable (by name only, never commit it):

- `DESEARCH_API_KEY`: your API key from console.desearch.ai (API Keys page).

## Run

```bash
export DESEARCH_API_KEY=...   # paste your key, or load it from your secret store
python pulse.py               # writes a fresh run under ./output
```

Options: `--count 20` (posts per X query), `--out output`, `--from-raw output/raw-YYYY-MM-DD.json` (re-run the analysis on a saved pull with no API calls).

One run with the default watchlist makes 10 API calls. On 2026-10-03 it took about 75 seconds and cost $0.026 in total (from the `X-Desearch-Cost-Usd` headers).

## Output (`output/`)

A live run writes these files under `output/`:

- `report-YYYY-MM-DD.md`: the daily report
- `posts-YYYY-MM-DD.csv`: one row per unique X post (engagement, author, language, spam flag, token tags)
- `mentions-YYYY-MM-DD.png`: mentions per token and per hour
- `costs-YYYY-MM-DD.csv`: latency and cost per call
- `raw-YYYY-MM-DD.json`: raw API data for replay

## Sample output

The saved 2026-10-03 run ships in this folder as [`sample-output.md`](sample-output.md). The chart for that run is [`mentions-2026-10-03.png`](mentions-2026-10-03.png), next to the sample (not under `output/`).

Excerpt:

```
| Token | Mentions | Unique authors |
|---|---|---|
| TAO | 45 | 42 |
| Bittensor | 31 | 29 |
| Desearch (SN22) | 1 | 1 |
| Chutes (SN64) | 3 | 2 |

Posts returned: 94; unique: 85; inside window: 63; outside window (dropped): 22

- Template groups (2+ authors, same closing text): 1 groups, 8 posts
  - 8 posts by @ParkerBenS9, @JustinMorganQ8, @EthanParker672, ...: "...$RENDER, $TAO , $FET , $NEAR"

| x_search '$TAO' sort=Top | 6.34 | 0.003 | 20 |
| ai_search tools=['twitter', 'reddit'] | 9.6 | 0.004 | 10 |
Total spend this run: $0.0260
```

## Known limits

- Mention counts are sample counts (Top + Latest, `--count` posts per query), not total X volume.
- `start_date` on X search takes a day, not a timestamp, and some returned posts were a couple of hours before that day in UTC, so the script filters to the last 24h itself.
- Reddit links from AI Search carry no post date, and in testing on 2026-10-03 many were older than the 24h window. The report flags this; confirm thread dates before quoting them.
- When you call the API without the SDK, send `"streaming": false` to AI Search to get JSON. Without it the response came back as an event stream in testing on 2026-10-03.
