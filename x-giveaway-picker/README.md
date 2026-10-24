# X Giveaway Picker
Made by Desearch

[https://desearch.ai](https://desearch.ai)

## What it does

Collect public X giveaway reposters, repliers, or both, apply entry rules, draw winners, and export an entrants CSV. The web page and CLI share network-free collection and draw logic in `core.py`; `app.py` provides the HTTP client and user interfaces. The samples contain made-up accounts and post ids.

## Requirements

Python 3 with the standard library. Install pytest for the offline tests using the requirements file.

## Setup

```sh
python3 -m pip install -r x-giveaway-picker/requirements.txt
```

For API-backed runs, configure `DESEARCH_API_KEY` or `DESEARCH_API_KEY_FILE` in your environment. The latter names an explicitly configured credential file. No default credential files are read. Offline fixture runs require neither variable.

## Run

From the repository root:

```sh
python3 x-giveaway-picker/app.py --cli 900001234567890 --demo-fixtures --mode both --draw-timestamp 2026-10-23T00:00:00Z
```

Omit `--demo-fixtures` to use the API with a public post URL or numeric id. CLI runs have no cache or rate limit. Inputs are validated before fetching.

| Flag | Meaning |
| --- | --- |
| `--cli POST` | Run once and print JSON for a post URL or numeric id |
| `--demo-fixtures` | Use offline responses from `samples/`; requires `--cli` |
| `--mode repost\|reply\|both` | Entry mode, default `repost` |
| `--winners` | Requested winners, 1 to 10, default 1 |
| `--min-tags` | Distinct tags in one reply, 0 to 5, default 0 |
| `--min-account-age-days` | Optional nonnegative minimum account age |
| `--min-followers` | Optional nonnegative minimum followers |
| `--count` | Reply request count, 1 to 100, default 50 |
| `--draw-timestamp` | Optional ISO UTC draw timestamp to repeat a draw |
| `--csv PATH` | Write collected accounts and eligibility to CSV |
| `--port` | Web server port, default 8000 |
| `--help` | Show argument help |

## Serve

```sh
python3 x-giveaway-picker/app.py --port 8000
```

Open the printed local address. The web page allows 2 uncached runs per rolling 10 minutes and 5 per rolling day per IP. Invalid input returns HTTP 400 without consuming a run. Refused runs return HTTP 429 with `Retry-After`, before any API request.

Collections are cached for 1 hour by post id, entry mode, and reply count, with up to 100 entries and oldest-entry eviction. Cache hits do not count against the rate limit, make no API calls, and report zero new request cost. Winner count, tags, age, and follower rules are applied fresh to cached accounts. Errors such as a missing post are not cached. CSV export uses stored results without fetching again.

The client IP comes from the socket peer address. `X-Forwarded-For` is not trusted. Users behind a proxy share that proxy's limit. Cache, rate limits, and CSV exports are in memory and are lost on restart. Each server process has its own state.

To repeat a cached draw, enter the timestamp portion of the displayed seed in the optional draw timestamp field. The same timestamp and eligible list reproduce the winners.

## Test

```sh
python3 -m pytest -q x-giveaway-picker
```

Tests are offline with fake fetch clients and clocks. Web integration tests bind only to `127.0.0.1` on port 0. If the environment prohibits sockets, those tests skip; a socket-free HTTP handler test still exercises validation, rate limits, cache reuse, and CSV export. The fixture CLI test runs without either credential environment variable and blocks network connections.

## Sample output

Actual output from the offline command in Run:

```json
{
  "entrants": [
    {
      "user_id": "900001",
      "username": "entrant_01",
      "followers": 42,
      "account_created_at": "2018-10-10T20:19:24Z",
      "reposted": true,
      "replied": true,
      "tags": 1,
      "eligible": true,
      "reason": ""
    }
  ],
  "winners": [
    {
      "user_id": "900001",
      "username": "entrant_01",
      "followers": 42,
      "account_created_at": "2018-10-10T20:19:24Z",
      "reposted": true,
      "replied": true,
      "tags": 1,
      "eligible": true,
      "reason": ""
    }
  ],
  "seed": "900001234567890:2026-10-23T00:00:00Z",
  "notices": [
    "from the latest ~1 replies the API returned (post shows 1 replies)",
    "1 of 2 reported reposts returned; deleted, protected or uncollected accounts do not appear"
  ],
  "coverage": "Picked from 1 reposts and 1 replies the API returned (post shows 2 reposts, 1 replies).",
  "cost_usd": 0.0,
  "returned_reposters": 1,
  "reported_reposts": 2
}
```

## How the draw works

Each user id has one entry. Repost mode requires a repost, reply mode requires a reply, and both requires both. The post author is excluded. Tags are distinct handles in a single reply, excluding the author's handle; separate replies are not combined. Missing age or follower data fails an enabled filter. When fewer accounts qualify than requested winners, all eligible accounts are returned.

The seed is the post id plus `:` plus the ISO UTC draw timestamp. Python `random.Random` draws from eligible accounts sorted by user id. This is a seeded, reproducible draw: the same seed and same eligible list reproduce it. Eligibility rules must also match when repeating a draw.

## Limits

Post resolution uses `/twitter/urls` first. An empty result stops with "post not found or not public" and no reposter or reply calls. A failed resolution raises an error.

Reposters follow `next_cursor` until null, a repeated cursor, or the 25-page cap. The API does not document a page size. Only a remaining cursor at that cap produces "first 25 pages of reposters only (N collected; more remain)", where N is the number of unique reposters collected. Each failed page is retried once, then collection stops and the draw uses accounts collected so far with a notice. Users without ids are skipped and duplicate ids are merged.

Replies use one call only. A notice reports "from the latest ~N replies" alongside the reported reply count. The coverage line compares returned repost and reply counts with reported counts. When fewer reposters return than reported, an additional notice explains that deleted, protected, or uncollected accounts do not appear.

API results can change between runs. Expired collections are fetched again, so a seed alone cannot reproduce a draw without the same eligible list. The app sums the `x-desearch-cost-usd` response header for requests made during a run; missing or invalid cost headers contribute nothing. See [Desearch pricing and billing](https://www.desearch.ai/docs/guide/introduction/pricing-and-billing) for pricing information.
