# Use case: see what others say about your brand this month

Made by [Desearch](https://desearch.ai).

**Who:** a founder, marketer or PR person who wants a monthly list of third-party pages and X posts about their brand.

**Before:** searching the web and X by hand, skipping your own site, and pasting links into a spreadsheet.

**With the saved prompt:** one prompt in Claude or Cursor with Desearch MCP connected. It searches the web and X for the last 30 days, then drops links on your own domains and posts from your own account, and returns:

- a table of pages and posts with where, link, a short exact snippet, tone and date,
- a "left out" list, so you can see what was dropped and why.

Authors of X posts are shown as a user.

**Steps for the sample (2026-10-15), using Raycast, a Mac launcher app we are not connected with:**

1. Ran `ai-search` on web and X with the product type in the prompt, the last 30 days, and `result_type: "ONLY_LINKS"`. 10 web pages and 10 X posts came back. Some web pages were on the brand's own site.
2. Ran `x-search` with `(Raycast OR "raycast app") -from:raycast`, at least 5 likes, the last 30 days. 20 posts came back, none from the brand's own account.
3. Dropped links on the brand's own domain (6 of the 10 web pages), then read each item and labelled the tone. 1 post in 30 was about something else.

**What to expect:**

- These are public pages and posts Desearch returned for this search. Treat them as a sample of the conversation, not a full count.
- The search can return pages from your own site. The prompt drops them in step 3; check the domain column once more yourself.
- If your brand name is also a common word or a technical term, add what it is ("the Mac launcher app") to the prompt and read each row.

See the [saved prompt](saved-prompt.md) and the [sample](sample-output.md).
