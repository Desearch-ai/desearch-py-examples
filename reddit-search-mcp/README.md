# Reddit Search (Desearch MCP)

Made by Desearch, https://desearch.ai

Saved prompt and tiny Python CLI that searches Reddit threads on a topic through the hosted Desearch MCP `ai-search` tool with `tools: ["reddit"]`, and prints the thread links plus a short summary.

Why MCP: the REST API reference lists only `web` and `twitter` as `ai-search` sources (OpenAPI checked 2026-10-16), while the hosted MCP `ai-search` tool lists `reddit`. This example uses MCP.

## Setup
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # from console.desearch.ai
```

## Run
```
python reddit_search.py "What do people recommend for keeping houseplants alive in winter?"
python reddit_search.py "houseplants winter care tips" --links-only --raw out.json
```

## Sample output (2026-10-16)
```
1. (title hidden by Reddit login page)
   https://www.reddit.com/r/houseplants/comments/17n2iii/what_are_the_unspoken_rules_of_caring_for/
2. r/houseplants on Reddit: How does anyone keep their plants alive in the winter?!?
   https://www.reddit.com/r/houseplants/comments/sbrqzx/how_does_anyone_keep_their_plants_alive_in_the/
...
Summary:
People recommend keeping houseplants alive in winter by ensuring they are kept warm and protected from cold drafts ...
Cost: $0.004
```

Notes from the test run: some results have the title "Welcome to Reddit" (the script relabels them), results have no post dates, and a run returned threads from past years even with a one-month date range.

## No-code version
Paste the prompt in `saved-prompt.md` into Cursor or Claude Code with the Desearch MCP server connected.

## Tests (offline, no key needed)
```
pytest -q tests
```
