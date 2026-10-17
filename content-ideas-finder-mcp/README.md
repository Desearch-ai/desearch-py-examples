# Content Ideas Finder (Desearch MCP)

Made by Desearch, https://desearch.ai

Turn the questions people ask about your niche into a month of post ideas, with a source link behind each one. It uses the hosted Desearch MCP server: the `ai-search` tool for Reddit (and Hacker News for tech niches) and the `x-search` tool for X posts.

There are two ways to use it:
- **No code:** paste `saved-prompt.md` into Claude or Cursor with the Desearch MCP server connected. Your assistant runs the searches and writes the plan (example: `sample_plan.md`).
- **Small script:** `content_ideas.py` runs the same searches and prints a table of questions, a suggested format and the source link (example: `sample_output.md`).

## Setup
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```
Get an API key at console.desearch.ai and save it in a file only you can read:
```
printf '%s' 'YOUR_KEY' > ~/.desearch-api-key && chmod 600 ~/.desearch-api-key
```
The script reads the key from `~/.desearch-api-key` (or `--key-file PATH`) and prints only the last 4 characters of its sha256 fingerprint.

## Run
```
python content_ideas.py "starting a newsletter"
python content_ideas.py "home espresso" --no-hackernews
python content_ideas.py "starting a newsletter" --raw raw.json
python content_ideas.py "starting a newsletter" --from-raw raw.json   # rebuild the table, no API calls
```
Options: `--no-hackernews` (non-tech niches), `--no-x`, `--count` (X posts to read, default 20), `--limit` (questions to keep, default 10), `--raw` (save the responses), `--from-raw` (work offline from a saved file).

## What it does
1. `ai-search` with `tools: ["reddit"]` and the prompt "questions beginners ask about <niche>".
2. The same with `tools: ["hackernews"]`, unless you pass `--no-hackernews`.
3. `x-search` with `(<niche>) ("how do i" OR "how do you" OR "any tips") lang:en -is:retweet`, count 20.
4. Pulls question sentences that mention your niche out of titles and posts, keeps one per thread or post, takes turns between sources, and suggests a format (carousel for lists and tips, short video for how-tos, thread for the rest).

## Sample output (2026-10-17)
```
Niche: starting a newsletter
Read 40 threads and posts Desearch returned; found 10 questions.

| # | Question people asked | Post idea | Format | Source | Date |
|---|---|---|---|---|---|
| 1 | How to start a newsletter? | Answer it: "How to start a newsletter", with your own example | short video | https://www.reddit.com/r/selfpublish/comments/188ttau/how_to_start_a_newsletter/ | not shown |
| 2 | What's the best place to start a newsletter? | Answer it: "What's the best place to start a newsletter", with your own example | carousel | https://news.ycombinator.com/item?id=37464463 | not shown |
| 3 | Thinking of starting a newsletter? | Answer it: "Thinking of starting a newsletter", with your own example | thread | https://x.com/i/status/1840013968019972548 | 2024-09-28 |
...
ai-search cost: $0.0080
```
Full table: `sample_output.md`.

## Good to know
- Reddit and Hacker News results come without dates, and X results mix newer and older posts. Check the date column (or open the link) before you build a post on a question.
- The script's question picking is simple text matching. The saved prompt gives better post ideas because your assistant reads the threads and writes the hooks.
- If your niche is made up or very vague, you still get links, but they may be about something else. Treat a thin or off-topic table as "nothing found".

## Tests (offline, no key needed)
```
pytest -q tests
```
