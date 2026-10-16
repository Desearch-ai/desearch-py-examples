# Sample output

Lookup run on 2026-10-16 at 15:06 Asia/Tbilisi: username `desearch_ai`, 3 pages. Cost $0.00765 for 3 calls (header total).

Profile card: Desearch.ai | Subnet 22, 1,725 followers, 76 following, 681 posts, joined 2025-01-14.

Stats: 48 posts from 2026-09-24 16:04 to 2026-10-15 16:07 UTC, 2.29 per day, median likes 4. Pages returned 17, 16 and 18 posts; 3 repeated across pages and were dropped.

| created_utc | kind | text (trimmed) | likes | replies | link |
|---|---|---|---|---|---|
| 2026-10-15 16:07 | post | Builder tip: one Desearch web search call can ask for page text and a publish-date window together ... | 4 | 0 | https://x.com/i/status/2110764481857114194 |
| 2026-10-15 14:02 | post | Most web agents run the same loop: find pages, then read them. With Desearch that is two GET calls ... | 4 | 1 | https://x.com/i/status/2110732993300148437 |
| 2026-10-15 14:02 | reply | Every billable response carries X-Desearch-Cost-Usd and X-Desearch-Usage-Count headers ... | 1 | 1 | https://x.com/i/status/2110733042272833853 |

Full files: `samples/page.html`, `samples/posts.csv`, `samples/lookup-summary.json`.

## Not found
Username `qzxvplornb26nx` (no such account): HTTP 404 `User not found or unavailable`, cost $0, 0.81 s. The app shows "No public X account found for that username."
