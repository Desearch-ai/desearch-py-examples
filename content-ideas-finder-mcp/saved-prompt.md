# Saved prompt: Content Ideas Finder (Desearch MCP)

Made by Desearch, https://desearch.ai

Works in an MCP client such as Claude or Cursor, connected to the hosted Desearch MCP server (`https://mcp.desearch.ai/mcp`, with your Desearch API key in the `Authorization` header). Setup: https://www.desearch.ai/docs/guide/sdk/mcp

Replace `<niche>` (two places) and paste:

```
My niche is: <niche>

1. Use the Desearch ai-search tool with tools ["reddit"] and result_type "LINKS_WITH_FINAL_SUMMARY" for: "questions beginners ask about <niche>".
2. If my niche is about tech, software, startups or online business, run the same search again with tools ["hackernews"]. Otherwise skip this step.
3. Use the Desearch x-search tool with count 20 and this query (keep the parentheses):
   (<niche>) ("how do i" OR "how do you" OR "any tips") lang:en -is:retweet

Then, using only what those searches returned:
- List up to 10 questions that come up most. Give each one source link, and the date if the result shows one.
  If a Reddit result has a generic title, read the question from the words in its link.
- For each question, write one post idea: a title, a one-line hook, and a format (thread, carousel or short video).
- Show it as a table: question, post idea, hook, format, source link, date.
- Say plainly if fewer than 10 real questions came back. If the search summary says the sources do not mention my niche, tell me nothing useful was found instead of making a plan.
- Do not invent questions, sources or links. Do not name individual posters; say "a user".
```

Tested 2026-10-17 09:26 Asia/Tbilisi with the niche "starting a newsletter": the three searches returned 10 Reddit threads, 10 Hacker News threads and 20 X posts, enough for a 10-row plan (see `sample_plan.md`). The two ai-search calls cost $0.004 each.
