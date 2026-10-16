Paste into Cursor or Claude with the Desearch MCP server connected. Change the page list first.

# Saved prompt 1: build my pricing table

You are my pricing analyst. Read the pricing pages below with the Desearch tools and build one table. Do not use anything you remember about these companies. Use only the page text the tool returns.

Pages:
- [https://linear.app/pricing]
- [https://www.figma.com/pricing/]
- [https://slack.com/pricing]

For each page:
1. Call the Desearch tool extract with {"url": "<page>", "format": "text", "js": false}.
2. If the text comes back empty or almost empty, wait a few seconds and call extract once more with the same arguments. If it is still empty or has no prices, write "No prices in page text" for that page and move on.
3. Read the plans in order. If a price appears without a plan name above it, write the plan as "(name not in page text)" rather than borrowing the name of the plan before it.
4. If two prices are glued together (for example "$8.75$4.38"), check the nearby words. A promo ("50% off for 3 months") means the first number is the normal price and the second is the promo price. Report both and say which is which.

Build one table with these columns:
Tool | Plan | Monthly billing price | Annual billing price (per month) | Key limits | Free tier | Snapshot date

Rules:
- Prices exactly as written on the page, with the unit (per user / month, per seat, flat). If the page only shows one billing period, put "not shown" in the other column.
- Key limits: up to 3 per plan, copied from the page text (users, storage, history, credits, projects).
- Free tier: "yes" with its main limit, or "no".
- Snapshot date: today's date.
- Every cell must come from the page text. If something is missing, write "not in page text".

After the table, add:
- "Pages with problems": one line per page that came back empty or partial.
- "Read me first": anything a person should double check on the live page (promo prices, missing plan names, prices that depend on team size).

# Saved prompt 2: compare with my last table

You are my pricing analyst. Below is the pricing table I saved last time. Re-read the same pages with the Desearch tool extract ({"url": "<page>", "format": "text", "js": false}), build today's table with the same rules as before, then compare.

My last table:
[paste your last table here, including its snapshot date]

Report only:
1. "Changes": one line per real change, as Tool | Plan | What changed | Before | Now. Real changes are: a price, a plan added or removed, a plan renamed, a limit or free tier changed, a promo started or ended.
2. "No changes": list the tools where nothing in the table changed. If nothing changed anywhere, say "No pricing changes since <last date>" in one line.
3. "Could not check": pages that came back empty or partial today, so they are not counted as "no change".

Ignore noise that is not a pricing change: customer logos and quotes, headlines and marketing copy, banner text, dates, cookie notices, the order of features, and wording changes that do not change a price or limit.

Then print today's full table so I can save it for next time.
