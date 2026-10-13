# Listicle Gap Finder

Made by [Desearch](https://desearch.ai).

Give it your brand, 3 to 5 competitor names and 5 to 8 buyer searches ("best <category> tools 2026", "<rival> alternatives"). It collects the pages that rank for these searches with the Desearch API, reads each page, counts which brands it names, and flags the "gap" pages: pages that name 2 or more of your competitors but not you. Output: a Markdown outreach list, a CSV with one row per page, a mentions chart and a cost CSV.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # create a key at console.desearch.ai
```

## Run

```bash
# queries.txt: one buyer search per line
python listicle_gap.py --brand "YourBrand" --competitors "Rival A,Rival B,Rival C" --queries-file queries.txt
python listicle_gap.py --brand "YourBrand" --competitors "Rival A,Rival B" -q "best <category> tools 2026" -q "Rival A alternatives" --max-pages 20
python listicle_gap.py --from-raw output/raw-<date>-<brand>.json   # offline, no API calls, no cost
```

Options: `--links-count` (links-only results per query, 10 to 200, default 10, `0` skips this source), `--max-pages` (pages to read, default 40), `--start` (comma-separated `start` values for `GET /web`, default `0`), `--out` (default `output`), `--redact "word1,word2"` (replace these words with `[redacted]` in saved titles and snippets, handy before you share a sample), `--full-raw <path>` (also keep an unredacted raw file with full page text).

Endpoints used:
- `GET https://api.desearch.ai/web?query=<search>&start=0`: ranked web results (`title`, `link`, `snippet`)
- `POST https://api.desearch.ai/desearch/ai/search/links/web` with `{"prompt": "<search>", "tools": ["web"], "count": 10}`: a second list of links for the same search
- `GET https://api.desearch.ai/web/extract?url=<page>&format=text&js=false`: page text, used to count brand mentions

## How it decides

1. Every result from both sources becomes one page row (URLs are normalized, so the same page found twice is read once).
2. Pages are sorted for reading: on-topic titles first (a title, snippet or URL that contains a word from your searches), then roundup-style titles (best, top, alternatives, vs, compared, tested), then pages found by more searches, then the best rank.
3. The top `--max-pages` pages are read with Extract. Brand names are matched as whole words, case-insensitive, so a brand called "Search" does not match "research".
4. A page is a gap when it names 2+ competitors, does not name your brand, and is not on a competitor's own domain.

## Output (in `output/`)

- `<date>-<brand>-gaps.md`: summary, pages naming each brand, outreach list, cost line
- `<date>-<brand>-pages.csv`: one row per page with the searches it ranked for, best rank, mention counts per brand and the gap flag
- `<date>-<brand>-extract-log.csv`, `-costs.csv`, `-mentions.png`
- `raw-<date>-<brand>.json`: every search response plus each page's status, length and brand counts (page text itself is not saved), for `--from-raw`

Pages that return no text are listed in the extract log and left out of the counts.

## Sample (measured on 2026-10-08, 09:50 Asia/Tbilisi)

Category: a software category. Test brand: YourBrand. Tracked rivals: Rival A, Rival B, Rival C, Rival D, Rival E. 6 buyer searches (`queries.txt`), `--links-count 10`, `--max-pages 40`.

```bash
python listicle_gap.py --brand "YourBrand" --competitors "Rival A,Rival B,Rival C,Rival D,Rival E" --queries-file queries.txt \
    --redact "<two third-party names>" --full-raw <private path>
```

The measured run was saved with `--redact` for two third-party names, so 6 places in the raw file's search results (1 title in the pages CSV) show `[redacted]`. Page samples from that run are not included in this folder.

- Each `GET /web` call returned 20 results; each links-only call returned 10 links.
- 110 unique pages found, 40 read, 34 returned page text.
- YourBrand was named on 14 of the 34 pages; Rival A on 32, Rival B on 26, Rival C on 31, Rival D on 30, Rival E on 13.
- 19 gap pages (2+ rivals named, test brand not named).
- Cost: $0.047 for the full run (sum of the `X-Desearch-Cost-Usd` headers), about 2 minutes 25 seconds.

## Notes

- The list shows pages that rank for these searches. It does not say who reads them.
- Brand matching is plain text. Check a few gap pages by hand before you write to the author.
- A competitor's own blog can rank for your searches; those pages are kept in the CSV but never flagged as gaps.
