# Forum Intent Board

Made by [Desearch](https://desearch.ai).

Which public forum threads in your niche are people asking for a tool, a recommendation or an alternative? This script sends 5 to 8 niche keywords to the hosted Desearch MCP server (`ai-search`), once with the `hackernews` source and once with the `reddit` source per keyword, and writes every link to `forum_hits.csv`. Plain rules in the code ("looking for", "alternative to", "recommend", "how do I", "any tool", "switching from" and a few more) score each row for intent, and the top rows go to a short board a human can open today.

It lists public HN and Reddit threads Desearch returned for your keywords on the run date. It is not every mention and not an alert feed.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # create a key at console.desearch.ai
```

## Run

```bash
python forum_intent_board.py keywords.json                                    # live: 2 MCP calls per keyword, then a link check
python forum_intent_board.py --from-raw output/raw-2026-10-12.json            # offline rebuild, no API calls, no cost
```

`keywords.json` holds a `niche` label and up to 8 `keywords`. Options: `--date-filter` (sent to `ai-search`, default `PAST_MONTH`, `''` to omit), `--result-type` (`ONLY_LINKS` default, or `LINKS_WITH_FINAL_SUMMARY`), `--board-size` (default 20), `--no-link-check`, `--redact-file` (words replaced with `[redacted]` in saved titles and snippets), `--full-raw <path>` (keep every response unchanged in a private file), `--out` (default `output`).

## Desearch service used

Hosted MCP over Streamable HTTP, `https://mcp.desearch.ai/mcp`, header `Authorization: Bearer <key>` (docs: https://www.desearch.ai/docs/guide/sdk/mcp, checked 2026-10-12). One tool:

```json
{"name": "ai-search", "arguments": {"prompt": "crypto tax software", "tools": ["reddit"], "result_type": "ONLY_LINKS", "date_filter": "PAST_MONTH"}}
```

The result text is JSON: a `search` list (`title`, `link`, `snippet`, `highlights`, and `published_date` on most HN items) plus `cost_usd` and `usage_count`. The script keeps `hackernews` and `reddit` in separate calls.

Python client: the official `mcp` package (tested with 2.3.0), `streamable_http_client` with an http client that carries the header (see `tools/usecase_snippet.py`, 20 lines).

## How it works

1. **Search.** One `ai-search` call per keyword and source, `ONLY_LINKS`.
2. **Clean titles.** Some Reddit items come back with a generic page title and a sign-in snippet. The script then uses the thread's URL slug as the title (`title_source=url_slug`) and drops the snippet.
3. **Link check.** HN links: the public HN item data for that id (exists, not dead, posting time, story or comment). Reddit links: only checked to be a `/comments/<id>/` thread URL; the box could not read Reddit's thread data, so `link_live` stays empty for Reddit. Links that are not threads (a subreddit or list page) never reach the board.
4. **Intent score.** Weighted phrase rules on title + snippet (`INTENT_RULES` at the top of the script). Board threshold: score 2 or more.
5. **On-topic rule.** At least half of the keyword's words (4+ letters, first 5 letters) appear in title + snippet.
6. **Board.** Unique links with intent, on topic, not a dead HN item; sorted by score, then newest HN thread.

## Output (in `output/`)

- `forum_hits.csv`: keyword, source (hn / reddit), rank, title, title_source, url, snippet (240 chars, handles removed), published_date as returned, HN thread creation date and age, link check, intent score and terms, on-topic rule, fetched_at, duplicate_of.
- `<date>-board.md`: the ranked board.
- `<date>-calls.csv`: every call with link count, `cost_usd`, `usage_count`, seconds.
- `raw-<date>.json`: the run for `--from-raw` (titles, links, short snippets; no highlights, no author fields).

## Sample (measured on 2026-10-12, Asia/Tbilisi)

Niche: crypto and on-chain data tools. 8 keywords: on-chain analytics dashboard, crypto portfolio tracker, crypto tax software, wallet tracking tool, DeFi yield tracker, token unlock calendar, crypto screener, blockchain explorer.

- 16 calls (09:37 to 09:39), each returned 10 links: 80 HN rows, 80 Reddit rows, 156 unique links.
- Cost: $0.064 for the run, the sum of the `cost_usd` each result carried ($0.004 per call).
- HN: 74 of 75 HN item links were live, 61 stories and 13 comments; one was a dead story. 1 HN link and 1 Reddit link were list pages, not threads.
- Reddit: 49 of 80 titles came from the URL slug (step 2).
- Board: 19 rows (7 HN, 12 Reddit).
- Spot check of 20 rows (every 8th row): 13 on topic, 7 not; all 7 were HN rows.

## Tips

- Check thread dates. The script reads each HN thread's posting time and shows it on the board.
- Pick keywords with a product noun ("crypto tax software", "blockchain explorer"). Our broad ones ("token unlock calendar") drew more general HN threads.
- Run each source in its own call so you can see which source a link came from.
- Reddit titles are often a thread's own question, so Reddit rows made up most of our board.
