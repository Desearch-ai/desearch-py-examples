# Find X Influencers (Desearch MCP)

Made by Desearch, https://desearch.ai

Saved prompt and a tiny Python CLI that finds active X voices on a topic. It calls the hosted Desearch MCP `x-search` tool, groups the posts by author, keeps authors with 2 or more posts, and ranks them by total likes, with follower counts.

## Setup
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# put your key from console.desearch.ai in a file only you can read
echo "<your key>" > ~/.desearch-api-key && chmod 600 ~/.desearch-api-key
```
The script reads the key from `~/.desearch-api-key` (or `--key-file PATH`) and prints only the last 4 characters of its sha256, so you can check which key ran.

## Run
```
python find_influencers.py '("sourdough" OR "bread baking") lang:en' --verified --min-likes 10
python find_influencers.py '("sourdough" OR "bread baking") lang:en' --count 50 --raw posts.json --hide-handles
```
Keep OR terms inside parentheses. `-is:retweet` is added for you.

## Sample output (2026-10-16, handles hidden)
```
50 posts, 38 authors, 5 with 2+ posts
#  author | followers | posts | likes | top post
1. a creator #1 | 35855 | 5 | 2382 | (hidden)
2. a creator #2 | 2036399 | 3 | 1877 | (hidden)
3. a creator #3 | 4960 | 3 | 437 | (hidden)
```

Notes from the test run: results are sorted by Top, so older popular posts appear next to recent ones (add start_date and end_date in the saved prompt if you only want current voices). With the default filters the MCP tool returned 20 posts for count 50; with `verified` and `min_likes` it returned 50.

## No-code version
Paste the prompt in `saved-prompt.md` into Cursor or Claude Code with the Desearch MCP server connected.

## Tests (offline, no key needed)
```
pytest -q tests
```
