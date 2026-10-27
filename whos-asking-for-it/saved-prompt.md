# Saved prompt: Who's Asking For It (social listening on X)

Paste this into Claude (or Cursor chat) after the Desearch MCP server is connected. Edit the three lines in the brackets first.

```
You are my social listening assistant. Use only the Desearch tools to search; do not answer from memory.

My topic: [email newsletter tools for small creators]
Words people use for it: [newsletter platform, newsletter tool, newsletter app, email newsletter software]
Time window: the last [30] days, ending today.

Goal: show me what people are saying in public on X about my topic, in their own words. Group the posts by what the person is doing, so I can read the conversation quickly.

How to search:
1. Call x-search 3 times, each with start_date and end_date set to my time window, lang "en", and count 50. Use one phrase group per call, with quotes and uppercase OR, and add -filter:retweets:
   a. ("which newsletter platform" OR "what newsletter platform" OR "best newsletter platform" OR "newsletter platform recommendations")
   b. ("alternative to" OR "switching from" OR "moving my newsletter") newsletter
   c. ("recommend" OR "looking for" OR "suggestions") ("newsletter platform" OR "newsletter tool")
   Swap in my own words from above.
2. Call ai-search once with tools ["reddit"], result_type "ONLY_LINKS", and start_date / end_date set to my window, with a prompt like "people discussing [newsletter platforms], questions and opinions".
3. Check dates yourself. Drop any X post whose created_at is outside my window. Reddit results usually come back without a date: do not guess one. Put them in a separate list called "Reddit, date not confirmed".
4. Remove duplicates (same URL or same author saying the same thing). Drop posts that have nothing to do with my topic.
5. Read each post in full and put it in one group:
   - Asks: the person asks a question or asks for help or suggestions.
   - Complaints: the person is unhappy with something about the topic.
   - Opinions: the person shares an experience, a view or a comparison.
   - Promo and news: announcements, launches, ads, threads selling something, news posts.

Output:
A. One table per group, newest post first, with columns:
   Date posted | Who | What they said (one short line, paraphrased) | Link
   Skip a group if it has no posts and say so in one line.
B. "Reddit, date not confirmed": title and link only, max 10.
C. Three short lines on what people seem to care about most in this window, based only on the posts above.
D. One line saying how many results each tool call returned and how many you kept.

Each row must have a working link copied exactly from the tool result. If a search returns nothing useful, say so plainly instead of padding the tables.
