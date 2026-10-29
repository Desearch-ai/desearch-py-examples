# Social Media Username Checker
Made by Desearch ([https://desearch.ai](https://desearch.ai))

Checks one or more handles across Instagram, TikTok, X and Facebook, printing a grid of public profile results with display names, follower counts when present, and profile links. Statuses are `found`, `not_found` (no public profile found), `could_not_check`, and `invalid`. Invalid local formats skip HTTP requests.

## Endpoints used

GET requests to `https://api.desearch.ai`, authenticated with the Authorization header:

- Instagram: `/desearch/instagram/profile/{username}`
- TikTok: `/desearch/tiktok/profile/{username}`
- Facebook: `/desearch/facebook/profile/{profile_id}`
- X: `/twitter/user/posts?username=<handle>`; only the username parameter is sent.

## Setup

Python 3.10+ is required. No packages are needed. Get a key at [console.desearch.ai](https://console.desearch.ai), and set the environment variable `DESEARCH_API_KEY`, or supply a key file. The key is never intentionally printed or saved.

## Run

From the `username-checker` directory:

```sh
python3 username_checker.py candidate_one candidate_two
python3 username_checker.py https://www.instagram.com/candidate_one/ --networks instagram,x
python3 username_checker.py candidate_one --dry-run
python3 username_checker.py candidate_one --key-file /path/to/key --out reports --json
python3 username_checker.py --from-raw out/raw-YYYYMMDD-HHMMSS.json
```

Handles are trimmed and leading @ characters removed. Supported full profile URLs are accepted.

## Options

- `--networks`: comma-separated networks, default `instagram,tiktok,x,facebook`.
- `--out DIR`: output directory, default `out/`.
- `--timeout SECONDS`: timeout per HTTP attempt, default 60. X can take about 50 seconds.
- `--workers N`: parallel worker count, default 8. Results retain input handle and network order.
- `--dry-run`: print planned URLs and maximum calls, including retries; no key or network needed.
- `--from-raw FILE`: rebuild outputs from saved JSON with zero HTTP calls and no key needed.
- `--key-file PATH`: read the key from a file instead of the environment.
- `--json`: also print structured results after the grid.

Only HTTP 503 is retried, once after two seconds. HTTP 401/403 aborts the run; in-flight requests may finish. Missing credentials cause a friendly nonzero exit.

## Outputs

- `raw-YYYYMMDD-HHMMSS.json`: call records with URLs, status codes, attempts, timing, cost, errors and response bodies. The `responses` array preserves each HTTP response, including retries. Authorization fields and key text are redacted.
- `results.csv`: one row per handle and network.
- `grid.md`: grid, per-handle details, limitations note and cost summary. Also printed to stdout.

A compact call, cost and elapsed-time summary is printed to stderr. Latency includes retry waiting. Costs sum the `X-Desearch-Cost-Usd` headers across attempts. Missing or malformed cost headers count as zero and are flagged as unknown. Replay reports original call counts and costs, with the current rebuild duration; it makes zero new calls.

See [Sample output](sample-output.md) for a real run.

## Cost

Measured on 2026-10-29 (cost from the X-Desearch-Cost-Usd response header): an Instagram, TikTok or Facebook profile that is found cost $0.00207 per call; X user posts cost $0.0027 to $0.00285 per found account (18 to 19 posts returned); every not found answer (404) and every TikTok 503 cost $0. Three handles on four networks (12 calls in total) cost $0.02097 and took about 10 seconds with parallel calls. Use --dry-run to see the planned calls first.

## Known limits

No public profile found does not mean the handle is free: it can be reserved, banned, private, suspended or deactivated. Check on the network's own signup page.

TikTok answered 503 "Service request failed" for handles that do not exist in our tests, so the app retries once and then shows "could not check". X results come from the user posts endpoint because there is no X profile lookup endpoint. This is slower and billed per post returned. An empty X response shows could not check, with an empty response note. Facebook needs the vanity name or numeric id. Private or restricted accounts may look like missing ones. Local format rules are approximations. Responses without a recognizable profile show could not check. Public profile discovery cannot determine signup eligibility.

## Offline tests

```sh
cd username-checker && python3 -m unittest discover -s tests -v
```

Tests use mocked HTTP and synthetic fixtures, with no network access.
