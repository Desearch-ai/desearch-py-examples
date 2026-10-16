# X Keyword Monitor

Made by [Desearch](https://desearch.ai).

For a founder, marketer or community manager who wants to see what people posted on X about a few keywords since the last check. Paste the saved prompt into Claude or Cursor, or run the script. Both search public X posts, keep only posts newer than your last check, and give you the time to use next time.

Authors of X posts are shown as a user. These are the posts Desearch returned for this search, not a full count of the conversation.

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
KEYWORDS: "home espresso" OR "espresso machine" OR "latte art"
MIN LIKES: 5
LAST CHECK: 2026-10-14 11:35 UTC
NOW: 2026-10-15 11:35 UTC

You report new public X posts Desearch returned for these keywords since LAST CHECK.

1. Search. Call x-search with:
   {"query": "(KEYWORDS)", "start_date": <date of LAST CHECK>, "end_date": <date of NOW>, "min_likes": MIN LIKES, "count": 20}
   Keep the OR group in parentheses exactly as written. Note how many posts came back.

2. Filter.
   - Keep only posts created after LAST CHECK.
   - Drop posts whose text has none of the keywords, and posts that are only a link.
   - Sort what is left newest first.

3. Output.
   - First line: "Public posts Desearch returned for these keywords between LAST CHECK and NOW: <n> returned, <n> new, <n> kept."
   - Table: time (UTC) | keyword matched | likes | short excerpt (exact words, max 20) | link
   - "Summary": 3 lines on what people talked about, based only on the kept posts.
   - Last line: "Next LAST CHECK: NOW".
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
python3 keyword_monitor.py config.json
python3 keyword_monitor.py --from-raw path/to/raw.json   # offline rebuild, no API calls
```

`config.json` holds the keywords, `min_likes`, `count` and `last_check` (UTC). After a live run, copy `Next LAST CHECK` from `output/monitor.md` back into `last_check`.

A live run writes `output/` and `evidence/raw-<date>.json`. Both folders are gitignored.

| Flag | Default | Meaning |
|---|---|---|
| `config` | `config.json` | keywords, likes floor and last check |
| `--from-raw PATH` | | rebuild the table from a saved raw file |
| `--out DIR` | `output` | output folder |

Offline tests (no API calls): `pytest -q test_keyword_monitor.py`.

## How it works

Base URL `https://api.desearch.ai`. The script sends the key in the `Authorization` header.

1. `GET /twitter` with `query=("home espresso" OR "espresso machine" OR "latte art")`, `sort=Latest`, `min_likes`, `count`, `start_date` set to the date of `last_check`, and `end_date` set to today's date (`YYYY-MM-DD`). The OR group stays in parentheses.
2. The script keeps posts created after `last_check`, drops posts with none of the keywords, drops posts that are only a link, and sorts the rest newest first.
3. It writes three summary lines from the kept posts and the time to use as the next last check.

## Sample output (2026-10-15, home espresso keywords)

- 20 posts returned for the window, 12 newer than 2026-10-14 11:35 UTC, 11 kept.
- 1 link-only post was dropped. 8 posts were older than the last check.

See [sample-output.md](sample-output.md). Each run writes `output/monitor.md` and `output/posts.csv`.
