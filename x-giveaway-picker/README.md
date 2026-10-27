# X Giveaway Picker
Made by Desearch

[https://desearch.ai](https://desearch.ai)

## What it does

Collect public X giveaway reposters, repliers, or both, apply entry rules, draw winners, and export an entrants CSV. The web page and CLI share network-free collection and draw logic in `core.py`; `app.py` provides the HTTP client and user interfaces. The samples contain made-up accounts and post ids.

## Requirements

Python 3 with the standard library. Install pytest for the offline tests using the requirements file.

## Get the code

```sh
git clone https://github.com/Desearch-ai/desearch-py-examples.git
cd desearch-py-examples
```

Alternatively, use sparse checkout:

```sh
git clone --filter=blob:none --sparse https://github.com/Desearch-ai/desearch-py-examples.git
cd desearch-py-examples
git sparse-checkout set x-giveaway-picker
```

Until this example is merged, add `--branch nino/x-giveaway-picker` to the clone command.

## Setup

The app itself needs only Python 3 and its standard library. Pip is only for the tests. Use a virtual environment to avoid the `externally-managed-environment` error:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r x-giveaway-picker/requirements.txt
```

For API-backed runs, configure `DESEARCH_API_KEY` or `DESEARCH_API_KEY_FILE` in your environment. The latter names an explicitly configured credential file. No default credential files are read. Offline fixture runs require neither variable.

The client sends its own User-Agent header; requests with the default Python urllib User-Agent are refused with HTTP 403.

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
| `--accept-partial-replies` | Draw despite incomplete reply coverage, including noninteractive CLI runs |
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

Open the printed local address. The web page allows 2 uncached runs per rolling 10 minutes and 5 per rolling day per IP. Invalid input returns HTTP 400 without consuming a run. Refused runs return a styled HTML page with HTTP 429 and `Retry-After`, before any API request. It explains both limits, the approximate wait, and that cached posts can still be re-drawn. The form retains the submitted values on success, validation errors (400), and rate-limit pages (429), including checkboxes and the draw timestamp.

The post lookup, reposter list, and reply list (per requested reply count) are cached as separate parts per post id. Each part has its own collection time and a 1-hour TTL; the cache holds up to 100 parts with oldest-entry eviction. A run with all needed parts cached makes no API calls, consumes no rate-limit run, and reports zero new cost. Switching from both modes to repost-only or reply-only with the same reply count is therefore free. If parts are missing, only those parts are fetched, the run consumes one uncached slot, and only new request cost is reported. Winner count, tags, age, and follower rules are applied fresh. Missing posts, failed reposter pages and non-503 reply errors are not cached. A 503 indicating no replies may be cached. CSV export uses stored results without fetching again.

When any part is reused, the page shows its collection time in a readable local format with a zone label and UTC offset. Set `GIVEAWAY_TZ=Asia/Tbilisi` (or another valid IANA zone) to choose the zone. An unset or invalid value uses the machine's local zone abbreviation and offset.

The client IP comes from the socket peer address. `X-Forwarded-For` is not trusted. Users behind a proxy share that proxy's limit. Cache, rate limits, and CSV exports are in memory and are lost on restart. Each server process has its own state.

To repeat a cached draw, enter the timestamp portion of the displayed seed in the optional draw timestamp field. The same timestamp and eligible list reproduce the winners.

## Test

```sh
python3 -m pytest -q x-giveaway-picker
```

Tests are offline with fake fetch clients and clocks. Web integration tests bind only to `127.0.0.1` on port 0. If the environment prohibits sockets, those tests skip; a socket-free HTTP handler test still exercises validation, rate limits, cache reuse, and CSV export. The fixture CLI test runs without either credential environment variable and blocks network connections.

## Sample output

Actual output from the offline command in Run (exit code 0, no stderr):

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
  "drawn": true,
  "draw_pending_confirmation": false,
  "rules": {
    "url": "https://x.com/i/status/900001234567890",
    "winners": 1,
    "min_tags": 0,
    "min_account_age_days": null,
    "min_followers": null,
    "must_repost": true,
    "must_reply": true,
    "count": 50,
    "entry_mode": "both",
    "draw_timestamp": "2026-10-23T00:00:00Z"
  },
  "counts": {
    "entrants": 1,
    "eligible": 1,
    "winners_requested": 1,
    "winners_drawn": 1
  },
  "message": "",
  "exclusions": {},
  "exclusions_all": {},
  "reply_coverage": {
    "returned": 1,
    "reported": 1,
    "unique_authors": 1
  },
  "partial_reply_warning": "",
  "seed": "900001234567890:2026-10-23T00:00:00Z",
  "notices": [
    "1 of 2 reposters collected; more may remain",
    "from the latest ~1 reply the API returned (post shows 1 reply)",
    "1 of 2 reported reposts returned; deleted, protected or uncollected accounts do not appear"
  ],
  "coverage": "Picked from 1 repost and 1 reply the API returned (post shows 2 reposts, 1 reply).",
  "cost_usd": 0.0,
  "returned_reposters": 1,
  "reported_reposts": 2
}
```

## How the draw works

Each user id has one entry. Repost mode requires a repost, reply mode requires a reply, and both requires both. The post author is excluded. Tags are distinct handles in a single reply, excluding the author's handle; separate replies are not combined. Missing age or follower data fails an enabled filter. Results include the rules used (entry mode, winners requested, tags, account age, followers, requested reply count and draw timestamp/seed) and counts for entrants, eligible accounts, winners requested and winners drawn. When fewer accounts qualify than requested winners, all eligible accounts are returned with an explicit message such as "Only 5 accounts met the rules, so 5 winners were drawn instead of 10." When none qualify, the result says "No accounts met the rules, so no winners were drawn." Each ineligible account is counted once in `exclusions`, by its first failed rule in rule-check order. `exclusions_all` preserves overlapping counts for every failed rule in JSON. The CSV `reason` lists every failed rule. The web page shows the draw message first, followed by a readable "Not eligible: 44 accounts (counted once, by the first rule each failed): reply not returned (40), not enough followers or unknown (4)." sentence sorted by count descending, then reason name. It omits that sentence when there are no exclusions. The CLI also prints these draw messages to stderr.

The seed is the post id plus `:` plus the ISO UTC draw timestamp. Python `random.Random` draws from eligible accounts sorted by user id. This is a seeded, reproducible draw: the same seed and same eligible list reproduce it. Eligibility rules must also match when repeating a draw.

## Limits

Post resolution uses `/twitter/urls` first. An empty result stops with "post not found or not public" and no reposter or reply calls. A failed resolution raises an error.

Reposters follow `next_cursor` until null, a repeated cursor, an empty users page, a page with no new user ids, or the 25-page cap. The API does not document a page size. When the 25-page cap is reached and the last page still adds new ids, the app shows "first 25 pages of reposters only (N collected; more remain)". Otherwise, when fewer unique reposters are collected than the post reports, it shows "N of R reposters collected; more may remain". N is the number of unique reposters collected and R is the reported retweet count. These two notices are mutually exclusive. Each failed page is retried once, then collection stops and the draw uses accounts collected so far with a notice. Users without ids are skipped and duplicate ids are merged.

Replies use one call only. `reply_coverage.returned` counts reply items returned by the API (including multiple replies by the same author); `reported` is the post's `reply_count`. `unique_authors` separately counts distinct reply author ids. These are collection and result fields. When the rules require a reply, the web page shows returned and reported counts together with unique authors. Repost-only results omit this reply coverage line; CLI JSON still includes these fields. Accounts have one entry per user id.

In reply mode, fewer returned reply items than reported replies produces a warning before the draw. Accounts without a returned reply are marked "reply not returned" in entrants and CSV and cannot win. Accounts absent from all collected lists cannot appear in the export. Consider repost-only mode when reply coverage is incomplete.

The main form always keeps its "Collect and draw" button so changed rules can be submitted normally. Below the warning text, a separate form has a "Draw anyway" button, followed by rules, counts and CSV export. Above the button it explains: "Press Draw anyway to draw from the replies that came back. This uses the cached list, so it makes no new API calls and does not use a run." That button resubmits the same values with `confirm_partial_replies=1`, reusing the cached collection with no API calls or rate-limit run. The CLI prints the warning to stderr. On a TTY it asks "Draw anyway? [y/N]" and draws only for y/yes. `--accept-partial-replies` accepts the warning explicitly. Without a TTY, that flag is required to draw. Refusal prints JSON with empty winners and `drawn: false` and `draw_pending_confirmation: true`, still writes `--csv` if supplied, and exits with code 3. Collection happens once.

A replies HTTP 503 with zero reported replies, or detail saying no replies were found, says plainly that the post has no replies the API could find and includes the API detail, for example "X search found no replies for this post. You were not charged." It does not say collection stopped early. Other reply failures show "reply collection failed (HTTP status): detail". When fewer reposters return than reported, an additional notice explains that deleted, protected, or uncollected accounts do not appear.

API results can change between runs. Expired collections are fetched again, so a seed alone cannot reproduce a draw without the same eligible list. The app sums the `x-desearch-cost-usd` response header for requests made during a run; missing or invalid cost headers contribute nothing. See [Desearch pricing and billing](https://www.desearch.ai/docs/guide/introduction/pricing-and-billing) for pricing information.


## Links and readable errors

Numeric post ids and http(s) X post links are accepted. Scheme-less `x.com/user/status/id`, `www.x.com/...`, `twitter.com/...`, `mobile.twitter.com/...` and `mobile.x.com/...` links are normalized to HTTPS before API calls. Profile links, other domains and arbitrary text are rejected.

API errors show readable messages in the CLI without a traceback and on the normal web page with HTTP 502. HTTP 401 and JSON HTTP 403 explain that Desearch refused the key and point to console.desearch.ai. A non-JSON HTTP 403 says: "Desearch refused the request at the edge (HTTP 403). This is not a key problem; check the client's User-Agent and network." HTTP 402 is labeled payment required and preserves the API detail (including credits or balance guidance when supplied). HTTP 429 asks the user to wait, 5xx identifies a Desearch server error and preserves detail, and other statuses include the status and detail. Missing or unreadable explicitly configured key files show their path without raw OS errors or key contents. Network errors explain that Desearch could not be reached and suggest checking the connection.

`drawn` is true only when at least one winner was drawn. `draw_pending_confirmation` is true only when partial-reply confirmation held the draw; when nobody qualifies, both fields are false. The CLI exits 0 when nobody qualifies, 3 when confirmation is declined or not accepted, and 1 on error. No-replies and reply-collection-failure notices also print to stderr before the draw message. A no-replies notice does not also claim that the latest ~0 replies were returned.

Coverage describes only the entry modes used. For example: "Picked from 44 reposts the API returned (post shows 47 reposts). Replies: 4 returned, not used in repost-only mode." If no replies were fetched, the extra reply sentence is omitted. Reply-only coverage similarly does not claim reposts were used. Reply collection notices are omitted in repost-only mode.

Validation names the field and its range on both the web (HTTP 400) and CLI: "Winners must be from 1 to 10.", "Minimum tags must be from 0 to 5.", "Reply count must be from 1 to 100.", "Minimum account age days must be 0 or more.", and "Minimum followers must be 0 or more." Noninteger values use the same readable field labels with "must be an integer."
