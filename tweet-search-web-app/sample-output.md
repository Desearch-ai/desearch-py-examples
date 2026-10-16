# Sample output

Search run on 2026-10-16 at 14:51 Asia/Tbilisi: `desearch` with any of `bittensor, subnet`, sort Latest, count 15. The app sent `desearch (bittensor OR subnet)`.

Result note: `15 of 15 requested posts returned in 5.55 s.` Cost $0.00225.

| created_utc | text (trimmed) | likes | replies | link |
|---|---|---|---|---|
| 2026-10-15 16:25 | Sunrise Digest · 2026-10-15 REAX Surges 558% as Smart Money Flows into Engy & Green Compute ... | 3 | 0 | https://x.com/i/status/2110769039865712878 |
| 2026-10-15 16:07 | Builder tip: one Desearch web search call can ask for page text and a publish-date window together ... | 4 | 0 | https://x.com/i/status/2110764481857114194 |
| 2026-10-15 15:54 | Which subnets win when gamma tokens go live? We mapped the subnets other subnets will actually pay to use ... | 36 | 1 | https://x.com/i/status/2110761337621995657 |
| 2026-10-15 14:02 | Every billable response carries X-Desearch-Cost-Usd and X-Desearch-Usage-Count headers ... | 1 | 1 | https://x.com/i/status/2110733042272833853 |

Full files: `samples/page.html`, `samples/tweets.csv`.

## Filter checks (same base query `bitcoin`, 20 posts each)
| Filter | Returned | Rows outside the filter |
|---|---|---|
| lang=es | 20 | 0 |
| min_likes=100 (Top) | 19 | 0 |
| min_replies=20 (Top) | 20 | 0 |
| min_retweets=50 (Top) | 20 | 0 |
| blue_verified | 20 | 0 |
| is_video | 20 | 0 |
| is_image | 20 | 1 (no photo in the returned media) |
| is_quote | 20 | 0 |
| 2026-10-10 to 2026-10-12 | 20 | 0 (all on 2026-10-12) |

Full data: `samples/filter-checks.json`.
