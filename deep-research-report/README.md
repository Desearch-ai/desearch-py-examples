# Deep Research Report

Made by [Desearch](https://desearch.ai).

A small Python script for analysts and founders who have one research question and want a cited, dated report instead of an afternoon of open tabs. You give it a topic and a date window. It asks the Desearch Search API a fixed set of sub-questions, dedupes the pages, and writes a markdown report where every finding is a sentence quoted from a returned page, with its link and published date, plus a source table and a CSV.

The report is built only from pages Desearch returned for your searches. It is not complete research, and the script writes no claims of its own.

## What you get

- `report-<topic>-YYYY-MM-DD.md`: up to 3 findings per sub-question (each a quoted sentence, then the source title, link, outlet and published date), a source table (title, outlet, published date, whether it is inside your window, which sub-questions found it) and a short run summary
- `sources-<topic>-YYYY-MM-DD.csv`: one row per unique page, with the quoted sentence, where it came from, and the full matched passage as returned
- the raw responses as JSON, so you can rebuild the report offline

## How the findings are chosen (no summarizing)

1. The topic goes into a fixed template of five sub-questions (`SUB_QUESTIONS` near the top of the script): what is driving it, latest news, data and market size, companies and projects, risks and criticism. Pass `--sub` 4 to 6 times to use your own.
2. Each sub-question is one `POST /search` call with `start_date`, `end_date`, `count` 20, `highlights` and `page_text`.
3. Pages are deduped by link (ignoring `www`, trailing slashes and query strings) and by near-identical titles (the same story under a different site name).
4. For each page, the script picks one sentence from the returned page text that lies inside the passage Desearch matched, preferring the one that shares the most words with the sub-question. The sentence is copied exactly. If a page has no page text, it falls back to a sentence of the matched passage as returned.
5. Only pages with a published date inside your window become findings, at most one per outlet per sub-question, and pages already quoted for an earlier sub-question are used again only when nothing else fits. Undated or out-of-window pages still appear in the source table, marked.

## Setup

```bash
pip install -r requirements.txt
# Put your Desearch API key (from console.desearch.ai) in a key file, one line:
printf '%s' 'YOUR_KEY' > ~/.desearch_api_key && chmod 600 ~/.desearch_api_key
```

The script reads the key only from a key file (`--key-file PATH`, default `~/.desearch_api_key`). It does not read environment variables.

## Run

```bash
python deep_research_report.py --topic "stablecoin adoption" --start-date 2026-09-19 --end-date 2026-10-19 \
  --key-file ~/.desearch_api_key --out output
```

Offline, from the saved sample (no key, no cost):

```bash
python deep_research_report.py --from-raw samples/sample-raw.json --out output/sample
```

Options: `--question` (report heading), `--sub` (your own sub-questions, repeat), `--start-date` / `--end-date` (YYYY-MM-DD, default the last 30 days), `--mode fast|balanced` (default balanced), `--count 10|15|20` (default 20), `--no-page-text`, `--raw-out`.

## Endpoint

`POST https://api.desearch.ai/search` with a JSON body: `query`, `mode`, `count` (10, 15 or 20), `start_date`, `end_date`, `highlights`, `page_text`. Each result has `url`, `title`, `published_date`, `highlights` and (when asked) `page_text`. The response body also carries `cost_usd` and `usage_count`, and the script adds them up.

The desearch-py SDK (1.2.1, checked 2026-10-19) has no method for this endpoint yet, so the script calls it with `requests`. Send a `User-Agent` header if you call it from plain Python; the script sets one.

## Notes from testing (2026-10-19)

- In my runs, every result had a `published_date` inside the window I asked for, including a window in early 2025.
- Each call came back in under a second in my runs.
- A big story shows up many times: the same wire article on many outlets, and the same page under several language paths. The URL and title dedupe merges a lot of it, but the same story under different headlines stays, so read the source table with that in mind.
- The `highlights` text came back with the spaces after commas and periods removed, so the script quotes the matching sentence from `page_text` instead and keeps the passage only in the CSV.
- A query of made-up words still returned a full page of unrelated results, so check that the source titles match your topic.
- There is no paging: one call returns at most 20 results, and asking for 10 is not the same as the first 10 of 20.
- An encyclopedia page came back with a recent `published_date`, which is likely its last edit, not when it was written.

## Sample output

`samples/sample-report.md` and `samples/sample-sources.csv` are the report rebuilt from `samples/sample-raw.json` (a run on 2026-10-19 for "stablecoin adoption", window 2026-09-19 to 2026-10-19). The public sample keeps, for each page, only the quoted sentence as page text and leaves out pages whose text contains an account handle or banned words, so it has fewer sources than the live run. The run log is in `samples/live-run-2026-10-19.md`.

## Tests

```bash
python -m unittest discover -s tests
```
