# Brand Mentions Finder

Made by [Desearch](https://desearch.ai).

For a founder, marketer or PR person who wants a monthly list of third-party pages and public X posts about their brand. Paste the saved prompt into Claude or Cursor, or run the script. Both search the web and X for the last 30 days, then drop the brand's own sites and the brand's own account.

Authors of X posts are shown as a user. These are the pages and posts Desearch returned for this search, not a full count of the conversation.

## Connect Desearch in Cursor or Claude Code

Create a key at [console.desearch.ai](https://console.desearch.ai). The server is `https://mcp.desearch.ai/mcp`. Send the API key in the `Authorization` header as `Bearer <key>`.

Cursor, in `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "desearch": {
      "url": "https://mcp.desearch.ai/mcp",
      "headers": {
        "Authorization": "Bearer <key>"
      }
    }
  }
}
```

Claude Code:

```bash
claude mcp add --transport http desearch https://mcp.desearch.ai/mcp \
  --header "Authorization: Bearer $DESEARCH_API_KEY"
```

Reload the client, confirm Desearch is connected, then paste the prompt below.

## Saved prompt

```text
BRAND: Raycast
WHAT IT IS: the Mac launcher app
BRAND TERMS: Raycast OR "raycast app"
OWN ACCOUNT: raycast
OWN DOMAINS: raycast.com
TODAY: 2026-10-15

You list public pages and posts Desearch returned that mention BRAND, written by others.

1. Web and X. Call ai-search with:
   {"prompt": "Third-party reviews, articles and posts that mention BRAND, WHAT IT IS, from the past month",
    "tools": ["web", "twitter"], "result_type": "ONLY_LINKS",
    "start_date": "<TODAY minus 30 days>T00:00:00Z", "end_date": "<TODAY>T23:59:59Z"}
   Results can include pages on OWN DOMAINS. Step 3 removes them.

2. More X posts. Call x-search with:
   {"query": "(BRAND TERMS) -from:OWN ACCOUNT", "start_date": <TODAY minus 30 days>, "end_date": TODAY, "min_likes": 5, "count": 20}
   Keep the OR group in parentheses exactly as written.

3. Clean up.
   - Drop any link on OWN DOMAINS or their subdomains, and any post from OWN ACCOUNT.
   - Drop duplicates (same link twice).
   - Read each item and drop it if BRAND means something else there. List it under "left out".

4. Output.
   - First line: "Public pages and posts Desearch returned for BRAND on <date>: <n> web, <n> X, <n> kept."
   - Table: where (site or "X") | link | snippet (exact words, max 25) | tone (positive, neutral, negative) | date
   - "Left out": one line each with the reason.
   - Show authors of X posts as "a user".
```

The same text is in [saved-prompt.md](saved-prompt.md). Who it is for, and the sample walkthrough, are in [usecase.md](usecase.md).

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai
```

| Variable | Meaning |
|---|---|
| `DESEARCH_API_KEY` | your API key |
| `DESEARCH_API_KEY_FILE` | optional: path to a file holding the key, used when `DESEARCH_API_KEY` is not set |

The script sends the key only in the `Authorization` header and never writes it to output.

## Run

```bash
python3 brand_mentions.py config.json
python3 brand_mentions.py --from-raw path/to/raw.json   # offline rebuild, no API calls
```

`config.json` holds the brand, the product phrase, brand terms, the brand's own account, own domains, optional words for other meanings, the window and `min_likes`.

A live run writes `output/` and `evidence/raw-<date>.json`. Both folders are gitignored.

| Flag | Default | Meaning |
|---|---|---|
| `config` | `config.json` | brand, terms, domains and window |
| `--from-raw PATH` | | rebuild the table from a saved raw file |
| `--out DIR` | `output` | output folder |

Offline tests (no API calls): `pytest -q test_brand_mentions.py`.

## How it works

Base URL `https://api.desearch.ai`. The script sends the key in the `Authorization` header.

1. `POST /desearch/ai/search` with `tools: ["web", "twitter"]`, `result_type: "ONLY_LINKS"`, `streaming: false`, and `start_date` / `end_date` covering the last 30 days (`YYYY-MM-DDTHH:MM:SSZ`).
2. `GET /twitter` with `query=(Raycast OR "raycast app") -from:raycast`, `sort=Latest`, `min_likes`, `count`, and `start_date` / `end_date` as `YYYY-MM-DD`. The OR group stays in parentheses.
3. After the results come back, the script drops links on the brand's own domains (the host equals the domain, or is a subdomain), posts from the brand's own account, duplicate links, rows that do not contain a brand term, and rows that contain `other_meaning_words` without a product word. Nothing on the request asks the API to drop domains.

## Sample output (2026-10-15, brand: Raycast)

- Web and X from `ai-search`, plus 20 X posts from `x-search`, last 30 days.
- 6 of 10 web pages in that run were on the brand's own site and were left out by hand.
- 1 post in 30 was about something else (a game, with no Raycast in the text).

See [sample-output.md](sample-output.md). Each run writes `output/mentions.md` and `output/mentions.csv`.
