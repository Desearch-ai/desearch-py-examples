# Ad Library Angle Log

Made by Desearch. Built on the [Desearch API](https://desearch.ai) (https://desearch.ai).

A small Python CLI for e-commerce marketers and the developers who help them. Give it one or more store names, and it pulls matching public Meta Ad Library records with Desearch Facebook search, then writes a Markdown angle log per store (hooks and angles grouped by ad copy, offers, CTAs found in the copy, landing page notes, days since each ad started) and a JSON snapshot. Run it again later and it writes a diff: new ads, disappeared ads, unchanged ads.

The runs below were made live on 2026-10-05 (Asia/Tbilisi) against `POST https://api.desearch.ai/desearch/facebook/search`, with Gymshark and Allbirds as the example stores. Landing pages use `GET https://api.desearch.ai/web/extract`.

## Setup

Run the commands in this README from the `ad-library-angle-log` folder.

Python 3.10 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai (API Keys page)
```

The only env var is `DESEARCH_API_KEY`. The code reads it by name and never prints or logs it. Saved request/response files (`--save-raw`) have the `Authorization` header replaced with `<redacted>`.

## Run

```bash
# run 1
python adlog.py run --store Gymshark --store Allbirds --save-raw

# later: run 2, plus a diff against the newest earlier snapshot
python adlog.py run --store Gymshark --store Allbirds --save-raw --diff-against latest

# diff any two snapshots, or re-render a snapshot without calling Desearch
python adlog.py diff runs/<run1>/snapshot.json runs/<run2>/snapshot.json
python adlog.py render runs/<run>/snapshot.json
```

Each run writes `runs/<timestamp>[-label]/`:

| File | What it is |
|---|---|
| `snapshot.json` | Every ad record (normalized), the calls made, cost per call |
| `<store>-angle-log.md` | The angle log for that store |
| `diff.md`, `diff.json` | Only with `--diff-against` (or from `adlog.py diff`) |
| `raw/` | Only with `--save-raw`: each request/response, key redacted |

Options for `run`:

| Flag | What it does |
|---|---|
| `--store NAME` | Store or brand keyword, repeatable. Matching is case-insensitive. Keep the brand as one word (`Gymshark`, not `Gym Shark`). |
| `--count N` | Ads to request per store (default 30, allowed 1 to 100). `POST /desearch/facebook/search` returns at most 30 ads per request, so values above 30 are clamped to 30. `--no-clamp` sends the number as is. You are billed per ad returned. |
| `--no-probe` | Skip the `count: 1` check that runs before the full search. The probe only skips the second call when the keyword matches nothing. |
| `--extract N` | Fetch up to N landing pages with `GET /web/extract` and `format=text`, only for URLs that appear in the ad text. Store ads first, each URL once. |
| `--label TEXT` | Suffix for the run folder name. |
| `--diff-against PATH or latest` | Write `diff.md` and `diff.json` against a previous snapshot. |

Progress, HTTP status, latency and cost per call go to stderr. The first store's angle log goes to stdout.

To check the diff logic without calling Desearch: `python -m pytest test_diff.py`.

## Request it sends

```bash
curl -X POST "https://api.desearch.ai/desearch/facebook/search" \
  -H "Authorization: $DESEARCH_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "Gymshark", "count": 30}'
```

The response is a JSON array of ad records: `id` (Ad Library id), `url` (`https://www.facebook.com/ads/library?id=<id>`), `text` (ad copy), `createTime`, `author` (the advertiser page: `id`, `name`, `url`, `category`, `likes`), `stats`, `media`, `hashtags`.

## What the app does with each record

1. Normalizes it. `createTime` (a Unix timestamp in seconds in the 2026-10-05 responses) becomes the start date. Days since start = run date minus start date.
2. Marks whether the advertiser name contains the store name. Other advertisers that mention the store are listed separately, not mixed into the store's angles.
3. Groups the store's ads by identical copy. Ad Library lists each version of a creative as its own ad id. In the 2026-10-05 run, Gymshark's 24 store ads were 10 distinct copies and Allbirds' 24 were 11.
4. Tags angles with keyword rules (offer, new arrival, motivation, comfort, community, seasonal, social proof). The rules cover English plus the French, Spanish, Italian, Dutch and German copy in those runs. It also pulls offers (percent off, codes, free shipping) and CTA phrases out of the text.
5. Looks for a URL or domain in the ad text. Only those are passed to Extract. The record has no landing URL field.

## Sample output

Excerpt from the live run at 2026-10-05 09:52 Asia/Tbilisi (`count: 30`, plus one `GET /web/extract?format=text` call). Full output for both stores, and the run 1 to run 2 diff, is in `sample-output.md`.

```markdown
# Ad angle log: Gymshark

Desearch calls: probe count=1 -> HTTP 200, 1 ads, 1 units, $0.00207, 4.02 s; search count=30 -> HTTP 200, 30 ads, 30 units, $0.06210, 2.7 s
Extract calls: 1.
Cost for this store: $0.06467 (sum of X-Desearch-Cost-Usd). Billed units: 31.

## At a glance
- Ads returned: 30 (24 from an advertiser named like "Gymshark", 6 from other advertisers that mention it)
- Distinct ad copies from the store: 10 (Ad Library lists each version of a creative as its own ad)
- Records with a landing URL or domain in the data: 2 of 30 (0 of 24 store ads)

## Angles in the store's ads
| Angle | Ads | Distinct copies |
|---|---|---|
| offer / discount | 17 | 4 |
| motivation / identity | 16 | 3 |
| new arrival / launch | 10 | 3 |
| seasonal | 2 | 1 |

### 2. Ça sent une motivation à bloc et de nouveaux PRs dans ces tenues 🔥
- Versions: 7 ad ids; started 2026-07-02 to 2026-08-16; 95 days since the earliest start
- Offer in copy: Extra -10% avec le code WELCOME10
```

The $0.06467 total is the search cost plus one Extract call at $0.00050 (31 returned ads at $0.00207 is $0.06417). The diff between run 1 (09:31) and run 2 (09:51), both with `--count 30`, was 0 new, 0 disappeared, 30 unchanged for each store. Nothing changed in 20 minutes. Run it daily or weekly to see movement.

## Measured cost and speed

Measured on 2026-10-05 (Asia/Tbilisi) from the `X-Desearch-Cost-Usd` and `X-Desearch-Usage-Count` response headers, and from `time.perf_counter()` around each request.

Billing as of the 2026-10-05 fix, on `POST /desearch/facebook/search` and `GET /web/extract`: a call is charged only for each unique item actually returned. Empty results cost $0. HTTP 422, 404 and 5xx responses are refunded.

- `POST /desearch/facebook/search`: **$0.00207 per ad returned**. On 2026-10-05, `count: 10` with 10 ads returned cost $0.0207. `count: 50` returned 30 ads and cost $0.0621 (30 units). An empty keyword (`Gymshrak`, and a made-up name) at `count: 20` cost $0 and 0 units.
- `GET /web/extract` with `format=text`: $0.0005 per call that returns page text. An empty page returns HTTP 404 `No content found` and costs $0. A failed Extract call returns that same free 404. The angle log prints the HTTP status from the response.
- One store with the defaults (a `count: 1` probe plus `count: 30` when ads exist) is $0.06417. Two stores are $0.12834. An empty keyword costs $0.
- Latency on the 2026-10-05 morning runs: `POST /desearch/facebook/search` took 1.2 s to 6.0 s. `GET /web/extract` with `format=text` took 2.0 s to 10.1 s.

## Known limits

- `POST /desearch/facebook/search` returns at most 30 ads per request. On 2026-10-05, `count: 31` and `count: 50` both returned 30 ads. `cursor` is ignored, so there is no paging. That is why the app clamps `--count` to 30.
- Records have no landing URL field, and no CTA button, headline or link description. In the 2026-10-05 09:52 run with `count: 30`, none of the 48 store ads (24 Gymshark, 24 Allbirds) had a URL in the text either, so the app had no store landing pages to fetch. The URLs it did find were in ads from other advertisers. The app only calls Extract for a URL that is already in the record text.
- `createTime` is the ad's start date. On 2026-10-05 it was a Unix timestamp in seconds, and it matched the public Ad Library start date for the 10 ads compared that day. The record has no end date, so days since start counts time live only while the ad is still running.
- `POST /desearch/facebook/search` has no country or active-status filter. Results mix countries and languages.
- `POST /desearch/facebook/search` has no sort or date parameter. For Gymshark on 2026-10-05, the 30 ads from `count: 30` were all July to August starts, while the public Ad Library page showed Gymshark ads started as recently as 2026-10-02. A quiet diff does not prove there were no new launches. "Disappeared" in a diff means the ad id was not in the second run's 30 results.
- In that same `count: 30` run, `stats` was empty on every record. `media` was present on 1 of 30 Gymshark records and 9 of 30 Allbirds records.

## Files

- `adlog.py`: the CLI
- `test_diff.py`: offline check of the diff logic
- `requirements.txt`: `requests`
- `sample-output.md`: angle logs for both stores, plus the run 1 to run 2 diff
