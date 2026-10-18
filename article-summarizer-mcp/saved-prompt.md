# Saved prompt: Article Summarizer (Desearch MCP)

Made by Desearch, https://desearch.ai

Works in an MCP client such as Claude or Cursor, connected to the hosted Desearch MCP server (`https://mcp.desearch.ai/mcp`, with your Desearch API key in the `Authorization` header). Setup: https://www.desearch.ai/docs/guide/sdk/mcp

Replace `<link>` and paste:

```
Summarize this article for me: <link>

1. Use the Desearch extract tool on that link with format "text" and js false.
2. If extract returns an error, fewer than about 150 words, or a login or sign-up page, stop. Tell me "Desearch could not read enough of this page to summarize it", show me what came back, and do not guess. If the error says "No content found", you may try extract once more.
3. Otherwise, using only the extracted text:
   - Give the article's topic in one line.
   - Write 5 bullets with the main points, in plain words. Each bullet must be something the text says.
   - Under "Numbers mentioned", list each figure in the text (amounts, percentages, counts) with the sentence it came from, quoted exactly as written.
   - Do not add facts, numbers or names that are not in the text. Do not name social media accounts.
4. Optional: use the Desearch ai-search tool with tools ["web"] and result_type "ONLY_LINKS" for: "news and articles about: <the topic from step 3>". List up to 2 links from other sites that cover the same story, with their titles. If none of them is about the same story, say so.
```

Tested 2026-10-18 16:03 Asia/Tbilisi on a Guardian news article: extract returned 616 words of article text, and the summary in `sample_summary.md` was written from that text only. The extract call cost $0.0005 on the REST price and the optional ai-search call cost $0.004.
