# Saved prompt: X Keyword Monitor

Made by [Desearch](https://desearch.ai).

Paste this into Claude or Cursor with the Desearch MCP server (`https://mcp.desearch.ai/mcp`) connected. Send your API key in the `Authorization` header as `Bearer <key>`. Fill in the lines at the top. Update LAST CHECK each time from the last line of the output.

```text
KEYWORDS: "home espresso" OR "espresso machine" OR "latte art"
MIN LIKES: 5
LAST CHECK: 2026-10-14 11:35 UTC
NOW: 2026-10-15 11:35 UTC

You report new public X posts Desearch returned for these keywords since LAST CHECK.

1. Search. Call x-search with:
   {"query": "(KEYWORDS)", "start_date": <date of LAST CHECK>, "end_date": <date of NOW>, "min_likes": MIN LIKES, "count": 20}
   Keep the OR group in parentheses exactly as written. Note how many posts came back.

2. Filter.
   - Keep only posts created after LAST CHECK.
   - Drop posts whose text has none of the keywords, and posts that are only a link.
   - Sort what is left newest first.

3. Output.
   - First line: "Public posts Desearch returned for these keywords between LAST CHECK and NOW: <n> returned, <n> new, <n> kept."
   - Table: time (UTC) | keyword matched | likes | short excerpt (exact words, max 20) | link
   - "Summary": 3 lines on what people talked about, based only on the kept posts.
   - Last line: "Next LAST CHECK: NOW".
   - Show authors of X posts as "a user".
```
