# TikTok Comments Export

Made by [Desearch](https://desearch.ai).

Turn a few TikTok video ids or links into one clean CSV of the public comments the Desearch API returned, plus a short summary (comments per page, a simple question / complaint / praise tag, top 10 by likes). One REST endpoint and one Python file.

## What it calls
- `GET /desearch/tiktok/comments/{video_id}?count=...`
- Paging: the response is a plain list with no cursor field. Passing the running offset as `cursor` (`10` for page 2, `20` for page 3 at count 10) worked in testing. The script dedupes anyway.
- Comments came back without an id field in testing, so the script builds a `comment_key` (short hash of the commenter id, time and text) to dedupe.

## Setup
```bash
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # from console.desearch.ai
```
(Or set `DESEARCH_KEY_FILE` to a file that holds the key.)

## Run
```bash
python tiktok_comments.py --videos 7166602323639225606 https://www.tiktok.com/video/7095449168591736070 --count 10 --pages 3
python tiktok_comments.py --from-raw path/to/your-saved-raw.json   # rebuild CSV offline from your own saved raw JSON, no API calls
```
Optional: `--empty-check <made-up-video-id>` makes one extra call to see how a video with no comments behaves.

Each comment returned is billed, so keep `--count` and `--pages` small while you try it. Check the cost headers on your first call.

## Output
`output/tiktok-comments-<label>.csv`, one row per unique comment:

`video_id, video_link, comment_key, viewer, text, likes, reply_count, create_time_utc, tag, page`

- Commenters are shown as `Viewer N`; `@mentions` in text become `[viewer]` and links become `[link]`.
- Video links are rebuilt from the id, with no account name in them.
- `reply_count` is blank when the API returns no reply data (it returned none in testing).
- `tag` is a simple keyword rule (question, complaint, praise or blank), a starting point for reading, not a classifier.

Sample (from a test run on 2026-10-16):
```
video_id,video_link,comment_key,viewer,text,likes,reply_count,create_time_utc,tag,page
7166602323639225606,https://www.tiktok.com/video/7166602323639225606,hccba6988db83,Viewer 1,you're so amazing and inspiring! you're the reason i'm not scared of my acne.,7380,,2022-11-16 13:37,praise,p1
```
