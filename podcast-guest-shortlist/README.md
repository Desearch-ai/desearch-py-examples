# Podcast Guest Shortlist

Made by [Desearch](https://desearch.ai).

For a podcast host or producer on a niche show who needs fresh guests. Paste the saved prompt into Claude or Cursor, or run the script. Both search public X posts on your topic from the last 30 days, check that each person posts about it more than once, and look for past podcast pages.

Each person is shown as a user. The host reviews the table and reaches out personally. Nothing here drafts a message or looks for contact details.

These are the posts and pages Desearch returned for this search, not a list of people who are open to guesting.

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
TOPIC TERMS: sourdough OR levain OR "bread baking"
TOPIC NAME: sourdough
TODAY: 2026-10-14

You build a podcast guest shortlist from public posts and pages Desearch returned for this search. The host reviews it and reaches out personally. Never draft outreach messages and never look for contact details.

1. Search. Call x-search with:
   {"query": "(TOPIC TERMS)", "start_date": <TODAY minus 30 days>, "end_date": TODAY, "min_likes": 20, "count": 50}
   Keep the OR group in parentheses exactly as written. Note how many posts came back.

2. Pick people.
   - Drop posts dated before start_date.
   - Drop brands, shops, recipe pages, news accounts and anything that looks automated. Label each account yourself: person, brand, or bot.
   - Drop political figures and posts that only mention the topic in passing.
   - Keep up to 15 different people, most on-topic first.

3. Confirm. For each person call x-posts-by-user with:
   {"user": "<account from step 2>", "query": "(TOPIC TERMS)", "count": 10}
   Sort the posts by date yourself. Count how many are about the topic and how many are from the last 30 days. Mark anyone with only one on-topic post as "one post only".

4. Past podcasts. For each person call web-search with "<display name> podcast".
   If the pages are about other people with the same name, run "<display name> TOPIC NAME podcast" once.
   Keep only pages that are clearly this person as a guest or host. Otherwise write "none found".

5. Output.
   - First line: "Public posts and pages Desearch returned for this search on <date>: <n> posts, <n> people checked."
   - Table: person | on-topic posts (count, newest date) | past podcast pages or "none found" | person or brand | pitch angle (one line, based only on their posts)
   - Call each person "a user". Do not print account names or personal post links.
   - A "skipped" list with one line each and the reason.
   - A reminder: the host reviews each row and reaches out personally.
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
python3 guest_shortlist.py config.json
python3 guest_shortlist.py --from-raw path/to/raw.json   # offline rebuild, no API calls
```

`config.json` holds the topic terms, the topic name, the window, `min_likes`, `count`, how many people to check, and `brand_words` (names that look like a shop or a recipe page).

A live run writes `output/` and `evidence/raw-<date>.json`. Both folders are gitignored.

| Flag | Default | Meaning |
|---|---|---|
| `config` | `config.json` | topic, window and brand words |
| `--from-raw PATH` | | rebuild the shortlist from a saved raw file |
| `--out DIR` | `output` | output folder |

Offline tests (no API calls): `pytest -q test_guest_shortlist.py`.

## How it works

Base URL `https://api.desearch.ai`. The script sends the key in the `Authorization` header.

1. `GET /twitter` with `query=(sourdough OR levain OR "bread baking")`, `sort=Latest`, `min_likes=20`, `count=50`, and `start_date` / `end_date` as `YYYY-MM-DD`. The OR group stays in parentheses.
2. Posts before the window, and posts that do not contain a topic term, are dropped. People are ordered by how many on-topic posts they had in that search. Accounts whose display name or bio matches `brand_words` go to the skipped list.
3. For each remaining person, `GET /twitter/post/user` with `user`, the same topic `query`, and `count=10`. The script sorts those posts by date, counts on-topic posts, and marks "one post only" when there is just one.
4. `GET /web?query=<display name> podcast`. If none of the pages contain both "podcast" and a longer word from the display name, it calls `GET /web` once more with `<display name> <topic> podcast`. Otherwise the cell says "none found".
5. The pitch angle is a short excerpt of that person's newest on-topic post. The written table says "a user" and does not include account names or personal post links.

## Sample output (2026-10-14, home sourdough baking)

- 50 posts returned, 15 people checked, 13 kept as individuals, 2 skipped as brand-style accounts.
- Past podcast pages found for 5 of the 15. One of those showed up only after the topic was added to the web search.

See [sample-output.md](sample-output.md). Each run writes `output/shortlist.md` and `output/guests.csv`.
