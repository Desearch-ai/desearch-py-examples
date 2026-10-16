# How to use Desearch for social listening

Made by [Desearch](https://desearch.ai).

Social listening means checking what people say about a brand in public. As an analyst, I wanted a quick weekly sheet: what people posted on X, which posts got traction, and which websites show up for the brand name. I built it with two Desearch API endpoints and one Python script. Total build time was under an hour.

## What you need

- A Desearch API key from console.desearch.ai
- Python 3 and the `requests` library

## Steps

1. **Pick the brand and the query.** I used Duolingo. The X query was `(duolingo OR "duo owl") lang:en`. Put OR terms in parentheses so the language filter applies to both.
2. **Pull X posts.** Call `GET /twitter` twice: `sort=Latest&count=50` for the newest posts and `sort=Top&count=20` for the posts with the most traction, both with `start_date` set to 7 days ago.

   ```python
   import os
   import requests

   s = requests.Session()
   s.headers["Authorization"] = os.environ["DESEARCH_API_KEY"]
   q = '(duolingo OR "duo owl") lang:en'
   latest = s.get("https://api.desearch.ai/twitter", params={"query": q, "sort": "Latest", "count": 50, "start_date": since}).json()
   top = s.get("https://api.desearch.ai/twitter", params={"query": q, "sort": "Top", "count": 20, "start_date": since}).json()
   ```
3. **Pull web pages.** Call `GET /web?query=duolingo` with `start=0`, `10` and `20`, then drop duplicate URLs. Pages overlap, so de-duplication matters.
4. **Tag and count.** Mark each row on topic if the brand word is in the text, title, snippet or URL. Count posts by day, rank posts by likes plus reposts plus replies, and count web domains.
5. **Write the sheet.** Save `mentions.csv` for analysis and a short `report.md` for the team.

## What I got (2026-10-15)

- 69 unique public posts Desearch returned on X, 68 of them naming the brand.
- 38 unique web URLs over 3 pages, all naming the brand. 27 were the brand's own pages and app store listings, and 11 were third-party forum threads, videos, reviews and articles.
- The 50 newest posts covered about 2.5 hours, so Latest is a snapshot of right now. Top gives a better view of the week.

## Tips

- For "what are people saying", filter out the brand's own domains and app store listings from web results. The third-party rows are the ones worth reading.
- Keep the X query tight. A loose brand word that is also a common word will pull in unrelated posts.
- Show authors as Account A, Account B and so on when you share the sheet.
