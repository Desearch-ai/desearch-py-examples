# X Account Analytics

Made by [Desearch](https://desearch.ai).

A small Python script for analysts, founders and social media leads who want a quick engagement read on one public X account. You give it a username. It pulls the account's latest posts with the Desearch API (`GET /twitter/user/posts`, following `next_cursor` for a few pages), and writes a per-post CSV and a short markdown summary: engagements, engagement rate per view and per follower, posts per day, best weekday and hour, top posts, and a split by post type and media.

It covers the latest posts Desearch returns for the account (a few dozen with the default 3 pages), not the account's full history.

## What you get

- `<prefix>-posts.csv`: one row per post: date (UTC and your time zone), weekday, hour, type (original, reply, thread reply to itself, quote, repost), media (none, photo, video, gif, mixed), pinned flag, likes, reposts, replies, quotes, bookmarks, views, engagements, ER per view %, ER per follower %, whether the post is in the rates and why not, link and text
- `<prefix>-summary.md`: account numbers, medians and means, best weekday and hour, tables by post type and by media, top posts by engagements and by ER per view, the list of excluded posts, and a page log (posts returned, new, repeated)
- `<prefix>-summary.csv`: the headline numbers in one row, for a spreadsheet
- the raw responses as JSON, so you can rebuild everything offline

## How the numbers are computed

```
engagements          = likes + reposts + replies + quotes + bookmarks
ER per view %        = engagements / views x 100
ER per follower %    = engagements / followers x 100   (followers at run time)
```

- **Reposts are left out of every rate.** In my tests a repost row came back with 0 likes, the original post's repost count and a view count of its own, so its numbers are not the account's own engagement. They stay in the CSV and the post type counts.
- **Posts with no view count** stay in the per-follower rate and are left out of the per-view rate. Both kinds of exclusion are counted and listed in the summary.
- **Posts per day** = posts analyzed / days between the first and last post (at least 1 day).
- **Best weekday and hour** compare median engagements for slots with at least 2 posts, in the time zone you pass with `--tz` (default UTC). With a few dozen posts, read them as hints.
- Posts that appear on two pages are counted once; the page log shows the repeats.

## Setup

```bash
pip install -r requirements.txt
# Put your Desearch API key (from console.desearch.ai) in a key file, one line:
printf '%s' 'YOUR_KEY' > ~/.desearch_api_key && chmod 600 ~/.desearch_api_key
```

The script reads the key only from a key file (`--key-file PATH`, default `~/.desearch_api_key`). It does not read environment variables.

## Run

```bash
python x_account_analytics.py --username desearch_ai --pages 3 --tz UTC --key-file ~/.desearch_api_key
```

Offline, from the saved sample (no key, no cost):

```bash
python x_account_analytics.py --from-raw samples/sample-raw.json --out output/sample
```

Options: `--pages` (1 to 10, default 3; each page is one call), `--tz` (any IANA time zone, for example `Asia/Tbilisi`), `--top` (top posts to list, default 5), `--out` (output prefix, default `output/<username>`), `--raw-out`.

## Endpoint and SDK

`GET https://api.desearch.ai/twitter/user/posts?username=...&cursor=...` returns `user` (including `followers_count` and `statuses_count`), `tweets` (each with `like_count`, `retweet_count`, `reply_count`, `quote_count`, `bookmark_count`, `view_count`, `created_at`, `media`, `is_retweet`, `is_quote_tweet`, `in_reply_to_status_id`) and `next_cursor`.

The script uses the desearch-py SDK (1.2.1): `Desearch.x_user_posts(username, cursor=..., include_metadata=True)`, which also returns the per-call cost from the response headers. The script adds those up and prints the total for a live run.

## Notes from testing (2026-10-19)

- There is no page size setting. Each page came back with 13 to 19 posts, and adding a `count` parameter did not change the page.
- Each `next_cursor` page picked up in date order where the previous page ended. One post showed up at the end of one page and again at the start of the next, so the script dedupes by post id. Sending the same cursor again returned the same page.
- Three pages reached about three weeks back on a brand account that posts about twice a day. Four pages reached about four weeks.
- Every post in my runs had a view count, for two accounts and posts up to four weeks old.
- Some of an account's thread replies (its replies to its own posts) did not show up in the timeline, while `GET /twitter` with `from:<username>` and `sort=Latest` found them. If threads matter for your analysis, cross-check with X search.
- A username that does not exist returned 404 with "User not found or unavailable". The SDK raises on that status, and the script records the status and stops.
- Repost rows carry mixed numbers (see above), which is why they are left out of the rates.

## Sample output

`samples/sample-posts.csv`, `samples/sample-summary.md` and `samples/sample-summary.csv` are rebuilt from `samples/sample-raw.json`, a run on 2026-10-19 for Desearch's own account with 3 pages. The public sample leaves out posts whose text links to other sites or names other products (they are dropped, not edited), so it has fewer posts than the live run. The live run's own numbers are in `samples/live-run-2026-10-19.md`.

## Tests

```bash
python -m unittest discover -s tests
```
