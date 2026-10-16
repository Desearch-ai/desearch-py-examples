# How to use Desearch to turn arXiv searches into a paper spreadsheet

Made by [Desearch](https://desearch.ai).

## The job
You are starting a literature review, a market scan or a reading list. You want the arXiv papers on two or three topics in one spreadsheet you can sort, share and annotate, not twenty browser tabs.

## What you build
A small Python script. You give it topics; it asks the Desearch API to search arXiv for each one and writes a CSV with one row per paper: arXiv id, title, authors, abstract link, the month from the id, a date when one is given, and a short piece of the abstract.

## How it works
1. Get an API key at console.desearch.ai.
2. Call the Desearch AI Search endpoint with the tool set to `arxiv` and the result type set to links only. The arXiv tool worked in testing on the API endpoint, and the hosted Desearch MCP server offers the same tool if you work inside an AI assistant.
3. Pull the arXiv id out of every link. The same paper can come back as its abstract page, its HTML page or an older version, so merge on the id and count how many links pointed to it.
4. Take the month from the id itself, so every paper gets a reliable month even when no date is returned.
5. Keep the abstract text as the summary snippet and write the CSV.

```bash
pip install requests
export DESEARCH_API_KEY=...
python arxiv_papers.py --queries "retrieval augmented generation evaluation" "small language models on device inference"
```

## What you get
In our test, two topics gave 16 unique papers, all from arXiv and all on topic, including surveys and recent work, merged into one sheet with the topic that found each one.

## Tips
- Results are not limited to a date range, so sort or filter on the month column.
- A topic that has no real papers still returns the closest papers it can find. Glance at titles before you trust a row.
- Author names and dates are not always returned; treat blank cells as unknown, and open the abstract link for the full record.
- Ten links per topic is a good start. Add more topics rather than one very broad one.

## Where to go next
Run it weekly on your topics and compare the new ids, or feed the CSV into a notebook to group papers by month and topic. Get a key at console.desearch.ai.
