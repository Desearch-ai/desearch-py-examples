# YouTube Angle Finder

Made by [Desearch](https://desearch.ai).

A small Python CLI for creators and marketers. Give it a niche or product question, and it finds YouTube videos on that topic with Desearch AI Search, then writes a short Markdown brief: **angles already covered** (with links to the videos that take them) and **gaps that look thin**. It prints the report, saves it to a file, and shows what the run cost.

The runs described below were made on 2026-10-04 (Asia/Tbilisi).

## How it gets YouTube results

A normal angles report does three things:

1. `POST /desearch/ai/search` with `tools: ["web"]`, `result_type: "ONLY_LINKS"`, `streaming: false`, `count: 10`, and the prompt `site:youtube.com <your question>`. This returns YouTube video links.
2. Public YouTube oEmbed (`https://www.youtube.com/oembed`, no key) for each video's title and channel name. Titles and snippets from Desearch for YouTube pages were often generic (`- YouTube`).
3. A second `POST /desearch/ai/search` with `tools: ["web"]`, `result_type: "LINKS_WITH_FINAL_SUMMARY"`, `streaming: false`, and a `system_message` that lists the verified titles, so the angles and gaps brief is grounded in those videos.

## Setup

Run the commands in this README from the `youtube-angle-finder` folder.

Python 3.10 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai (API Keys page)
```

The only env var is `DESEARCH_API_KEY`. The code reads it by name and never prints or logs it. Saved request and response files have the `Authorization` header replaced with `<redacted>`.

## Run

```bash
python angles.py "AI coding agents for solo founders"
```

Options:

| Flag | What it does |
|---|---|
| `--links-only` | Video list only, no brief. Stops after the `ONLY_LINKS` call, so there is no second summary request. |
| `--date-filter PAST_WEEK` | Passes `date_filter` through to `POST /desearch/ai/search`. Not a reliable freshness filter in the 2026-10-04 test. |
| `--no-fallback` | Send only `tools: ["youtube"]` on `POST /desearch/ai/search`. |
| `--count N` | Results per source. Sent as `count` on `POST /desearch/ai/search`. The 2026-10-04 runs used `10`, which is the API minimum. |
| `--out-dir DIR` | Where reports go (default `angles-out/`). |
| `--raw-dir DIR` | Also save each request and response as JSON (key redacted). |
| `--replay PREFIX` | Re-render a saved run from `--raw-dir` files without calling Desearch. |

Progress, HTTP status, latency, and cost per call go to stderr. The Markdown report goes to stdout and to `angles-out/<timestamp>-<mode>-<question>.md`.

## Request it sends

```json
{
  "prompt": "site:youtube.com AI coding agents for solo founders",
  "tools": ["web"],
  "result_type": "ONLY_LINKS",
  "streaming": false,
  "count": 10
}
```

The summary call is the same endpoint and the same `tools`, `streaming`, and `count`, with `result_type: "LINKS_WITH_FINAL_SUMMARY"` and a `system_message` that lists the verified titles. Auth header: `Authorization: <your key>`. `streaming` is always set to `false`. Omitting it on `POST /desearch/ai/search` returned an event stream in testing on 2026-10-03.

## Sample output (excerpt)

From the run at 2026-10-04 09:28 Asia/Tbilisi. Full output for all three niches: `sample-output.md`.

```markdown
# YouTube angles: Bittensor subnet mining for beginners

Desearch calls: 3 (HTTP 422, 200, 200; 0.05 s, 8.91 s, 8.13 s). Cost: $0.008 (sum of X-Desearch-Cost-Usd).

## Angles already covered
- Basic tutorials on how to start mining Bittensor subnets [2](https://www.youtube.com/watch?v=MydbEmhqiis), [3](https://www.youtube.com/watch?v=zPEfcCLt6DA) ...
- Testing and improving Bittensor miners [5](https://www.youtube.com/watch?v=OqDa6JdIsdc)

## Gaps that look thin
- Specifics on hardware requirements and setup for optimal mining performance [10](https://www.youtube.com/watch?v=YQWoPg1OoXM)
- In-depth comparison of different subnet options and their benefits ...

## Videos found (10)
1. [The Easiest Bittensor Subnet to Start Mining On!](https://www.youtube.com/watch?v=DtUYqhQNyr8) (Trend Setter Capital)
5. [How To Test & Improve Your Bittensor Miner (FULL Beginner Guide)](https://www.youtube.com/watch?v=OqDa6JdIsdc) (Trend Setter Capital)
```

## Measured cost and speed

Measured on 2026-10-04 09:22 to 09:30 Asia/Tbilisi from the `X-Desearch-Cost-Usd` response header and `time.perf_counter()` around each request:

- Every successful `POST /desearch/ai/search` call cost **$0.004** (`X-Desearch-Usage-Count: 10`), for both `result_type: "ONLY_LINKS"` and `result_type: "LINKS_WITH_FINAL_SUMMARY"`. `POST /desearch/ai/search/links/web` also cost $0.004 per call that day.
- HTTP 422 responses in those runs had no cost header.
- One angles report on the fallback path was one HTTP 422 plus two HTTP 200 calls, and the header sum was **$0.008**. `--links-only` summed to **$0.004**.
- Latency of successful calls: 6.1 s to 10.9 s, median 8.8 s (24 calls).

These figures were measured on 2026-10-04.

## Billing

On 2026-10-05 Desearch changed billing. Results are billed only per unique item actually returned. Empty results cost $0. Calls that return HTTP 422, 404, or 5xx are refunded.

## What the data includes

- Per video: a link, plus a title and snippet from Desearch that are sometimes generic or truncated. The app adds the title and channel from YouTube oEmbed when the Desearch title is missing, generic, or truncated.
- No publish date and no view count appeared in the Desearch responses from these runs, so the report shows none.
- The brief is model-written. Treat it as a starting point and open the links. In `sample-output.md`, the citation check on two of the three niches found a link that was not in the video list, and one niche also had bare numeric citations with no URL.

## Known issues

Limits that were still open in the 2026-10-04 runs:

- The app also tries `POST /desearch/ai/search` with `tools: ["youtube"]`, `result_type: "LINKS_WITH_FINAL_SUMMARY"`, `streaming: false`, and `count: 10` first, and falls back when that call is rejected. On 2026-10-04, from 09:22 to 09:31 Asia/Tbilisi, every attempt returned HTTP 422 (`No supported tools requested`).
- `--links-web` is a re-test flag, not part of a normal run. It calls `POST /desearch/ai/search/links/web` with `tools: ["youtube"]`, which returned HTTP 422 on 2026-10-04.
- `POST /desearch/ai/search` with `tools: ["web"]`, `streaming: false`, `count: 10`, and prompt `site:youtube.com <question>` sometimes returned off-topic pages (fewer than half of the links were YouTube videos). That happened twice on 2026-10-04. The same prompt sometimes returned generic technology pages. The app retries once.
- `date_filter: "PAST_WEEK"` passed through to `POST /desearch/ai/search` was not a reliable freshness filter for this job on 2026-10-04. Do not use it as proof that the videos are from that window.
- Titles and snippets on YouTube links from those AI Search responses were often generic (`- YouTube`) or truncated. Publish date and view count were absent from those responses.
- The angles brief can cite a video with a bare number, or with a URL that is not in the returned list. The report prints a citation check under the brief when that happens.

## Files

- `angles.py`: the CLI
- `requirements.txt`: `requests`
- `sample-output.md`: full output for three niches
