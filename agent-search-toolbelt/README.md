# Agent Search Toolbelt (Desearch MCP example)

Made by Desearch. Built with [Desearch](https://desearch.ai) (https://desearch.ai) hosted MCP.

A small Python research agent that connects to the Desearch hosted MCP server from code, gives itself exactly four tools, answers a question with the links it used, and writes a run log with every tool call's arguments, latency and cost.

| Tool on Desearch MCP | What the agent uses it for |
|---|---|
| `web-links-search` | find 10 links for the question |
| `extract` | read the top pages as plain text (`js: false`) |
| `x-search` | recent public X posts on the topic |
| `web-search` | ranked titles, links and snippets (available to the optional LLM mode) |

**The default loop is scripted. No LLM is used or needed.** It runs a fixed plan: `web-links-search`, then `extract` on the top 3 links (one retry if a page comes back empty), then `x-search`, then a Markdown answer that quotes the most relevant sentences from each page and lists every link. An LLM mode is optional (see below); without an LLM key the example still runs end to end.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai
```

| Variable | Meaning |
|---|---|
| `DESEARCH_API_KEY` | your Desearch API key |
| `DESEARCH_API_KEY_FILE` | optional: path to a file holding the key, used when `DESEARCH_API_KEY` is not set |
| `DESEARCH_MCP_URL` | optional: defaults to `https://mcp.desearch.ai/mcp` |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | only for the optional `--llm` mode |

## Run

```bash
python toolbelt.py "James Webb telescope exoplanet atmosphere findings" --x-days 14 --out answer.md
```

It prints the answer, writes it to `--out`, and appends one JSON line per tool call to `run-log.jsonl`. See `sample-output.md` (my run on 2026-10-09 09:39 Asia/Tbilisi) and `run-log.sample.jsonl` (the log of that run).

| Flag | Default | Meaning |
|---|---|---|
| `question` | | what to research |
| `--top N` | 3 | links to read with `extract` |
| `--links N` | 10 | `web-links-search` count (10 to 200) |
| `--x-count N` | 10 | `x-search` count |
| `--x-days N` | off | only X posts from the last N UTC days (`start_date` / `end_date`) |
| `--log PATH` | `run-log.jsonl` | JSONL run log |
| `--raw DIR` | off | save every raw tool result (for debugging; no key is ever written) |
| `--out PATH` | off | also write the answer Markdown here |
| `--llm` | off | optional LLM mode |

Offline tests (no network, no key): `pytest -q test_toolbelt.py`.

## How it works

`toolbelt.py` is the agent (about 60 lines of logic); `helpers.py` holds parsing, cost and Markdown helpers.

1. Connect with the official MCP Python SDK over Streamable HTTP, sending `Authorization: Bearer <key>`:

   ```python
   headers = {"Authorization": f"Bearer {api_key()}"}
   async with httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(30, read=180)) as http:
       async with streamable_http_client("https://mcp.desearch.ai/mcp", http_client=http) as (read, write):
           async with ClientSession(read, write) as session:
               await session.initialize()
   ```

   `x-api-key: <key>` worked as well. `initialize` and `tools/list` need no key; `tools/call` does.
2. `tools/list` returns the full Desearch tool set. The agent keeps only the four tools above, and `Toolbelt.call` refuses any other name, so the agent can never call a tool you did not give it.
3. Each tool result is one text item holding JSON. The agent parses it, and the run log gets `ts`, `tool`, `args`, `latency_s`, `is_error`, `items` and the cost fields below.
4. The answer lists the pages it read (with the quoted sentences), the other links found, and the X posts, each with its link.

### Run log line

```json
{"ts": "2026-10-09T09:39:38+04:00", "tool": "web-links-search", "args": {"prompt": "James Webb telescope exoplanet atmosphere findings", "tools": ["web"], "count": 10}, "latency_s": 8.392, "is_error": false, "items": 10, "cost_usd": 0.004, "usage_count": 10, "cost_source": "result"}
```

### Cost fields

`web-links-search` and `web-search` return `cost_usd` and `usage_count` inside the tool result, and the agent logs them with `"cost_source": "result"`. `extract` and `x-search` results have no cost field over MCP, so the agent logs `"cost_source": "not returned"` plus an `est_cost_usd` from the published rates on [desearch.ai/pricing](https://desearch.ai/pricing) (checked 2026-10-09). Console shows the billed amounts.

| Tool | Published rate (desearch.ai/pricing, 2026-10-09) | Per call in my runs | Where the agent gets it |
|---|---|---|---|
| `web-links-search`, count 10 | AI Search $0.40 / 1,000 items | $0.004 | `cost_usd` in the result |
| `web-search` | Web Search $1.00 / 1,000 searches | $0.001 | `cost_usd` in the result |
| `extract` | Extract $0.50 / 1,000 pages | $0.0005 per page | estimate from the rate |
| `x-search`, count 10 | X Search $0.15 / 1,000 posts, 10-post minimum per request | $0.0015 | estimate from the rate |

Every per-call number above matched both the pricing page and the REST `X-Desearch-Cost-Usd` header I got for the same call on 2026-10-09.

## Cost of one run

Measured on 2026-10-09 (Asia/Tbilisi), sample run: 1 `web-links-search` ($0.004 reported in the result) + 3 `extract` + 1 `x-search` (10 posts) = **$0.007** (the last two at the published rates: 3 x $0.0005 + $0.0015). 5 tool calls, 17.8 s of tool time.

## Optional: LLM mode

`python toolbelt.py "<question>" --llm` hands the same four tools to an LLM, which decides what to call. It needs `LLM_API_KEY`, `LLM_BASE_URL` (any endpoint that speaks the common chat-completions JSON with tool calling) and `LLM_MODEL`. `extract` is always sent with `js: false`. I had no LLM key for this build, so this mode is covered only by the offline test with a stub model (`test_llm_mode_with_stub_model`); every live run in this folder used the scripted loop.

## Known issues

Seen on 2026-10-09; details are in `report.md`.

- `extract` and `x-search` results over MCP carry no cost field (`web-search` and `web-links-search` do). The agent estimates those two from the published rates; Console has the billed amount.
- `x-search` on MCP has no `sort` option and returns Top posts, which for an undated query spanned 2018 to 2026. Use `--x-days N` when you want recent posts: with it, every post in my runs fell inside the window.
- `web-links-search` sometimes returns a different meaning of an ambiguous word: for "what is new in the Rust 2024 edition", 5 of 10 links were about the Rust video game. The other 6 test prompts had 0 or 1 off-topic links. Use specific wording ("Rust programming language 2024 edition").
- 1 of the 12 `web-links-search` calls I saved returned `HTTP 503 Search unavailable` as an error result. Run the question again.
- A page behind a bot check returned `HTTP 404 No content found` from `extract` on both tries; the agent skips it and reads the next link.
- With no key, `tools/call` raises an `MCPError` in the Python SDK. With a wrong key, the call returns a normal result with `is_error: true` and the text `HTTP 401: {"error":"Invalid API key"}`. Handle both.
- `extract` returns the page text as a JSON-encoded string (`"..."`), so parse it with `json.loads` (the helper does).
- Latency in my runs (successful calls): `web-links-search` 8.0 to 9.5 s (median 8.5 s, 9 calls), `extract` 0.9 to 8.1 s (median 2.6 s, 26 calls), `x-search` 2.4 to 6.5 s (median 2.9 s, 9 calls).
