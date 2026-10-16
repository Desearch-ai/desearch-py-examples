# Use case: a daily X keyword check without a dashboard

Made by [Desearch](https://desearch.ai).

**Who:** a founder, marketer or community manager who wants to see what people posted on X about a few keywords since yesterday.

**Before:** typing the same searches into X every morning and scrolling past posts already seen.

**With the saved prompt:** one prompt in Claude or Cursor with Desearch MCP connected. You keep a "last check" time at the top. Each run searches public X posts for your keywords since that time, drops what you already saw, and returns:

- a table of new posts, newest first, with likes, a short exact excerpt and a link,
- a 3-line summary of what people talked about,
- the time to paste in as your next "last check".

Authors of X posts are shown as a user.

**Steps for the sample (2026-10-15), using home espresso keywords:**

1. Ran `x-search` with `("home espresso" OR "espresso machine" OR "latte art")`, `min_likes: 5`, from 2026-10-14 to 2026-10-15, `count: 20`. 20 posts came back.
2. Kept the 12 posts newer than the last check, dropped 1 link-only post, and sorted the rest newest first. 11 kept.
3. The same search over REST is `GET /twitter` with `sort=Latest`, so a scheduled run comes back newest first.

**What to expect:**

- These are public posts Desearch returned for this search. Treat it as a sample of the conversation, not a full count.
- Single words pull in unrelated posts. Use phrases.
- Posts come in many languages. Add a language note to the prompt if you only want one.

See the [saved prompt](saved-prompt.md) and the [sample run](sample-output.md).
