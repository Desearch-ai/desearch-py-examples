# RAG Corpus Builder

Made by Desearch. Built with [Desearch](https://desearch.ai) (https://desearch.ai).

Give it a topic and 3 to 5 sub-questions. It asks the Desearch API for ranked web links per sub-question, dedupes them, reads each page with the Extract API, splits the text into heading-aware chunks and writes **a starter corpus from pages Desearch found**: `corpus.jsonl` (one row per chunk, with the source URL, page title and heading path on every row), `sources.csv` (one row per link and what happened to it) and a short `run-report.md`.

The output is meant for your own retrieval use (a RAG index, an eval set, a research notebook). Every row keeps its `source_url`, so you can cite the page and respect its license.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
echo "<your key from console.desearch.ai>" > ~/.desearch_key && chmod 600 ~/.desearch_key
export DESEARCH_API_KEY_FILE=~/.desearch_key      # or: export DESEARCH_API_KEY=...
```

The key is read at runtime and sent only in the `Authorization` header. Saved responses write `"Authorization": "<redacted>"`, and the client refuses to write any file that contains the key.

## Run

```bash
python ragcorpus.py examples/home-solar-batteries.json --max-pages 150 --max-spend 0.50
```

or without a file:

```bash
python ragcorpus.py --topic "home solar batteries" \
  --q "how a home solar battery system works" \
  --q "how long home solar batteries last" \
  --q "LFP vs NMC chemistry for home batteries"
```

Config file format (`count` per sub-question is optional, default `--count 50`):

```json
{
  "topic": "home solar batteries",
  "sub_questions": [
    {"q": "how a home solar battery system works", "count": 100},
    "how long home solar batteries last and how to maintain them",
    "LFP vs NMC chemistry for home batteries"
  ]
}
```

Output goes to `runs/<timestamp>-<topic>/`: `corpus.jsonl`, `sources.csv`, `run-report.md`, `snapshot.json`, `calls.jsonl` (one line per API call: status, latency, cost header) and `raw/` (link responses; Extract responses too with `--save-pages`).

| Flag | Default | What it does |
|---|---|---|
| `--count` | 50 | links requested per sub-question (10 to 200) |
| `--max-pages` | 150 | pages read in total, picked round-robin across sub-questions by rank |
| `--max-per-domain` | 3 | pages per domain, so one site does not fill the corpus |
| `--format` | `html` | Extract format; `html` keeps real headings, `text` guesses them |
| `--no-retry` | off | by default an empty page is read once more |
| `--no-topic-filter` | off | by default a link is skipped when its title and URL share no word with the topic or sub-question |
| `--chunk-chars` | 1200 | max characters per chunk |
| `--max-spend` | 1.0 | stop calling once this many USD (from the cost header) are spent |
| `--no-prefix-topic` | off | send the sub-question alone instead of `topic: sub-question` |

## How it works

1. `POST https://api.desearch.ai/desearch/ai/search/links/web` with `{"prompt": "<topic>: <sub-question>", "tools": ["web"], "count": 50}` returns `search_results` (title, link, snippet).
2. URLs are normalised (https, no `www.`, no fragment, no `utm_*` and similar tracking parameters, sorted query, no trailing slash) and deduped within and across sub-questions. The first sighting keeps its rank; `sources.csv` lists every sub-question a URL showed up in.
3. A light topic filter skips links whose title and URL share no word stem with the topic or sub-question.
4. `GET https://api.desearch.ai/web/extract?url=<link>&format=html&js=false` per page, 6 at a time. A page with under 200 characters of text is read once more.
5. The HTML is reduced to `<article>` or `<main>` when that holds most of the text; navigation, headers, footers, forms and cookie or share widgets are dropped. Paragraphs, list items, table cells and code blocks are grouped under their `h1`-`h6` path.
6. Chunks never cross a heading and are capped at `--chunk-chars`. Pages with the same text (one article under two URLs) and chunks repeated across pages (site-wide blurbs) are dropped by hash.

`corpus.jsonl` row:

```json
{"id": "p001-c002", "source_url": "https://palmetto.com/solar/how-does-a-solar-battery-work", "domain": "palmetto.com",
 "title": "How a Solar Battery Works: Energy Storage Explained", "heading_path": ["The science of solar batteries"],
 "heading": "The science of solar batteries", "chunk_index": 2, "text": "Lithium-ion batteries are the most popular ...",
 "n_chars": 1136, "sha256": "...", "topic": "home solar batteries", "sub_question": "how a home solar battery system works",
 "search_rank": 1, "fetched_at": "2026-10-11T09:46:24+04:00"}
```

## Sample output

From my run on 2026-10-11 09:44-09:46 (Asia/Tbilisi): 5 sub-questions, 260 links, 226 unique, 150 pages read, 139 pages in the corpus, 2629 chunks (median 479 characters, 2574 with a heading path). See `sample-output.md`, `samples/corpus.sample.jsonl` and `samples/sources.sample.csv`.

## Cost

At the rates on [desearch.ai/pricing](https://desearch.ai/pricing) (AI Search $0.40 per 1,000 items, Extract $0.50 per 1,000 pages), from the `X-Desearch-Cost-Usd` header in my runs:

| Call | Cost |
|---|---|
| links, `count: 50` (50 links returned) | $0.02 |
| Extract, one page | $0.0005 |
| 5 link calls at `count: 50` + 150 pages (calculated: 5 x $0.02 + 150 x $0.0005) | $0.175 |

Links took 7.3 to 8.6 s per call; Extract took a median of 1.8 s per page (max 10.3 s). The 150-page run finished in under 2 minutes.

## Tests

```bash
pytest -q test_ragcorpus.py      # offline, no key, no network
```

## Known issues

- Plan for about 40 to 60 links per call at high `count`. In my runs, `count: 10` returned 10, and `count` 50, 100 and 200 returned 39 to 62 links per call (`sample-output.md`).
- Further down the list, results can drift to general pages. In my first run, each of the 5 lists ended in a block of general "renewable energy" or "energy" pages (starting between rank 21 and rank 43), while none of ranks 1 to 20 was off topic. The topic filter (on by default) skipped 28 such links in the sample run.
- With `js=false`, some pages come back empty: 15 of 150 on the first call in the sample run (10 as HTTP 404 `No content found.`, 5 with under 200 characters, such as forum and shop pages that need JavaScript). Reading them again right away returned text for 6 of the 15, so the tool retries once. The rest are listed in `sources.csv` with status `empty`.
- Link lists change between calls, so two runs of the same config give overlapping but not identical corpora. Keep `corpus.jsonl` from the run you index.

Made by Desearch: https://desearch.ai
