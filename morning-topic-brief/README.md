# Morning Topic Brief

Made by Desearch. Built on the [Desearch API](https://desearch.ai) (https://desearch.ai).

A small Python script that, every morning, runs one Desearch AI Search per topic over the last 24 hours (web, X, Reddit, Hacker News), and turns the answers into one Markdown digest with cited links. It writes the digest to a file, prints it, and can send it to a Telegram chat.

## What it does

For each topic in `topics.yaml`, it sends one request to `POST https://api.desearch.ai/desearch/ai/search` with:

```json
{
  "prompt": "Bittensor",
  "tools": ["web", "twitter", "reddit", "hackernews"],
  "date_filter": "PAST_24_HOURS",
  "result_type": "LINKS_WITH_FINAL_SUMMARY",
  "system_message": "...short cited bullet digest...",
  "count": 10,
  "streaming": false
}
```

Then it:

1. Takes the `completion` (the summary) and the result lists (`tweets` and `search`).
2. Turns any bare numbered citations like `[8, 17]` into real links when it can tell which result list the numbers point to.
3. Removes duplicate links, tidies titles, and checks each result's own date (`created_at` on X posts, `published_date` when a web result has one). Results that are clearly older than the window are dropped from the source list and tagged `(older: YYYY-MM-DD)` if the summary cites them. Results with no date are kept and tagged `(date unknown)`.
4. Shows any `warnings` the API returns (for example when one source returned nothing).
5. Adds up the per-call cost from the `X-Desearch-Cost-Usd` response header and prints the total.

## Setup

Run the commands in this README from the `morning-topic-brief` folder.

Python 3.10 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Get an API key at console.desearch.ai (API Keys page).

## Environment variables (names only)

| Name | Required | What |
|---|---|---|
| `DESEARCH_API_KEY` | yes | Your Desearch API key. Sent as the `Authorization` header. |
| `TELEGRAM_BOT_TOKEN` | no | Bot token from Telegram's BotFather. |
| `TELEGRAM_CHAT_ID` | no | Chat to post the digest to. If either Telegram variable is missing, sending is skipped. |

Keep the key out of the code and out of the repo. One way is to keep it in a file only you can read and load it at run time:

```bash
export DESEARCH_API_KEY="$(cat ~/.desearch_api_key)"
```

## Run

```bash
python brief.py                       # uses topics.yaml, writes digests/brief-YYYY-MM-DD.md
python brief.py --config my.yaml      # your own topic list
python brief.py --out today.md        # choose the output file
python brief.py --sdk                 # same call through the official desearch-py SDK
python brief.py --evidence-dir logs/  # save each request/response as JSON (key redacted)
python brief.py --no-telegram         # never send to Telegram
python brief.py --replay logs/20261003-210817-http   # re-render saved responses, no API calls
```

Progress and cost go to stderr, the digest goes to stdout and to the file.

## Configure topics

`topics.yaml`:

```yaml
topics:
  - Bittensor
  - AI agents
  - open source LLMs
tools: [web, twitter, reddit, hackernews]
date_filter: PAST_24_HOURS
result_type: LINKS_WITH_FINAL_SUMMARY
count: 10          # results per source, the API accepts 10 to 200
max_links: 8       # links listed per topic
drop_stale: true   # drop results whose own date is older than the window
```

Tip: use a short topic as the prompt (for example `Bittensor`), not a sentence. In my test on 2026-10-03, a prompt like "What happened in the last 24 hours about AI agents" pulled X posts that matched the words "what happened in the last 24 hours" but were about unrelated things.

## Schedule it with cron

Run at 08:00 every day (cron uses the machine's local time zone):

```cron
# m h dom mon dow  command
0 8 * * * cd /path/to/desearch-py-examples/morning-topic-brief && DESEARCH_API_KEY="$(cat $HOME/.desearch_api_key)" TELEGRAM_BOT_TOKEN="$(cat $HOME/.tg_token)" TELEGRAM_CHAT_ID=123456789 .venv/bin/python brief.py >> brief.log 2>&1
```

## What it cost and how long it took (measured)

Measured by me on 2026-10-03 between 21:04 and 21:10 (Asia/Tbilisi), 16 AI Search calls with `count: 10`, 4 tools and `LINKS_WITH_FINAL_SUMMARY`:

- Cost: every call returned `X-Desearch-Cost-Usd: 0.004` and `X-Desearch-Usage-Count: 10`, so a 3-topic brief cost $0.012 per run.
- Latency: wall clock around each request (Python `time.perf_counter()`), 8.5 s minimum, 10.25 s median, 11.14 s maximum per call. A 3-topic brief took about 30 seconds end to end.

Your numbers may differ with other topics, sources and `count`.

## Sample output

Excerpt from `sample-output.md` (real run, 2026-10-03 21:08 Asia/Tbilisi; long titles shortened with "..."):

```markdown
# Morning Topic Brief, 2026-10-03

## Bittensor

- The project has a native token called TAO, with a maximum supply of 21 million, and features a proof-of-contribution reward system for miners and builders [16](https://x.com/Robin_T100/status/2106430982861533256)[20](https://x.com/onchain_alfa/status/2106404326193168795).
- The project is supported by infrastructure like Crucible Wallet, which offers tools for using TAO across Chrome, Android, and iOS [12](https://x.com/0x_Kalista/status/2106255881830846808).

**Sources**

- [TAO has a 21M max supply. After the first halving, base emission is 0.5 TAO per block...](https://x.com/Robin_T100/status/2106430982861533256) (twitter)
- [r/bittensor_ on Reddit: BitTensor Is About to Shock Everyone (Nobody’s Ready for This)](https://www.reddit.com/r/bittensor_/comments/1owoiah/bittensor_is_about_to_shock_everyone_nobodys/) (reddit) (date unknown)

---
Total Desearch cost for this brief: $0.012000 (from X-Desearch-Cost-Usd)
```

## Things to know

- In my runs, Reddit and Hacker News results came back inside the web `search` list, not as separate lists. The script labels each link by its domain. With all four tools, that list held only Reddit and Hacker News links (150 of 150 across my runs). With `tools: ["web"]` alone, the same query returned general sites. If you want news sites and blogs in your brief, try a separate call with `web` only.
- Some web results had no date, and a few had a `published_date` older than 24 hours even with `PAST_24_HOURS`. That is why the script checks dates itself. X posts always had `created_at` inside the window in my runs.
- The summary sometimes cites results by number only (`[8, 17]`). The numbers count across X posts and web results, and which list comes first can change between calls. The script works out the order from the citations the API already linked. If it cannot, it leaves the numbers as they are and says so.
- Bad key: the API returns HTTP 403 `{"detail":"Forbidden"}`. Missing header: HTTP 401 `{"detail":"Unauthorized"}`.
- With `--sdk`, error responses come back as an exception with only the status and reason. Do not log the full exception object: its text includes the request headers, which contain your key.
