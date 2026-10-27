# Pricing Page Snapshot (Desearch MCP)

Made by Desearch, https://desearch.ai

Read a few pricing pages and get one table of plans and prices, copied from the page text. Save it, run again next week, and see what changed. A saved prompt for Cursor or Claude does the full job with no code. This folder also has a tiny Python CLI that reads each page with the hosted Desearch MCP `extract` tool (`format: text`, `js: false`).

What the CLI does:
- reads each page once and tries once more if the text comes back empty
- finds each price line and the plan name right above it, in page order; a price with no name above it is marked "(name not in page text)"
- notes the billing line under the price when the page shows one ("Billed yearly")
- marks pages with no prices in the text as "No prices in page text"
- with `--compare`, lists added and removed plans and price changes against an earlier snapshot

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
python pricing_snapshot.py https://linear.app/pricing https://www.figma.com/pricing/ --save snapshot-1.json
# next week
python pricing_snapshot.py https://linear.app/pricing https://www.figma.com/pricing/ --compare snapshot-1.json --save snapshot-2.json
```
Some pricing pages build their prices with JavaScript and show no prices in the page text. The CLI reports those pages instead of guessing; check them on the live page.

## Sample output
`sample-output.txt`, built from a saved `extract` result of 2026-10-05:
```
Page | Plan | Price as written | Billing | Snapshot date
https://linear.app/pricing | Free | $0 | not shown | 2026-10-05
https://linear.app/pricing | Basic | $10 per user/month | Billed yearly | 2026-10-05
https://linear.app/pricing | Business | $16 per user/month | Billed yearly | 2026-10-05
https://linear.app/pricing | Enterprise | Custom | Annual billing only | 2026-10-05
```

## No-code version
Paste a prompt from `saved-prompt.md` into Cursor or Claude with the Desearch MCP server connected (`https://mcp.desearch.ai/mcp`, key in the `Authorization` header). Prompt 1 builds the table with key limits and free tier; prompt 2 compares with your last table.

## Tests (offline, no key needed)
```
pytest -q tests
```
