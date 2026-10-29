# Page to Markdown with the Desearch API

Made by Desearch · https://desearch.ai

A small Python CLI and library that turns a list of URLs into clean Markdown files. It calls the Desearch API Extract endpoint (`GET /web/extract`) with `format=markdown` and `js=false`, so the API returns the page as Markdown (headings, links, lists, tables and code), and retries once when a page comes back with no readable text. Every call is logged with its status, latency and the cost from the `X-Desearch-Cost-Usd` response header.

It works on pages whose text is in the HTML the server sends (articles, docs, blogs, reference pages). Pages that build their content in the browser with JavaScript come back as `422` with `error_code` `js_required` in this mode, at no charge; the tool writes no file for them.

## Demo

The public Page to Markdown demo provides a URL form, a saved sample, Copy and Download buttons. Run `python app.py` locally or follow [DEPLOY.md](DEPLOY.md) for Vercel. The demo validates public URLs and DNS before counting a request toward rate limits and making one Extract request, never retries, caches conversions for six hours, and applies rate limits and a daily spend cap. The page reads `DEMO_PER_IP_10MIN` and `DEMO_PER_IP_DAY` limits through the free `GET /api/convert?limits=1` endpoint. Errors clear and hide the result. Set `DEMO_LIVE=0` for a paused sample preview. The original CLI below retains its existing retry option and output files.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # pytest only; the tool itself uses the standard library
```

Get an API key at console.desearch.ai and put it in a file outside your project. Then set one of:

- `DESEARCH_API_KEY_FILE`: path to a file that holds the key (preferred)
- `DESEARCH_API_KEY`: the key itself

## Run

```bash
python page2md.py urls.txt --out out/
python page2md.py https://example.com https://docs.python.org/3/tutorial/introduction.html
```

`urls.txt` has one URL per line; lines starting with `#` are skipped. Options:

- `--format markdown|html|text`: which Extract format to request (default `markdown`, saved as returned; `html` and `text` are converted locally)
- `--no-retry`: skip the one retry on an empty result

Output in `--out`:

- `pages/NN-<slug>.md`: one Markdown file per page with readable text, with a small front matter block (source, title, fetched time, status, attempts, word count)
- `summary.md`: one row per URL (status, attempts, words, empty, latency, cost) and the header cost total
- `results.json`, `calls.jsonl`: per-URL and per-call records
- `raw/`: each response as returned, with the Authorization header shown as `<redacted>`

## Use it as a library

```python
import page2md
client = page2md.Client(page2md.api_key())          # out=None: nothing written to disk
r = page2md.page_to_markdown(client, "https://example.com")
print(r["status"], r["words"], r["cost_usd"])
print(r["markdown"])
```

## Tips

- Send a custom `User-Agent` header. The client sets `page-to-markdown/0.1`.
- Blank or malformed URLs are skipped locally before any call is made.
- A page that returns an error comes back as a non-200 status with a short `detail` message and an `error_code` (`page_not_found`, `js_required`, `blocked`, ...) and is not charged; check `summary.md` for those rows.
- Links in the Markdown are absolute. Navigation, footers, forms and scripts are dropped.
- Tests run offline: `pytest -q`.

## Files

`page2md.py` (CLI and HTTP client), `core.py` (Markdown helpers and the local HTML converter for `--format html`, no network), `test_page2md.py` (offline tests), `urls.txt` (the 10 URLs used for the sample), `samples/` (sample output), `sample-output.md`.
