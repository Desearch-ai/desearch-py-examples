# Token Narrative Pulse

Made by Desearch ([https://desearch.ai](https://desearch.ai))

A small Python script for crypto analysts. For a token watchlist it pulls the last 24 hours of X posts and finds Reddit threads through Desearch web search. Reddit links are not limited to the last 24 hours. It writes a daily Markdown report, a CSV of X posts and a PNG chart.

What it does:

1. X search (`GET /twitter`, via the `desearch-py` SDK `x_search`) with `sort=Top` and `sort=Latest` for each watchlist term, `start_date` = yesterday (UTC).
2. AI Search (`POST /desearch/ai/search`, via `ai_search`) with `tools=["twitter"]` only, `date_filter=PAST_24_HOURS`, a summary, and a system message asking for a Bullish / Bearish / Neutral breakdown with cited links.
3. Reddit web search (`GET /web`, via `web_search`) in one call. The query combines `site:reddit.com` with the watchlist terms joined with `OR`. Results are filtered to links on reddit.com or its subdomains.
4. Computes mentions per token, unique authors, top 5 posts by engagement, duplicate and template-bot checks, and language mix. X posts older than 24h are dropped client side.
5. Logs latency and cost per call from the `X-Desearch-Cost-Usd` response header and prints the total spend.

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

One run with the default watchlist makes 10 API calls: 8 X searches, 1 web search and 1 AI Search. On 2026-10-26 it took about 45 seconds and cost $0.0191 in total (from the `X-Desearch-Cost-Usd` headers).

## Output (`output/`)

A live run writes these files under `output/`:

- `report-YYYY-MM-DD.md`: the daily report, including Reddit links from web search in a "Reddit threads (web search, site:reddit.com)" section with returned and kept counts
- `posts-YYYY-MM-DD.csv`: one row per unique X post (engagement, author, language, spam flag, token tags)
- `mentions-YYYY-MM-DD.png`: mentions per token and per hour
- `costs-YYYY-MM-DD.csv`: latency and cost per call
- `raw-YYYY-MM-DD.json`: raw API data for replay

## Sample output

The unchanged [`sample-output.md`](sample-output.md) and [`mentions-2026-10-03.png`](mentions-2026-10-03.png) in this folder come from a 2026-10-03 run of the earlier version, which read Reddit through AI Search.

Excerpt:

```
| Token | Mentions | Unique authors |
|---|---|---|
| TAO | 45 | 42 |
| Bittensor | 31 | 29 |
| Desearch (SN22) | 1 | 1 |
| Chutes (SN64) | 3 | 2 |

Posts returned: 94; unique: 85; inside window: 63; outside window (dropped): 22

Total spend this run: $0.0260
```

## Known limits

- Mention counts are sample counts (Top + Latest, `--count` posts per query), not total X volume.
- `start_date` on X search takes a day, not a timestamp, and some returned posts were a couple of hours before that day in UTC, so the script filters to the last 24h itself.
- Web search results carry no post date, so the Reddit links are not limited to the last 24 hours; confirm a thread's date before quoting it. `GET /web` returned 20 results in the 2026-10-26 run. The script makes one call (`start=0`).
- When you call the API without the SDK, send `"streaming": false` to AI Search to get JSON. Without it the response came back as an event stream in testing on 2026-10-03.
