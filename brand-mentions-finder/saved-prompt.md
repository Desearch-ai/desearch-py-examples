# Saved prompt: Brand Mentions Finder

Made by [Desearch](https://desearch.ai).

Paste this into Claude or Cursor with the Desearch MCP server (`https://mcp.desearch.ai/mcp`) connected. Send your API key in the `Authorization` header as `Bearer <key>`. Fill in the lines at the top.

```text
BRAND: Raycast
WHAT IT IS: the Mac launcher app
BRAND TERMS: Raycast OR "raycast app"
OWN ACCOUNT: raycast
OWN DOMAINS: raycast.com
TODAY: 2026-10-15

You list public pages and posts Desearch returned that mention BRAND, written by others.

1. Web and X. Call ai-search with:
   {"prompt": "Third-party reviews, articles and posts that mention BRAND, WHAT IT IS, from the past month",
    "tools": ["web", "twitter"], "result_type": "ONLY_LINKS",
    "start_date": "<TODAY minus 30 days>T00:00:00Z", "end_date": "<TODAY>T23:59:59Z"}
   Results can include pages on OWN DOMAINS. Step 3 removes them.

2. More X posts. Call x-search with:
   {"query": "(BRAND TERMS) -from:OWN ACCOUNT", "start_date": <TODAY minus 30 days>, "end_date": TODAY, "min_likes": 5, "count": 20}
   Keep the OR group in parentheses exactly as written.

3. Clean up.
   - Drop any link on OWN DOMAINS or their subdomains, and any post from OWN ACCOUNT.
   - Drop duplicates (same link twice).
   - Read each item and drop it if BRAND means something else there. List it under "left out".

4. Output.
   - First line: "Public pages and posts Desearch returned for BRAND on <date>: <n> web, <n> X, <n> kept."
   - Table: where (site or "X") | link | snippet (exact words, max 25) | tone (positive, neutral, negative) | date
   - "Left out": one line each with the reason.
   - Show authors of X posts as "a user".
```
