# Comment Voice-of-Customer Report (Desearch API example)

Made by Desearch. Built with the [Desearch API](https://desearch.ai) (https://desearch.ai).

A small Python CLI. Give it a public brand handle on Instagram and/or TikTok. It pulls the brand's newest posts, pulls the public comments on each post, and sorts every comment into **questions, complaints, feature / product requests, praise and other**. You get a Markdown report (counts per bucket, the 5 most-liked comments per bucket with post links) and a CSV of every comment.

It reads public comments only. It does not read private messages or DMs, and it does not post anything.

## Setup

Run the commands in this README from the `comment-voc-report` folder.

Python 3.10 or newer.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai
```

Environment variables (names only):

| Variable | Needed for |
|---|---|
| `DESEARCH_API_KEY` | every run |
| `VOC_LLM_BASE_URL`, `VOC_LLM_API_KEY`, `VOC_LLM_MODEL` | only with `--classifier llm` (optional) |

## Run

```bash
python vocreport.py --instagram duolingo --tiktok duolingo
```

Output goes to `runs/<timestamp>-<handle>/`:

- `report.md`: counts per bucket, top 5 most-liked comments per bucket with post links, the posts covered, field fill rates
- `comments.csv`: every comment (`platform, brand, post_id, post_url, post_created_utc, key, comment_id, created_utc, likes, replies, author, bucket, rule, text`)
- `run.json`: every Desearch call with status, items returned and cost
- `raw/`: raw API responses (the key is never written; add `--no-raw` to skip)

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--instagram USER` / `--tiktok USER` | | public username without `@`; one or both |
| `--posts N` | 10 | newest posts per platform (pinned posts are dropped) |
| `--comments N` | 30 | comments requested per post (1-100); see limits below |
| `--classifier` | `keyword` | `keyword`, `llm`, or `module:ClassName` for your own |
| `--max-spend USD` | 1.50 | stop pulling comments once the run has cost this much |
| `--from-run DIR` | | re-sort a saved run with another classifier, no API calls |
| `--out DIR` | `runs` | output folder |

Offline checks (no API calls, no cost): `python test_vocreport.py`.

## How it works

1. `GET https://api.desearch.ai/desearch/instagram/profile/{username}/posts?count=N+3` and/or `GET .../desearch/tiktok/profile/{username}/posts?count=N+3`. This list is not strictly newest first: an old post (it behaves like a pinned post, there is no pinned field) came first on both platforms. So the CLI asks for 3 extra, drops any post in the top 3 that is older than a post after it, and keeps the newest N.
2. For each post: `GET .../desearch/instagram/comments/{shortcode}?count=30` or `GET .../desearch/tiktok/comments/{video_id}?count=30`. Header: `Authorization: <your key>`.
3. Every comment goes through a classifier. The default is ordered keyword rules (first match wins: request, complaint, question, praise, otherwise other). They are English first, with a few Spanish, Portuguese and Russian words.
4. Ranking and writing the report happen locally.

### Plug in your own classifier

Any class with a `classify(comments)` method that returns one `(bucket, reason)` pair per comment works:

```python
# myrules.py
class Mine:
    name = "mine"
    def classify(self, comments):
        return [("question" if "?" in c.text else "other", "mine") for c in comments]
```

```bash
python vocreport.py --tiktok duolingo --classifier myrules:Mine
python vocreport.py --from-run runs/<run-folder> --classifier myrules:Mine   # re-sort without paying again
```

`--classifier llm` sends comment texts in batches of 25 to a `/chat/completions` endpoint that you configure with the three `VOC_LLM_*` variables. If a batch fails, that batch falls back to the keyword rules. I tested this step only against a local stub server (`test_vocreport.py`), not a hosted model.

## What I measured (2026-10-06, Asia/Tbilisi)

Cost comes from the `X-Desearch-Cost-Usd` and `X-Desearch-Usage-Count` response headers on each call.

- **Price:** $0.00207 per item returned, on every billed call today (Instagram and TikTok profile posts and comments).
- **Billing follows items returned, not `count`.** `GET /desearch/tiktok/comments/{video_id}?count=30` returned 15 comments and billed 15 units ($0.03105). On a public video with 1 comment it billed 1 unit ($0.00207).
- **Empty is free.** `GET /desearch/tiktok/comments/{video_id}?count=30` on a public video with 0 comments returned HTTP 200 `[]` with cost 0.
- **One brand on both platforms with the defaults** (10 posts each, `count=30`): 23 calls, 322 items, **$0.66654** (run at 09:29, @duolingo, including one retried call that was not billed).

## Limits to know

All tested on 2026-10-06 with @duolingo:

- **About 15 comments per post.** `GET /desearch/instagram/comments/{media_id}?count=30` returned 13 to 15 comments per post (10 posts), even on posts showing thousands of comments. `GET /desearch/tiktok/comments/{video_id}?count=30` returned 13 to 19. `count=20` on TikTok also returned 15. You are billed for what comes back.
- **No paging for comments.** The comment response is a plain JSON array with no next-page cursor. On `GET /desearch/instagram/comments/{media_id}?count=5`, sending a `cursor` returned the same first 5 comments. On `GET /desearch/tiktok/comments/{video_id}`, a numeric `cursor` shifted the list but the pages overlapped. The CLI makes one call per post.
- **Instagram comments come back newest first.** Across 10 posts (`GET /desearch/instagram/comments/{media_id}?count=30`), 132 of 144 comments had 0 likes, so "most-liked" on Instagram means "most-liked among the newest ~15".
- **TikTok comments have no `id`.** `GET /desearch/tiktok/comments/{video_id}?count=30` returned no `id` on 156 of 156 comments. The CLI builds a key from `author.id` and `createTime`.
- **`createTime` has two formats.** On `GET /desearch/instagram/comments/{media_id}?count=30`, comments use an ISO string. On `GET /desearch/tiktok/comments/{video_id}?count=30`, comments use epoch seconds. The CLI turns both into UTC ISO.
- **`replies` was always empty** on all 300 comments (`GET /desearch/instagram/comments/{media_id}?count=30` and `GET /desearch/tiktok/comments/{video_id}?count=30`), so the CLI does not count replies.
- **Profile posts return fewer than asked.** `GET /desearch/tiktok/profile/{username}/posts?count=13` returned 10 posts and `GET /desearch/instagram/profile/{username}/posts?count=13` returned 12 (billed as returned).
- **Wrong usernames.** A nonexistent Instagram username returns HTTP 200 with an empty list (`GET /desearch/instagram/profile/{username}/posts?count=5`), so the CLI prints "no public posts found (check the username)". A nonexistent TikTok username returns HTTP 404 (`GET /desearch/tiktok/profile/{username}/posts?count=5`). Neither was billed.
- **Retry.** `GET /desearch/instagram/comments/{media_id}?count=30` returned HTTP 503 `Service request failed` on 2 of my 20 calls, not billed, and worked on retry. The CLI retries once after 5 seconds.

## Files

- `vocreport.py`: the CLI
- `test_vocreport.py`: offline checks (rules, full pipeline on inline fixtures, LLM step against a local stub)
- `requirements.txt`: `requests`
- `sample-output.md`: real report from the @duolingo run
