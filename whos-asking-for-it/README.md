# Who's Asking For It: social listening on X (Desearch MCP)

Made by Desearch, https://desearch.ai

Social listening on X: pull recent public X posts about a topic or problem, keep them inside your date window, and read what people say in their own words. A saved prompt for Cursor or Claude does it with no code. This folder also has a tiny Python CLI that runs the same searches through the hosted Desearch MCP `x-search` tool, keeps posts inside your date window, removes duplicates and gives each post a rough first-pass label (High, Medium, Low) for how close it is to someone asking for a tool.

This is for listening, not a lead list. Most posts it finds are announcements, promotions and general chat. In a live run on 2026-10-19 with the default newsletter phrases, 21 posts came back inside the window and none of them was someone asking which tool to use; the two High labels were promotional threads.

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
python whos_asking.py --days 30
python whos_asking.py --days 14 --group '("anyone recommend" OR "any recommendations") ("newsletter tool" OR "newsletter app")' --hide-handles
```
Keep OR terms inside parentheses. `-filter:retweets` and `lang en` are added for you. Without `--group` the script runs three newsletter example groups; swap in the words people use for your product.

The intent label is a simple keyword check: High needs a clear ask ("can anyone recommend", "switching from") plus a question mark, Medium is an open question, and everything else is Low. It is a rough hint, not a judgment, so read the posts yourself.

## Sample output (searches from 2026-10-03, handles, text and links hidden)
See `sample-output.txt`. A live run from 2026-10-19 is in `samples/live-run-2026-10-19.md`.
```
4 + 22 + 3 posts returned, 29 kept (2026-09-03 to 2026-10-03), first 8 shown
Rank | Intent | Date | Who | What they said | Link
1 | High | 2026-09-25 | person #1 | (hidden) | (hidden)
2 | Medium | 2026-09-13 | person #2 | (hidden) | (hidden)
```

## No-code version
Paste the prompt in `saved-prompt.md` into Cursor or Claude with the Desearch MCP server connected (`https://mcp.desearch.ai/mcp`, key in the `Authorization` header). The prompt reads each post in full and groups it as Asks, Complaints, Opinions, or Promo and news, in tables with links, keeps your date window, and adds a Reddit pass through `ai-search` as a separate "date not confirmed" list.

## Tests (offline, no key needed)
```
pytest -q tests
```
