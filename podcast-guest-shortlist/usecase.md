# Use case: find podcast guests who already talk about your topic

Made by [Desearch](https://desearch.ai).

**Who:** a podcast host or producer on a niche show who needs fresh guests every week.

**Before:** scrolling X for people who post well about the topic, then searching each name to see if they have been on a show before.

**With the saved prompt:** one prompt in Claude or Cursor with Desearch MCP connected. It searches public X posts on your topic from the last 30 days with at least 20 likes, checks each person's own posts on the same topic, searches the web for past podcast pages, and returns:

- a table of up to 15 people with how often they post on the topic, past podcast pages found or "none found", and a one-line pitch angle based only on what they posted,
- a "skipped" list for brands and one-off posts.

Each person is shown as a user.

**Steps for the sample (2026-10-14), using home sourdough baking:**

1. Ran `x-search` with `(sourdough OR levain OR "bread baking")`, `min_likes: 20`, the last 30 days, `count: 50`. 50 posts came back.
2. Picked 15 accounts and labelled them by reading: 13 people, 2 brand-style accounts.
3. Ran `x-posts-by-user` for each with the same topic query. 14 of 15 had 6 or more posts on the topic.
4. Ran `web-search` for "<name> podcast". It found past podcast pages for 4 people. For one common name, adding the topic ("<name> sourdough podcast") found the right person's episode.

**What to expect:**

- Accounts without a public name are hard to look up on the web. Mark them "none found" and decide yourself.
- Common names match other people. Add the topic word and check each page.
- Sort each person's posts by date yourself; older posts can come first.

**Before you reach out:**

- The host reaches out personally, one person at a time. The prompt does not write or send messages and does not look for contact details.
- Say what it is: public posts and pages Desearch returned for this search, not a list of people who are open to guesting.

See the [saved prompt](saved-prompt.md) and the [sample shortlist](sample-output.md).
