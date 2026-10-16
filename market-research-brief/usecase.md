# How to use Desearch for a quick market research brief

Made by [Desearch](https://desearch.ai).

As an analyst, I often need a first look at a consumer market before a longer study: which brands come up, what buyers worry about, and what prices people talk about. I built a short brief for home espresso machines with two Desearch API endpoints and one Python script. The brief describes the pages and posts Desearch returned, not the whole market.

## What you need

- A Desearch API key from console.desearch.ai
- Python 3 and the `requests` library

## Steps

1. **Pick a market and a buyer-style query.** I used `best home espresso machine`, the kind of phrase a shopper types.
2. **Pull several pages of web results.** Call `GET /web` with `start=0`, `10`, `20` and `30`. Pages overlap, so keep a set of URLs and drop repeats. Check the count of new URLs per page; if a page adds nothing, move on to the next `start`.

   ```python
   import os
   import requests

   s = requests.Session()
   s.headers["Authorization"] = os.environ["DESEARCH_API_KEY"]
   seen = {}
   for start in (0, 10, 20, 30):
       for r in s.get("https://api.desearch.ai/web", params={"query": q, "start": start}).json()["data"]:
           seen.setdefault(r["link"], r)
   ```
3. **Set aside store and brand pages.** Keep a short list of shop and manufacturer domains in a config file. Those pages sell; you want reviews and buyer discussion.
4. **Read the top pages.** Call `GET /web/extract` with `format=text` and `js=false` on the first dozen remaining URLs. Some pages come back with no text and some with only a menu or a login screen, so skip anything under 200 characters.
5. **Add a few recent posts.** `GET /twitter` with `("espresso machine" OR "espresso maker") lang:en`, `sort=Latest`, `count=20`. Put OR terms in parentheses so the language filter applies to both.
6. **Count and write.** Count which brands each page names, which concern terms appear (temperature, steam wand, cleaning, leaks), and pull dollar amounts. Write a one-page `brief.md` with the source list.

## What I got (2026-10-15)

- 79 web results across 4 pages, 44 unique URLs.
- 12 pages requested for text, 8 with usable text.
- Brands named on the most pages: Breville (4), Gaggia (3), Bambino (3), De'Longhi and Rancilio (2 each).
- Concern terms on the most pages: temperature and pressure (6 each), grinder (5), steam wand, cleaning and price (4 each).
- Only 5 dollar amounts in the page text, so price needs a dedicated query.
- One run took about 35 seconds.

## Tips

- Generic words in your query pull in unrelated pages. Check titles for your core word (here "espresso") and drop the rest.
- Read the source list before you trust the counts. A brief built on 8 pages is a starting point.
- Save the raw responses. The script has `--from-raw` so you can rebuild the brief without new calls.
