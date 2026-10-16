# Saved prompt: Who's Asking For It

Paste this into Claude (or Cursor chat) after the Desearch MCP server is connected. Edit the three lines in the brackets first.

```
You are my lead finder. Use only the Desearch tools to search; do not answer from memory.

My product: [a no-code email newsletter tool for small creators]
Words people use for it: [newsletter platform, newsletter tool, newsletter app, email newsletter software]
Time window: the last [30] days, ending today.

Goal: find recent public posts on X and Reddit where a real person is asking for a tool like mine, is unhappy with what they use now, or is about to switch. I want posts I could reply to today.

How to search:
1. Call x-search 3 times, each with start_date and end_date set to my time window, lang "en", and count 50. Use one phrase group per call, with quotes and uppercase OR, and add -filter:retweets:
   a. ("which newsletter platform" OR "what newsletter platform" OR "best newsletter platform" OR "newsletter platform recommendations")
   b. ("alternative to" OR "switching from" OR "moving my newsletter") newsletter
   c. ("recommend" OR "looking for" OR "suggestions") ("newsletter platform" OR "newsletter tool")
   Swap in my own words from above.
2. Call ai-search once with tools ["reddit"], result_type "ONLY_LINKS", and start_date / end_date set to my window, with a prompt like "people asking which [newsletter platform] to use, recommendations wanted".
3. Keep only posts where the author is asking for a tool, asking for help choosing, or complaining about their current tool and hinting they would switch. Drop announcements, job ads, promos, news articles and people selling something.
4. Check dates yourself. Drop any X post whose created_at is outside my window. Reddit results usually come back without a date: do not guess one. Put them in a separate list called "Reddit, date not confirmed".
5. Remove duplicates (same URL or same author saying the same thing).

Output:
A. A ranked table of the X posts, strongest buying intent first, with columns:
   Rank | Intent (High / Medium / Low) | Date posted | Who | What they said (one short line, paraphrased) | Link
   High = asking for a recommendation or ready to switch now. Medium = comparing options or open question. Low = loosely related.
B. "Reddit, date not confirmed": title and link only, max 10.
C. One line saying how many results each tool call returned and how many you kept.

Every row must have a working link copied exactly from the tool result. If a search returns nothing useful, say so plainly instead of padding the table.
```
