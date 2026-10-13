# Posting Time Check (TikTok, Instagram, Facebook)

Made by [Desearch](https://desearch.ai).

Does posting time matter in my niche? Give the script your account plus 10 to 15 peer accounts. It pulls each account's recent public posts on TikTok, Instagram and Facebook with the Desearch API, scores every post against its own account's median engagement (so big accounts don't drown out small ones), and groups the scores by weekday and 4-hour block in the time zone you pick. Output: one heatmap per platform, a best-3 / worst-3 slot table, CSVs and the raw JSON.

The handles in `handles.json` are an example set: CoinDesk as the "main" account and 12 public crypto news, research and exchange brand accounts as peers. Swap in your own.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # create a key at console.desearch.ai
```

## Run

```bash
python posting_time_check.py handles.json                          # page 1 per account, count=30
python posting_time_check.py handles.json --pages 2                # one more page on TikTok and Instagram
python posting_time_check.py handles.json --tz UTC --platforms tiktok,instagram
python posting_time_check.py handles.json --pages 2 --reuse-raw output/raw-2026-10-09.json   # add page 2 to a saved run
python posting_time_check.py --from-raw output/raw-2026-10-09-p2.json   # offline, no API calls, no cost
```

`handles.json` has a `main` entry and a `peers` list, each with a `tiktok`, `instagram` and `facebook` name (`null` skips that platform). Options: `--count` (1 to 100, default 30), `--pages` (default 1), `--tz` (default Asia/Tbilisi), `--max-age-days` (default 90: only posts from the last 90 days are scored, and paging stops once a page reaches older posts).

Endpoints used:
- `GET https://api.desearch.ai/desearch/tiktok/profile/{username}/posts?count=N&cursor=...`
- `GET https://api.desearch.ai/desearch/instagram/profile/{username}/posts?count=N&cursor=...`
- `GET https://api.desearch.ai/desearch/facebook/profile/{profile_id}/posts?count=N`

## How the score works

- Engagement per post: TikTok likes + comments + shares; Instagram likes + comments; Facebook reactions + comments.
- Score = engagement / median engagement of that account's scored posts. 1.0 is a normal post for that account, 2.0 is twice its normal.
- A slot is weekday x 4-hour block. Only slots with 3 or more posts are ranked. The table shows how many posts and how many accounts sit behind each slot.
- `createTime` comes back as Unix seconds (TikTok, Instagram) or an ISO 8601 string (Facebook), all in UTC. The script converts to `--tz`.

## Paging

The response is a plain list with no next-page token. What worked in my test on 2026-10-09: on TikTok, `cursor` = the last post's `createTime` x 1000; on Instagram, `cursor` = the last post's `id`. One extra page per account was tested on 5 TikTok and 5 Instagram accounts. I found no cursor value that pages Facebook, so the script reads one Facebook page per account.

## Output (in `output/`)

- `<date>-report.md`: per-platform sample size, best/worst table, heatmaps, account table, cost line
- `<date>-heatmap-tiktok.png`, `-heatmap-instagram.png`, `-heatmap-facebook.png`
- `<date>-best-worst.csv`, `-slots.csv`, `-posts.csv`, `-accounts.csv`, `-costs.csv`
- `raw-<date>.json` (page 1) and `raw-<date>-p2.json` (pages 1 and 2): every response, for `--from-raw`

## Sample (measured on 2026-10-09, 09:36 to 09:41 Asia/Tbilisi, slots in Asia/Tbilisi)

- Posts per request at `count=30`: TikTok 10, Instagram 12, Facebook 3.
- 303 posts kept (TikTok 138, Instagram 144, Facebook 21); 245 scored (posts from the last 90 days): TikTok 99 from 5 accounts, Instagram 128 from 7 accounts, Facebook 18 from 6 accounts.
- Instagram best slot: Mon 20-24, median score 2.59 (10 posts, 3 accounts). Worst: Thu 16-20, 0.48 (9 posts, 4 accounts).
- TikTok best slot: Thu 00-04, 6.16 (4 posts, 2 accounts). Most ranked TikTok slots have 3 to 7 posts, so one viral post moves a slot.
- Facebook: 3 of 42 slots have 3 or more posts, too few to call a best time.
- 49 calls, 316 posts returned, 316 billed units, $0.6541 total from the `X-Desearch-Cost-Usd` headers ($0.00207 per post).

## Notes

- Check that each username really belongs to the brand before you run. In this example set, 4 TikTok usernames and 1 Instagram username that match a brand name belonged to unrelated personal accounts, and 1 Facebook name belonged to an unrelated business; they are set to `null` in `handles.json` and their posts were dropped.
- The result describes public engagement on the recent posts in this sample. It says nothing about reach, and a best slot for these 13 accounts is not a rule for other accounts.
