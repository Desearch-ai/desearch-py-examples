# Hashtag Shortlist (TikTok + Instagram)

Made by [Desearch](https://desearch.ai).

Give it a niche and 8 to 10 candidate hashtags. For each tag it pulls the top public posts on TikTok and Instagram with the Desearch API hashtag endpoints, then ranks the tags per platform on median likes per post, share of posts from the last 30 days, and how many different creators appear. Output: a ranked table per platform, a "use these 5" line per platform, CSVs and a scatter chart (median likes vs freshness).

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # create a key at console.desearch.ai
```

## Run

```bash
python hashtag_shortlist.py "home gym" homegym garagegym homeworkout homegymsetup garagegymlife homefitness workoutfromhome powerrack
python hashtag_shortlist.py "home gym" homegym garagegym --count 20 --platforms tiktok
python hashtag_shortlist.py --from-raw output/raw-2026-10-07-home-gym.json   # offline, no API calls, no cost
```

Pass tags without `#`. `--count` is 1 to 20 (default 15).

Endpoints used:
- `GET https://api.desearch.ai/desearch/tiktok/hashtag/{tag}?count=N`
- `GET https://api.desearch.ai/desearch/instagram/hashtag/{tag}?count=N`

## Output (in `output/`)

- `<date>-<niche>-shortlist.md`: ranked tables + "use these 5" lines + cost line
- `<date>-<niche>-ranked.csv`, `-posts.csv`, `-costs.csv`, `-scatter.png`
- `raw-<date>-<niche>.json`: every response, for `--from-raw`

## Sample (measured on 2026-10-07, 09:29 Asia/Tbilisi, count=15)

- TikTok use these 5: #homeworkout #garagegym #homegym #workoutfromhome #homefitness
- Instagram use these 5: #homeworkout #garagegym #homegymsetup #homefitness #garagegymlife
- 16 calls, 198 posts returned, 198 billed units, $0.4099 total from the cost headers.

## Notes

- The ranked table shows `share_last_30d`, `newest_days` and `median_age_days` per tag, so you can see how recent each tag's posts are.
- Ranking uses likes on both platforms. TikTok rows also show median plays.
- A tag with no posts returns HTTP 404 and costs nothing.
- The ranking shows which tags have engaged, recent posts from many creators. It does not promise reach.
