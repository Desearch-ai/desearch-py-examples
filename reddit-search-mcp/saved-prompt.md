# Saved prompt: Reddit Search in MCP

Made by Desearch, https://desearch.ai

Works in any MCP client connected to the hosted Desearch MCP server (`https://mcp.desearch.ai/mcp`, with your Desearch API key in the `Authorization` header). Setup: https://www.desearch.ai/docs/guide/sdk/mcp

Replace `<topic>` and paste:

```
Use the Desearch ai-search tool with tools ["reddit"] and result_type "LINKS_WITH_FINAL_SUMMARY" for: "<topic>".
Then give me:
1. A table of up to 10 threads: title, what the thread is about in one line, the main opinion, and the link.
   If a title comes back as "Welcome to Reddit", write the topic from the link instead.
2. The 3 most common questions people ask.
3. The 3 most common complaints.
Say plainly if fewer than 10 relevant threads came back, and mark any thread that is off-topic.
Do not name individual posters; say "a user".
```

Tested 2026-10-16 14:55 Asia/Tbilisi with the topic "What do people recommend for keeping houseplants alive in winter?": 10 reddit.com thread links, all on-topic, plus a short cited summary, $0.004 per run.
