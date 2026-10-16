# Saved prompt: Podcast Guest Shortlist

Made by [Desearch](https://desearch.ai).

Paste this into Claude or Cursor with the Desearch MCP server (`https://mcp.desearch.ai/mcp`) connected. Send your API key in the `Authorization` header as `Bearer <key>`. Fill in the lines at the top. Pick a niche, non-political topic.

```text
TOPIC TERMS: sourdough OR levain OR "bread baking"
TOPIC NAME: sourdough
TODAY: 2026-10-14

You build a podcast guest shortlist from public posts and pages Desearch returned for this search. The host reviews it and reaches out personally. Never draft outreach messages and never look for contact details.

1. Search. Call x-search with:
   {"query": "(TOPIC TERMS)", "start_date": <TODAY minus 30 days>, "end_date": TODAY, "min_likes": 20, "count": 50}
   Keep the OR group in parentheses exactly as written. Note how many posts came back.

2. Pick people.
   - Drop posts dated before start_date.
   - Drop brands, shops, recipe pages, news accounts and anything that looks automated. Label each account yourself: person, brand, or bot.
   - Drop political figures and posts that only mention the topic in passing.
   - Keep up to 15 different people, most on-topic first.

3. Confirm. For each person call x-posts-by-user with:
   {"user": "<account from step 2>", "query": "(TOPIC TERMS)", "count": 10}
   Sort the posts by date yourself. Count how many are about the topic and how many are from the last 30 days. Mark anyone with only one on-topic post as "one post only".

4. Past podcasts. For each person call web-search with "<display name> podcast".
   If the pages are about other people with the same name, run "<display name> TOPIC NAME podcast" once.
   Keep only pages that are clearly this person as a guest or host. Otherwise write "none found".

5. Output.
   - First line: "Public posts and pages Desearch returned for this search on <date>: <n> posts, <n> people checked."
   - Table: person | on-topic posts (count, newest date) | past podcast pages or "none found" | person or brand | pitch angle (one line, based only on their posts)
   - Call each person "a user". Do not print account names or personal post links.
   - A "skipped" list with one line each and the reason.
   - A reminder: the host reviews each row and reaches out personally.
```
