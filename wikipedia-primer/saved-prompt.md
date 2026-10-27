# Saved prompt: Wikipedia Primer

Paste into Cursor or Claude with the Desearch MCP server connected. Change the three bracketed lines first.

```
You are my research assistant. Build a short primer on the topic below using the Desearch tools. Do not answer from memory.

Topic: [carbon credits]
Who it is for: [a founder who needs the basics before a call tomorrow]
Web cross-check: [yes]

Step 1. Call the Desearch tool ai-search with:
- prompt: "[Topic]: what it is, how it works, key facts, criticism, and related topics"
- tools: ["wikipedia"]
- result_type: "LINKS_WITH_FINAL_SUMMARY"

Step 2. Clean the results before you write anything:
- Keep only real articles that are about the topic. Drop pages whose title only looks similar (different spelling, a plant, a horse, a chemical formula), and drop pages whose title starts with File:, Talk:, Category: or Wikipedia:.
- If a page is not in English, keep it but mark it (for example "French Wikipedia").
- If there is no English Wikipedia article about the topic, say so in one line at the top.
- Ignore the published_date field. For Wikipedia it is the date the page was created, not when it was last updated.

Step 3. Check the summary against the sources:
- Use a fact only if the snippet or highlights of the page it cites actually say it. If a number or claim is cited to a page that does not contain it, move it to the page that does, or leave it out.
- Never copy the summary's citation numbers. Put the page link right after each fact instead.

Step 4. If Web cross-check is yes, call the Desearch tool web-search with query "[Topic] explained". Keep Step 1 on Wikipedia only and use this separate call for the web. From the web results pick 2 or 3 pages from neutral sources (universities, public bodies, nonprofits, reputable news). Skip pages that sell the thing, and skip anything that looks like spam.

Step 5. Write the primer in this format:

## [Topic]: a primer
One-paragraph plain-English explanation (max 80 words).

### Key facts
5 to 7 bullets. Each bullet ends with its Wikipedia link in parentheses.

### Related Wikipedia pages
Up to 6 pages from Step 2, each with one line on why it matters, and the link.

### What to read next
3 links in reading order: start with the main article, then the best related page, then the best web page from Step 4 (or a third Wikipedia page if there was no cross-check). One line each on what the reader will get.

### Web cross-check
Only if Step 4 ran: say in one or two lines whether the web pages agree with the Wikipedia facts, and note any disagreement with both links.

### Notes
One line per problem you hit: missing English article, off-topic results you dropped, facts you removed because the cited page did not support them.

Every link must be copied exactly from a tool result. If the tools return nothing useful, say so plainly instead of writing from memory.
```
