# Holiday Promo Watch

Made by [Desearch](https://desearch.ai).

When do brands in your category start their Black Friday push, and on which channel first? This script takes a dated snapshot for a few brands with the Desearch API: the promo wording on their homepage, sale pages and Black Friday pages, their latest X, Instagram and TikTok posts, and a "<brand> black friday 2026" web search. Every run appends rows to `output/promo_timeline.csv`, so a daily re-run until Cyber Monday (2026-11-30) shows who moved first, where, and with what wording.

It reports the public posts and pages Desearch returned on the run date. It is not a list of every promotion.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # create a key at console.desearch.ai
```

## Run

```bash
python holiday_promo_watch.py brands.json                                  # one live snapshot, appends to output/promo_timeline.csv
python holiday_promo_watch.py --from-raw output/raw-2026-10-11.json        # offline rebuild, no API calls, no cost
```

`brands.json` lists each brand with its site, sale page URLs and its public X, Instagram and TikTok usernames. Leave a field empty (`""`) to skip that channel. Check each username first: a brand name is not always the brand's account on every platform (in our run, one TikTok and one X username that matched a brand name belonged to unrelated accounts, so we left those channels empty).

Options: `--since` (season start, default `2026-10-01`; post channels count posts from this UTC date), `--until` (default `2026-11-30`; later live runs exit without calling the API), `--count` (posts requested per Instagram and TikTok profile, default 30), `--x-count` (default 20), `--no-x-search`, `--bf-pages` (own-site Black Friday pages from the brand search to read, default 2), `--no-html-check`, `--generic-query` (default `black friday 2026`, `''` to skip), `--redact-file` (words to replace with `[redacted]` in saved titles, excerpts and links), `--full-raw <path>` (keep every response unchanged in a private file), `--reuse-raw <path>` (reuse posts from an earlier full raw of the same day and call only pages and search again), `--out` (default `output`).

## Endpoints used

- `GET https://api.desearch.ai/web/extract?url=<page>&format=text&js=false`: page text, retried once when no text comes back (both tries are logged)
- `GET https://api.desearch.ai/web/extract?url=<page>&format=html&js=false`: one html read per page; the script strips tags itself to read the page title, banners and promo strips
- `GET https://api.desearch.ai/twitter/user/posts?username=<handle>`: latest X posts (original posts; replies are not included)
- `GET https://api.desearch.ai/desearch/instagram/profile/<username>/posts?count=30`
- `GET https://api.desearch.ai/desearch/tiktok/profile/<username>/posts?count=30`
- `GET https://api.desearch.ai/twitter?query=(<brand>) ("black friday" OR "cyber monday" OR "early access" OR sale)&start_date=<since>&sort=Latest&count=20`: posts by any account that name the brand with promo words (OR terms kept in parentheses)
- `GET https://api.desearch.ai/web?query=<brand> black friday 2026&start=0`, plus one `GET /web` for the season query itself

## How it works

1. **Pages.** Homepage, every sale URL in `brands.json`, and up to 2 pages on the brand's own domain that the brand search returned with "black friday", "bfcm" or "cyber" in the title or URL. Each page gets a text read (retried once if empty) and an html read. When the text read is short (under 200 characters) or empty, the script also does one plain fetch of the page (browser User-Agent, no Desearch call) and records whether its HTML has visible text.
2. **Posts.** Latest posts per platform. Instagram and TikTok `createTime` is Unix seconds (UTC); X `created_at` is a date string. Pinned posts can come first on Instagram and TikTok, so the script counts them (`leading_out_of_order`) and sorts by date before it looks for the first signal.
3. **Promo wording.** Strong: black friday, cyber monday, bfcm, cyber week, early access, N% off, up to N%, use/promo/discount code, sitewide. Weak: sale, deal, discount, save $N, offer, markdown, clearance, limited time (these also appear in menus and everyday copy).
4. **First signal per channel.** For posts: the earliest post dated on or after `--since` with strong wording (or weak, if none is strong). For pages: whether the page shows the wording on the run date. For the brand search: whether a result on the brand's own domain carries offer wording (strong if it also names 2026).
5. **Timeline.** Rows for today's run replace any earlier rows of the same date; rows from other dates stay. `first_seen_run` is the first run date with a strong signal for that brand, channel and source.

## Output (in `output/`)

- `promo_timeline.csv`: one row per run date, brand, channel and source: what was checked, signal (strong / weak / none), the terms, the first signal post date and link, and a short excerpt. Append-friendly.
- `<date>-summary.md`: the first-signal table, "who moved first", channel counts and order, search results by year named, and cost.
- `<date>-snapshot.csv`: per brand and channel: items returned, newest and oldest dates, pinned posts at the top, Extract tries, html read and plain-fetch check for pages, search year counts.
- `<date>-signals.csv`: every post or page with promo wording (posts before `--since` are kept and marked `in_season=False`).
- `<date>-serp.csv`: every search result with rank, the latest year it names, own-site flag and promo terms.
- `<date>-costs.csv`: every call with status, items, billed units and the `X-Desearch-*` headers.
- `<date>-posts-chart.png`: posts per brand and channel by date, promo posts marked.
- `raw-<date>.json`: the run for `--from-raw` (post text keeps only the brand's own @handles; posts by other accounts keep only id, date and terms).

## Schedule daily re-runs until 2026-11-30

The script exits without calling the API after `--until`, so one cron line is enough. Example (09:00 every day, box time):

```cron
0 9 * * * cd /path/to/holiday-promo-watch && . .venv/bin/activate && DESEARCH_API_KEY=$(cat ~/.desearch_key) python holiday_promo_watch.py brands.json --until 2026-11-30 >> output/cron.log 2>&1
```

Remove the line after 2026-11-30. Each daily run of the sample below costs about $0.24 (measured: one full run on 2026-10-11, 35 calls, $0.2362), so 50 runs from 2026-10-11 to 2026-11-30 would be about $12 at that rate. Instagram and TikTok posts are most of it; drop a platform or a brand to spend less.

## Sample (measured on 2026-10-11, Asia/Tbilisi)

Five DTC brands (apparel, beauty, eyewear, footwear). Posts are from the 09:44 run, pages and search from the 09:48 run (`--reuse-raw`).

- Posts returned: X 78 (4 brands, 19 or 20 each), Instagram 60 (12 per brand with `count=30`), TikTok 40 (10 per brand with `count=30`), X search 10 (1 to 4 per brand). Posts dated 2026-10-01 or later: X 2, Instagram 35, TikTok 24.
- Posts came back newest first on every platform once pinned posts are set aside: pinned posts came first on 2 accounts (3 each), and one Instagram account had two posts 3 hours apart in swapped order.
- Pages: 12 read (5 homepages, 4 sale or offer pages, 3 Black Friday pages from the brand search). All 12 returned text after at most one retry. On 3 of the 12, the offer wording (for example "20% off, no promo code needed" or a "Black Friday Early Access Offer Terms" title) was found only in the html read, which is why the script does both reads.
- Strong promo wording on the run date: 6 pages on 4 brands' sites, and 1 Instagram post dated 2026-10-09 (a partner offer, not a holiday sale). No X or TikTok post dated 2026-10-01 or later had strong wording.
- Brand search: 90 results; 6 name 2025 or older, 43 name 2026, 41 name no year. Many coupon pages put the current month in their title, so "names 2026" does not mean the offer is new. "black friday 2026": 19 results, all naming 2026.
- Cost: the 09:44 full run was 35 calls, $0.2362; the 09:48 pages-and-search run was 32 calls, $0.0175 (sum of the `X-Desearch-Cost-Usd` headers).

## Notes

- Wrap OR terms in parentheses, as in `(<brand>) ("black friday" OR "early access")`.
- Instagram returned at most 12 posts and TikTok at most 10 per request in our run, so `count=30` gives the latest 12 and 10. Pinned posts take some of those slots.
- `/twitter/user/posts` returns original posts. A brand that mostly replies on X can look quiet there.
- Keep the html read on: in our run it found offer banners and page titles that the text read left out.
- The search returns no date per result; the script only reports the latest year a title, snippet or URL names.
