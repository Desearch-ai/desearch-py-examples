# TikTok Profile Analytics to CSV

Made by [Desearch](https://desearch.ai).

Give it a few public TikTok usernames. It pulls each profile and its recent posts from the Desearch API and writes:

- `<out>-posts.csv`: one row per post (time, weekday, views, likes, comments, shares, saves, engagement rate, duration, hashtags, caption, a `likely_pinned` flag)
- `<out>-summary.csv`: one row per profile (followers, posts analyzed, posts per week, median gap between posts, average and median views, median likes, comments and shares, average and median engagement rate, views per follower, best weekday, top post)
- `<out>-summary.md`: a short table you can paste into a note

Engagement rate per post = (likes + comments + shares) / views.

## Setup

```bash
pip install -r requirements.txt
# Put your Desearch API key (from console.desearch.ai) in a key file, one line:
printf '%s' 'YOUR_KEY' > ~/.desearch_api_key && chmod 600 ~/.desearch_api_key
```

The script reads the key only from that file (or from `--key-file PATH`). It does not read environment variables.

## Run

```bash
python tiktok_profile_analytics.py --profiles BRAND_ONE BRAND_TWO BRAND_THREE --count 10 --out output/brands
```

Offline, from the saved sample (no key, no cost):

```bash
python tiktok_profile_analytics.py --from-raw samples/sample-raw.json --out output/sample
```

Options: `--count` posts per call (capped at 20), `--pages` pages per profile (default 1), following the cursor the API returns in the `x-desearch-next-cursor` header and stopping when there is no next page; each page is billed per item. `--raw-out` sets where the raw responses are saved, `--key-file` sets the key file.

## Notes from testing (2026-10-16)

- Endpoints: `GET /desearch/tiktok/profile/{username}` and `GET /desearch/tiktok/profile/{username}/posts?count=N`.
- TikTok calls are billed per returned item. Cost is shown in the `X-Desearch-Cost-Usd` response header, and the script prints it per call and in total.
- Each posts call returned up to 10 posts in testing even with a higher `count`; for more, use `--pages`, which sends back the `x-desearch-next-cursor` header value unchanged as `cursor` and stops when the header is absent. Treat results as the latest posts Desearch returned, not a full history.
- Pinned videos are listed first even when they are old. The script flags them and leaves them out of posts per week.
- Posts per week uses a window of at least 7 days, so a burst of posts in one evening does not read as hundreds per week.
- An unknown username gets an error status and is skipped; the other profiles still run.

## Sample output (`samples/sample-summary.md`)

| profile | followers | posts | posts/week | median views | median ER % |
|---|---|---|---|---|---|
| brand_a | 2100000 | 10 | 5.22 | 293205.5 | 7.489 |
| brand_b | 18300000 | 10 | 9.0 | 600720.5 | 15.636 |
| brand_c | 27300000 | 10 | 7.0 | 80453.5 | 8.239 |

## Tests

```bash
python -m unittest discover -s tests
```
