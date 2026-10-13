# Investor Topic Tracker

Made by [Desearch](https://desearch.ai).

Before a raise, you want to read what a list of investors has posted in public about your space. This script takes 10 to 15 X accounts (fund and firm accounts work well) and one topic, asks the Desearch API for each account's posts that match the topic, sorts them newest first in its own code, and writes a short reading list.

Output is the public posts Desearch returned for this handle and topic on the run date. It is a reading list, not a view on anyone's plans, and it sends nothing to anyone.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # create a key at console.desearch.ai
```

## Run

```bash
python investor_topic_tracker.py investors.json                          # live: 1 call per account
python investor_topic_tracker.py --from-raw evidence/raw-2026-10-13.json   # offline rebuild, no API calls
```

`investors.json` holds `topic`, `query` (the X search query sent for every account), `topic_terms` (words the script looks for in each post to count it) and `handles`. Options: `--count` (posts asked per account, default 20, max 100), `--out` (default `output`).

## Desearch service used

`GET https://api.desearch.ai/twitter/post/user` with header `Authorization: <key>` and query params `user` (the account), `query`, `count` (docs: https://www.desearch.ai/docs/api-reference/get-twitter-post-user, checked 2026-10-13). The response is a JSON list of posts with `id`, `text`, `created_at`, `like_count` and `user`.

## Output

- `output/investors.csv`: one row per account: posts returned, posts with a topic term, newest topic post date and link, last 30 days yes/no, median likes, the label used in the shortlist.
- `output/shortlist.md`: accounts ranked by their newest topic post, shown as Investor A, B, C.
- `evidence/raw-YYYY-MM-DD.json`: every response, for `--from-raw`.

## Sample output (2026-10-13, topic "AI agents", 12 fund accounts, count 20)

| # | Account | Posts with topic term / returned | Newest topic post (UTC) | Last 30 days |
|---|---|---|---|---|
| 1 | Investor A | 20 / 20 | 2026-10-12 17:45 | yes |
| 2 | Investor B | 14 / 20 | 2026-10-12 16:08 | yes |
| 3 | Investor C | 20 / 20 | 2026-10-09 17:33 | yes |

## Tips

- Put the OR group in parentheses: `("AI agents" OR "AI agent" OR agentic)`.
- Sort by `created_at` yourself; the script does this for you.
- Ask for 20 posts per account. Some accounts return fewer, which just means fewer matching posts came back.
- If an account returns nothing, check the handle spelling on X first.
