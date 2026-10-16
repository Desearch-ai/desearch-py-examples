# Directory Finder

Made by [Desearch](https://desearch.ai).

Type a category, get a list of directories that take submissions, with each submit page read once. The script runs a few web searches with the Desearch API (`GET /web`), pages through the results with `start`, keeps one row per domain, then reads each likely submit page with Extract (`GET /web/extract`, `format=text`, `js=false`).

Output: `output/directories.csv` (one row per directory submit page with short quotes about free, paid and review) and `output/shortlist.md` (directories Desearch found for this search on the run date).

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Save your API key from console.desearch.ai in a file only you can read. The script reads the key from that file (not from environment variables) and never prints it:

```bash
printf '%s' 'YOUR_KEY' > ~/.desearch_api_key && chmod 600 ~/.desearch_api_key
```

## Run

```bash
python directory_finder.py config.json --key-file ~/.desearch_api_key   # live: searches + page reads, saves evidence/raw-<date>.json
python directory_finder.py --from-raw samples/raw-sample.json           # offline: build output from the bundled sample, no API calls
python directory_finder.py --from-raw evidence/raw-<date>.json          # offline: rebuild output from your own saved run
```

`config.json` holds the category, 3-5 query variants, the `start` values to page with, and a `kinds` map (directory, list or article, submission service) you fill in after reading the pages. Only rows marked `directory` go to the output.

## Sample run (2026-10-14, category "AI tools")

- 4 queries x 3 pages (`start=0,10,20`) = 12 searches, 20 results each, 240 results, 93 unique domains.
- 25 likely submit pages read. 10 were a directory's own submit page; 9 of those loaded with text.

`samples/raw-sample.json` is a trimmed copy of that run (4 searches, 10 results each, 6 page reads, page text cut to 1500 characters).

## Tests

```bash
python -m pytest -q tests
```

The tests run offline against the sample.

## Tips

- Each `/web` page returned 20 results in our run, so `start=10` mostly repeated `start=0`. Paging in steps of 20 (`start=0,20,40`) gave new domains. Set `starts` in `config.json`.
- Keep `start` between 0 and 100.
- Some submit pages are forms that load with JavaScript, so a text read returns very little. The CSV marks them `page_loaded=False`; open those in a browser.
- Read each page yourself before you submit. The yes/no columns only say whether a word appears on the page.
