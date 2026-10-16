# Launch Video Swipe File

Made by Desearch · https://desearch.ai

A small Python CLI for founders planning a launch video: give it a category, get back `swipe.csv` and `swipe.md` with the most-liked public X video posts Desearch returned for launch and demo wording in that category over the last 30 days, grouped by how each post opens.

## What it does

1. **Search X for launch videos.** Desearch X Search (`GET /twitter`) with `query=(launch OR launching OR introducing OR demo) ("<term 1>" OR "<term 2>" ...)`. Both OR groups are in parentheses. Filters: `is_video=true`, `min_likes` (default 50), `start_date` = 30 days ago (UTC), `count` 50. One `sort=Top` pass and one `sort=Latest` pass.
2. **Filter in code too.** Keep posts that carry a video in `media`, have at least `min_likes`, and were created on or after the start day (UTC). One post per author, most-liked first, top 15.
3. **Refresh metrics.** `GET /twitter/urls` with the 15 post URLs (repeated `urls=` parameters) copies the latest likes, reposts and replies back onto each post.
4. **Group by opening.** The first 200 characters of the text decide the group, first match wins: `before/after`, `problem-first`, `founder talking`, `demo-first`, `announcement`, else `other`. The rules are regexes in `core.OPENINGS`.
5. **Write output.** `swipe.csv` (rank, opening, date, author, url, likes, reposts, replies, has_video, launch_words, hook, found_by) and `swipe.md`. Links use `https://x.com/i/status/<id>`. Individual authors show as "a creator" (pass `--brand <account>` to name an org or brand account), @mentions become `@user`, and tool names in post text become `[tool]`.

`--compare` adds two Top passes (`is_video` only, `min_likes` only) and writes their overlap with the main pass to `snapshot.json`, so you can see what each filter does for your category.

Everything in the output is the public X video posts Desearch returned for your query and window. Tip: check post dates and watch each video before you use it as a reference.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # pytest only; the CLI uses the standard library
echo "<your key from console.desearch.ai>" > ~/.desearch_key && chmod 600 ~/.desearch_key
export DESEARCH_API_KEY_FILE=~/.desearch_key     # or DESEARCH_API_KEY; the file wins when both are set
```

## Run

```bash
python swipe.py "mobile apps" --terms "iOS app" "mobile app" "Android app" "App Store" --min-likes 50
# options: --days 30  --count 50  --top 15  --brand <account> ...  --compare  --out runs
pytest -q test_swipe.py                          # offline tests
```

Each run writes `runs/<timestamp>-<category>/`: `swipe.csv`, `swipe.md`, `snapshot.json` (per-pass counts, overlap, final ids), `calls.jsonl` (one line per call with status, latency, items and cost) and `raw/` (each response). The key goes only in the `Authorization` header; the client refuses to write a file that contains it. Requests send their own `User-Agent`.

## Cost

Each response carries `X-Desearch-Cost-Usd`, and `calls.jsonl` records it (`cost_source: header`). If a header is missing, the script writes a calculated X Search value from the public rate and labels it `calculated`. My sample run with `--compare` (4 X Search passes and 1 `/twitter/urls` call) cost **$0.02115** by the headers on 2026-10-14.

## Sample output

See `sample-output.md` and `samples/` (run of 2026-10-14 09:30 Asia/Tbilisi, category "mobile apps").

## Tips

- Pick category terms people actually write in launch posts. A very narrow set of terms ("habit tracker", "todo app") with `is_video=true` and `min_likes=50` returned nothing for me; broader terms worked.
- Launch wording also matches news, recaps and promos. Open each post before you add it to your swipe file.
