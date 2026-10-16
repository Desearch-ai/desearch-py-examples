# arXiv Paper Search to CSV

Made by [Desearch](https://desearch.ai).

Type a few topics, get one clean CSV of arXiv papers: id, title, authors, abstract link, date and a short abstract snippet, with duplicates merged. One Desearch API endpoint and one Python file.

## What it calls
- `POST /desearch/ai/search` with `tools: ["arxiv"]`, `result_type: "ONLY_LINKS"`, `streaming: false`, `count: 10`.
- The API reference lists `web` and `twitter` as tools; `arxiv` worked in testing on this endpoint. The hosted MCP server lists `arxiv` in its `ai-search` tool, and gave the same papers in testing, so you can use either.

## Setup
```bash
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # from console.desearch.ai
```
(Or set `DESEARCH_KEY_FILE` to a file that holds the key.)

## Run
```bash
python arxiv_papers.py --queries "retrieval augmented generation evaluation" "small language models on device inference"
python arxiv_papers.py --from-raw samples/raw-sample.json   # rebuild a CSV offline from the bundled sample, no API calls
```
Optional: `--empty-check "<made-up topic>"` makes one extra call so you can see what a topic with no real papers returns. Each query is one billed call; check the cost headers on your first run.

## Output
`output/arxiv-papers-<label>.csv`, one row per unique paper (the raw response is saved next to it as `output/raw-<label>.json`):

`arxiv_id, title, authors, abs_link, id_month, published_date, summary_snippet, queries, links_seen`

- The same paper often comes back several times (abstract page, HTML page, other versions). The script keys on the arXiv id, so each paper appears once; `links_seen` counts how many links pointed to it.
- `id_month` comes from the arXiv id itself (`2405.07437` is May 2024), so every row has a reliable month.
- `published_date` and `authors` are taken only from abstract-page results. Dates earlier than the id month are dropped. Many rows have these blank.
- `authors` is kept as returned (name parts joined by `;`).
- `summary_snippet` is the first 300 characters of the abstract when one was returned.
- Results are not filtered by date; sort or filter on `id_month` yourself.

Sample (from a test run on 2026-10-16):
```
arxiv_id,title,authors,abs_link,id_month,published_date,summary_snippet,queries,links_seen
2404.13781,Evaluating Retrieval Quality in Retrieval-Augmented Generation,Salemi; Alireza; Zamani; Hamed,https://arxiv.org/abs/2404.13781,2024-04,2024-04-21,"Evaluating retrieval-augmented generation (RAG) presents challenges...",retrieval augmented generation evaluation,2
```
