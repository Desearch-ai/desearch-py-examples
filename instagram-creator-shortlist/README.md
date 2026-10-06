# Instagram Creator Shortlist

Made by Desearch ([https://desearch.ai](https://desearch.ai))

A small Python script for marketers and analysts. Type a niche keyword and it finds public Instagram creators through the Desearch API, pulls their recent posts, and writes a ranked shortlist grouped by follower tier (nano, micro, mid, macro) with median engagement rate, median likes and comments, posting cadence and days since the last post. Output is Markdown, CSV and a PNG chart of followers vs engagement.

What it does:

1. Search (`POST /desearch/instagram/search` with body `{"query": "home gym", "count": 20}`) for profiles matching the keyword.
2. Profile (`GET /desearch/instagram/profile/{username}`, username in the path) for every search result, for followers and the private flag.
3. Recent posts (`GET /desearch/instagram/profile/{username}/posts?count=12`) for up to 10 public creators with at least 1,000 followers, largest first.
4. Computes per creator: engagement rate per post = (likes + comments) / followers and its median, median likes and comments, posts in the last 30 days, median days between posts, days since the last post (pinned posts excluded), video share, and a stale flag (no post in 30+ days). Logs status, latency, items returned and cost per call from the `X-Desearch-*` response headers.

The official Python SDK (desearch-py 1.2.1) has no Instagram methods yet, so the script calls the REST API directly with `requests`.

## Setup

Run everything from this folder (`instagram-creator-shortlist/`). Python 3.10+.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Environment variable (by name only, never commit it):

- `DESEARCH_API_KEY`: your API key from console.desearch.ai (API Keys page).

## Run

```bash
export DESEARCH_API_KEY=...        # paste your key, or load it from your secret store
python ig_shortlist.py "home gym"  # writes to ./output
```

Options: `--search-count 20`, `--max-creators 10`, `--posts 12`, `--min-followers 1000`, `--out output`, `--from-raw output/raw-YYYY-MM-DD-home-gym.json` (re-run the analysis on a saved pull with no API calls).

One run for "home gym" with the defaults on 2026-10-06 made 31 API calls, took about 80 seconds and cost $0.3312 in total (from the `X-Desearch-Cost-Usd` headers).

## Output (`output/`, file names carry the date and keyword)

- `shortlist-*.md`: ranked creators per tier plus data quality checks
- `shortlist-*.csv`: one row per pulled creator with all metrics
- `profiles-*.csv`: every search result with search and profile follower counts
- `posts-*.csv`: every post with likes, comments, plays, age and media type
- `engagement-*.png`: followers (log) vs median engagement rate, colored by tier
- `costs-*.csv`: status, latency, items returned, billed units and cost per call
- `raw-*.json`: raw API data for `--from-raw`

## Sample output (run of 2026-10-06, excerpt)

Full shortlist: [sample-output.md](sample-output.md), chart: [engagement-2026-10-06-home-gym.png](engagement-2026-10-06-home-gym.png).

```
## Micro creators
| Rank | Creator | Followers | Median ER | Median likes | Median comments | Posts in 30 d | Median gap | Last post | Video share |
| 1 | @homegym_nzninth | 27,595 | 4.72% | 1,274 | 33 | 2 | 6.8 d | 14 d ago | 33% |
| 2 | @crossfit.pawa | 10,359 | 1.99% | 182 | 24 | 1 | 2.6 d | 27 d ago | 100% |
| 3 | @homegym_mwenge | 10,420 | 0.36% | 38 | 1 | 11 | 0.5 d | 0 d ago | 91% |

## Data quality checks
- Followers, search vs profile call: 10 of 10 identical.
- `postsCount` on profiles: 12 (20); search `mediaCount`: 12 (10), missing (10).
- Posts out of date order (newer than the post before it): 9 across 7 creators; leading posts treated as pinned and excluded from ER/cadence: 14 (no pinned flag in the response).
```

## Known limits

- The posts call returned at most 12 posts in testing on 2026-10-06, even with `count=20`, and no pagination cursor comes back, so metrics use up to 12 recent posts.
- `postsCount` on the profile (and `mediaCount` in search) read 12 for every account on 2026-10-06, while the public pages showed 100 to 2,488 posts. Do not use it as a total post count.
- Search results often omit `followers` (present on 8 to 10 of 20 results on 2026-10-06), so the script takes followers from the profile call for every result.
- Pinned posts come first in the posts response, with no pinned flag, and can be years old. A leading post is treated as pinned when a later post is newer, and it is left out of engagement and cadence.
- `stats.viewCount` was not returned; video posts carry `playCount` instead. Post `createTime` is Unix seconds (an integer), not an ISO string as shown in the docs.
- `following` on the profile read a little lower than the public page on 2026-10-06; follower counts matched. The script does not use `following`.
- A username that does not exist returns HTTP 404 on the profile call and an empty list on the posts call; a search with no matches returns HTTP 404.
- No Instagram methods in desearch-py 1.2.1; the script uses plain HTTP.
