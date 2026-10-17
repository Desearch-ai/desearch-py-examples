# Instagram Engagement Rate Calculator

Made by [Desearch](https://desearch.ai).

Give it one public Instagram username. It pulls the profile and the latest posts from the Desearch API and works out the account's engagement rate, with the formula shown and a split by format (image, carousel, video/reel). You can add one or two peer accounts to see them side by side; each account is calculated on its own.

## The formula

```
per post:      engagement rate % = (likes + comments) / followers x 100
per account:   engagement rate % = mean of the per-post rates
               (the same as total likes + comments / posts / followers x 100)
```

The median of the per-post rates is shown next to the mean, so one viral post cannot hide a quiet feed. The same formula is applied to each format group for the split.

Left out of the rate, and counted in the output so you can see what was skipped:

- posts that look pinned (listed first but older than the post after them), because they are not part of the recent feed
- posts under 24 hours old, because they are still collecting likes
- posts with hidden likes

Saves and shares are not in the data, so this is a likes plus comments rate. Use `--include-pinned` or `--include-fresh` to count those posts anyway.

## What you get

- `<out>-summary.md`: the formula, one line per account and the split by format
- `<out>-summary.csv`: one row per account (followers, posts used and returned, skipped counts, average likes and comments, engagement rate, median, range, best format)
- `<out>-formats.csv`: one row per account and format (posts, share of posts, average likes, comments and views, engagement rate, median)
- `<out>-posts.csv`: one row per post (time, format, likes, comments, views when returned, rate, and why a post was skipped)
- `<out>-formats.svg`: a bar chart of engagement rate by format

## Setup

```bash
pip install -r requirements.txt
# Put your Desearch API key (from console.desearch.ai) in a key file, one line:
printf '%s' 'YOUR_KEY' > ~/.desearch_api_key && chmod 600 ~/.desearch_api_key
```

The script reads the key only from a key file: `~/.desearch_api_key` by default, or `--key-file PATH`. It does not read environment variables.

## Run

```bash
python ig_engagement_rate.py --accounts BRAND_ONE --count 12 --out output/brand
# with two peers for comparison
python ig_engagement_rate.py --accounts BRAND_ONE PEER_ONE PEER_TWO --count 12 --out output/brands
```

Offline, from the saved sample (no key, no cost):

```bash
python ig_engagement_rate.py --from-raw samples/sample-raw.json --out output/sample
```

Options: `--count` posts per account (capped at 20 in this script), `--include-pinned`, `--include-fresh`, `--raw-out` where the raw responses are saved, `--key-file`.

## Endpoints

- `GET /desearch/instagram/profile/{username}` for the follower count
- `GET /desearch/instagram/profile/{username}/posts?count=N` for the latest posts, each with `likeCount`, `commentCount`, `mediaType` and `createTime`

The Python SDK (desearch-py 1.2.1, checked 2026-10-17) has no Instagram methods yet, so the script calls these REST endpoints with `requests`.

## Notes from testing (2026-10-17)

- Each posts call returned the number of posts asked for (12 of 12 for three accounts).
- The result covers the latest N posts Desearch returned, not an account's full history. In testing no next-page cursor came back, so the script reads one page per account.
- `createTime` came back as a Unix timestamp; the script also accepts ISO strings.
- View counts were returned for only some videos, so average views is blank where none came back. The rate itself uses followers, not views.
- Instagram calls are billed per returned item. The cost is in the `X-Desearch-Cost-Usd` response header, and the script prints it per call and in total. Keep `--count` small.
- An unknown username returns 404 and is skipped; the other accounts still run.

## Sample output (`samples/sample-summary.md`)

| account | followers | posts used / returned | engagement rate % | median % | best format |
|---|---|---|---|---|---|
| brand_a | 268356497 | 6 / 12 | 0.0558 | 0.0423 | carousel (0.0858 %, n=3) |
| brand_b | 104375766 | 8 / 12 | 0.4525 | 0.2474 | carousel (0.8143 %, n=3) |
| brand_c | 17566964 | 12 / 12 | 0.3943 | 0.2972 | video/reel (0.4657 %, n=8) |

These are rates on the recent posts Desearch returned on 2026-10-17, not benchmarks. A full live run log is in `samples/live-run-2026-10-17.md`.

## Tests

```bash
python -m unittest discover -s tests
```
