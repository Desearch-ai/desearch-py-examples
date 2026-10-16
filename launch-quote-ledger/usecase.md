# How to use Desearch to build a launch quote ledger

Made by [Desearch](https://desearch.ai).

When a product launches on X, the quote posts are where people say what they actually think. This guide shows how I built a small Python script that collects the quote posts of a launch post into a spreadsheet, using the Desearch API. Built on 2026-10-15.

## What you get

For each launch post: a table of who quoted it, when, how many likes, the text of the quote, and any disclosure wording found in public text (#ad, sponsored, partner and similar).

## Steps

1. **Get a key.** Sign up at console.desearch.ai and export it as `DESEARCH_API_KEY`.
2. **Pick launch posts.** I picked 3 launch posts from the past week (a developer tool, an ecosystem page, a learning product), with 41 to 99 quotes each.
3. **Load the launch post.** `GET /twitter/post?id=<post id>` returns the text, date and `quote_count`, so you know how many quotes to expect.
4. **Find the quotes.** Call `GET /twitter` with `query=quoted_tweet_id:<post id>`, `is_quote=true`, `sort=Latest` and `count=20`. `quoted_tweet_id:` is a search operator that worked in my testing; it is not listed as a documented feature. In my run all 60 results across the 3 launches quoted the right post. Each call took 1.3 to 3.6 s.
5. **Check and flag.** Keep results whose `quoted_status_id` equals the launch id, then scan the text for disclosure wording.
6. **Save.** Write a CSV and a Markdown table. Show quoters as Account A, B, C if you share the table.

```python
import os
import requests

key = os.environ["DESEARCH_API_KEY"]
params = {"query": f"quoted_tweet_id:{post_id}", "is_quote": "true", "count": 20, "sort": "Latest"}
quotes = requests.get(
    "https://api.desearch.ai/twitter",
    params=params,
    headers={"Authorization": key},
).json()
quotes = [q for q in quotes if str(q.get("quoted_status_id")) == post_id]
```

## Tips

- Use `quoted_tweet_id:` in the query. Searching the author's handle with `is_quote=true` mixes in quotes of the author's other posts.
- Add `blue_verified=true` to keep only verified quoters.
- For larger launches, raise `count`. With `count=50` on a launch with 99 quotes I got 40 quotes back in one call, so plan for fewer than requested.
- Read flagged quotes by eye. In my run both flagged quotes were not disclosures ("Not sponsored, just sharing", and "partner integrated with" describing the product).
- Keep the raw JSON. The script can rebuild the ledger offline with `--from-raw`.

## Cost to start

Fetching a post and pulling 20 quotes cost me well under one cent per launch.
