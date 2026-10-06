# City Trends Pulse

Made by Desearch ([https://desearch.ai](https://desearch.ai))

A small Python script for analysts that answers "what's moving where on X right now". For a list of places (by WOEID) it pulls the current X trends through the Desearch API, fetches the top posts for the leading trends, and writes a Markdown snapshot, CSVs and a PNG chart: which trends are global and which are local, whether the top posts are actually about the trend, how fresh they are, and what language they are in.

What it does:

1. X trends (`GET /twitter/trends`, via the `desearch-py` SDK `x_trends`) with `count=30` for each place.
2. X search (`GET /twitter`, via `x_search`) with `sort=Top` and `start_date` = yesterday (UTC) for each unique trend query among the top trends of every place. The top 3 posts by engagement are kept.
3. Replies (`GET /twitter/replies/post`, via `x_post_replies`) for the #1 post of each place.
4. Computes shared vs local trends (Jaccard overlap), relevance (does the post mention the trend), freshness, language mix, duplicate checks, and logs latency and cost per call from the `X-Desearch-Cost-Usd` response header.

Default places (edit `LOCATIONS` in `trends.py`): Worldwide (1), United States (23424977), United Kingdom (23424975), New York (2459115), London (44418), Istanbul (2344116) and Georgia (23424823). Georgia is not in the WOEID list linked from the Desearch docs; it is kept to show how an unsupported place is detected and skipped.

## Setup

Run everything from this folder (`city-trends-pulse/`). Python 3.10+.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Environment variable (by name only, never commit it):

- `DESEARCH_API_KEY`: your API key from console.desearch.ai (API Keys page).

## Run

```bash
export DESEARCH_API_KEY=...   # paste your key, or load it from your secret store
python trends.py              # writes to ./output
```

Options: `--top 4` (trends per place to search posts for), `--posts 20` (posts fetched per trend, top 3 by engagement kept), `--no-replies`, `--out output`, `--from-raw output/raw-YYYY-MM-DD.json` (re-run the analysis on a saved pull with no API calls).

One run with the defaults on 2026-10-04 made 32 API calls, took about 100 seconds and cost $0.0975 in total (from the `X-Desearch-Cost-Usd` headers).

## Output (`output/`)

- `snapshot-YYYY-MM-DD.md`: the "what's moving where" report
- `trends-YYYY-MM-DD.csv`: every trend row (place, requested and returned WOEID, rank, name, query, volume if present)
- `posts-YYYY-MM-DD.csv`: every fetched post with engagement, age, language and a relevance flag
- `overlap-YYYY-MM-DD.png`: shared-trend heatmap between places plus a relevance bar chart
- `costs-YYYY-MM-DD.csv`: latency and cost per call
- `raw-YYYY-MM-DD.json`: raw API data for `--from-raw`

## Sample output (run of 2026-10-04, excerpt)

Full report: [sample-output.md](sample-output.md), chart: [overlap-2026-10-04.png](overlap-2026-10-04.png).

```
## Locations skipped (WOEID not supported)
- **Georgia** (WOEID 23424823): API returned HTTP 200 with `woeid: null` and 30 trends; treated as unsupported (looks like a Worldwide fallback).

## Global vs local
- Trends in 3+ of 6 locations: Carti (5), Lucki (5), Brewers (3), Cavan Sullivan (3), chivas (3), Milwaukee (3), Padres (3), Ty France (3), #UFC332 (3)
- Only in **United Kingdom**: 0 of 30 (identical trend list to London)
- Only in **Istanbul**: 29 of 29, e.g. 2026 ARIA, Aliyev, #AnaParaTakvimi, Azerbaycan, Azeri, Bilinmelidir

## Data quality checks
- Relevance: 98% of kept posts mention the trend in text or hashtags (all fetched posts: 95%).
- Freshness: median age of kept posts 4.2 h; 100% within 24 h; oldest 22.4 h
```

A few words in quoted post text are masked with `*` in the saved sample.

## Known limits

- Trends carry `name`, `query` and `rank` only. There is no volume field, so "biggest" means rank within a place.
- In testing on 2026-10-04, a WOEID the API does not support (for example Georgia, 23424823) returned HTTP 200 with `woeid: null` and a list matching Worldwide, not an error. The script compares the returned `woeid.id` with the one it asked for and skips places that do not match.
- There is no endpoint that lists supported places; the WOEID list linked from the API reference is the only guide.
- `count` for trends must be between 30 and 100; other values return HTTP 422.
- A trend list can contain the same trend twice (on 2026-10-04 Istanbul had `#pazar` at rank 1 and rank 2).
- Mention and relevance figures are sample counts (top `--posts` posts per trend), not total X volume.
- With desearch-py 1.2.1, the repr of an SDK exception includes the request headers, which carry your API key. The script logs only the status and message; do the same if you extend it.
