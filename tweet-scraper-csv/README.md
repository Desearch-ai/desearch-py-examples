# Tweet Scraper to CSV

Made by Desearch · https://desearch.ai

A small Python CLI that runs an X query through the Desearch API (`GET /twitter`) and writes the public posts Desearch returned to a clean CSV: `id, date, text, likes, reposts, replies, link, author`.

## What it does

1. **Builds the query.** Your terms are ORed inside parentheses, for example `("home espresso" OR "espresso machine")`. Multi-word terms are quoted. `--extra` appends more query text after the group.
2. **Calls X Search.** `GET https://api.desearch.ai/twitter` with `query`, `sort` (default `Latest`), `start_date` (today minus `--days`, UTC), optional `end_date`, `lang` and `count` (default 50). The key goes in the `Authorization` header and requests send their own `User-Agent`.
3. **Cleans in code.** Drops duplicate ids and any post dated outside your UTC date window (for example a post from the evening before `start_date`), then sorts newest first.
4. **Writes the CSV.** `date` is UTC, `link` is `https://x.com/i/status/<id>`. By default the author column says "a user" (pass `--org <account>` to name an org account), @mentions become `@user`, t.co links are removed and tool names in post text become `[tool]`. `--raw-authors` keeps usernames and full text for private use.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # pytest only; the CLI uses the standard library
echo "<your key from console.desearch.ai>" > ~/.desearch_key && chmod 600 ~/.desearch_key
export DESEARCH_API_KEY_FILE=~/.desearch_key     # or DESEARCH_API_KEY; the file wins when both are set
```

## Run

```bash
python tweets_csv.py "home espresso" "espresso machine" --days 7 --sort Latest --count 50 --lang en
# options: --end YYYY-MM-DD  --sort Top|Latest  --count N  --lang xx  --org <account> ...  --extra "..."  --raw-authors  --out runs
pytest -q test_tweets_csv.py                     # offline tests, no network
```

Each run writes `runs/<timestamp>/`: `posts.csv`, `snapshot.json` (query, returned vs kept, dropped ids, cost), `calls.jsonl` (status, latency, items, cost per call) and `raw/` (each response, key redacted; the client refuses to write a file that contains the key).

## Cost

Each response carries `X-Desearch-Cost-Usd`, recorded in `calls.jsonl`. My sample run (1 call, 50 posts) cost $0.0075 by that header on 2026-10-15.

## Sample output

See `sample-output.md` and `samples/` (run of 2026-10-15 18:28 Asia/Tbilisi).

## Tips

- One call returns up to `count` posts. With `sort=Latest`, a busy topic can fill that from the last few hours, so check post dates and narrow the window or raise `count` if you need older posts.
- Put OR terms in parentheses so other filters apply to the whole group.
- Check post dates and read the posts before you rely on them; keyword matches include ads and off-topic posts.
