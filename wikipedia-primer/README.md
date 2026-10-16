# Wikipedia Primer (Desearch MCP)

Made by Desearch, https://desearch.ai

Get a short, Wikipedia-grounded primer on any topic: a plain summary with a link after each fact, the related Wikipedia pages, and an optional web cross-check. A saved prompt for Cursor or Claude does it with no code. This folder also has a tiny Python CLI that calls the hosted Desearch MCP `ai-search` tool with the `wikipedia` source and, with `--web`, the `web-search` tool.

What the CLI does with the results:
- drops `File:`, `Talk:`, `Category:` and `Wikipedia:` pages and marks pages that are not in English
- swaps citation numbers for the page link
- keeps a fact with a number only if a returned page shows that number, re-links it to the page that does, or leaves it out with a note

## Setup
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# put your key from console.desearch.ai in a file only you can read
echo "<your key>" > ~/.desearch-api-key && chmod 600 ~/.desearch-api-key
```
The script reads the key from `~/.desearch-api-key` (or `--key-file PATH`) and prints only the last 4 characters of its sha256.

## Run
```
python wikipedia_primer.py "carbon credits"
python wikipedia_primer.py "retrieval-augmented generation" --web
```

## Sample output
`sample-output.md` is the CLI output for "carbon credits" with `--web`, built from saved tool results of 2026-10-04.

## No-code version
Paste the prompt in `saved-prompt.md` into Cursor or Claude with the Desearch MCP server connected (`https://mcp.desearch.ai/mcp`, key in the `Authorization` header). The assistant also picks neutral web sources and writes the "What to read next" list.

## Tests (offline, no key needed)
```
pytest -q tests
```
