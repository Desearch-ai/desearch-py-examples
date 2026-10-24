# Plagiarism Checker
Made by Desearch · https://desearch.ai

Find public web pages that share sentences with your text, with a similarity score and the matching passage. This tool gives no verdict and does not detect AI writing. Only sampled sentences are checked, and only pages the search returns are compared. A match does not establish who wrote the wording first.

Use Python 3.9 or newer. Install dependencies and put your raw API key in a private file:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p ~/.config/desearch
printf '%s' 'YOUR_KEY' > ~/.config/desearch/access.key
chmod 600 ~/.config/desearch/access.key
export DESEARCH_KEY_FILE=~/.config/desearch/access.key
```

The key is read only from a file, never from an API key environment variable. The default file is `~/.desearch_api_key`. An optional SHA256 fingerprint prefix can verify that you selected the expected key.

```sh
python plagiarism_checker.py essay.txt --dry-run
python plagiarism_checker.py essay.txt --yes --out output --run-name essay-check
python plagiarism_checker.py --text 'Carefully designed gardens support diverse flowering plants throughout the summer.' --yes
cat essay.txt | python plagiarism_checker.py - --yes
python -m pytest -q
```

## Sample output

From `samples/mixed-essay.txt`, run 2026-10-24 09:40 Asia/Tbilisi, with 7 searches and 7 page fetches (6 billed, 1 returned 404 and cost $0), $0.010 in total:

```text
Matching sources found on the web
3 of 7 sampled sentences have at least one matching public page (42.9%).
Total cost: $0.010000 USD; 14 calls; slowest 2.95 s; empty-result calls 0 ($0.000000).
```

The sample text in `samples/` mixes original sentences with one Wikipedia sentence, one public-domain book sentence and one paraphrase (see [samples/SOURCES.md](samples/SOURCES.md)). The full output of that run is in [samples/sample-summary.md](samples/sample-summary.md) and [samples/sample-matches.csv](samples/sample-matches.csv) (page titles as returned, with dashes normalized).

Endpoints: `GET https://api.desearch.ai/web`, `GET https://api.desearch.ai/web/extract`, and `POST https://api.desearch.ai/search`.

`--engine web` is the default: cheaper per sentence, and in our test on 2026-10-24 it found a page published the same day. It returns snippets without publication dates. Quoted queries can fall back to loosely related results, so every snippet is scored. `--engine search` returns page text for every result but costs more and can miss very new pages.

Requests use a raw key in the Authorization header and User-Agent `desearch-plagiarism-checker/1.0`. The CLI uses `requests` for all three endpoints: desearch-py 1.2.1 (checked 2026-10-24) has no method for `POST /search`, and one small HTTP client keeps the cost headers in one place.

Options:

| Option | Default | Meaning |
| --- | --- | --- |
| FILE or --text TEXT | required | File, `-` for stdin, or inline text |
| --max-sentences N | 8 | Maximum sampled sentences |
| --min-words N | 8 | Skip shorter sentences |
| --max-query-words N | 18 | Maximum words in a search query; use the most distinctive contiguous window, earliest on ties |
| --query-style quoted/plain/both | quoted | Both sends two searches per sentence |
| --engine web/search | web | Search endpoint to use |
| --verify-pages N | 3 | Top qualifying canonical pages per sentence to verify, web only; 0 disables |
| --max-pages N | 10 | Maximum unique pages fetched across the run |
| --web-price USD | 0.001 | Price list rate per web search, confirm in Console |
| --extract-price USD | 0.0005 | Price per page extraction |
| --mode fast/balanced | balanced | Search mode |
| --count 10/15/20 | 10 | Requested results per search |
| --threshold NUMBER | 0.6 | Minimum match score, from 0 to 1 |
| --partial-threshold NUMBER | 0.4 | Minimum partial overlap score, from 0 to 1 |
| --replay RAW_DIR | unset | Rebuild reports from saved responses without a key or network |
| --price-per-result USD | 0.0005 | Observed rate, confirm in Console |
| --max-cost USD | 0.25 | Refuse when estimate exceeds this amount |
| --yes | off | Skip paid-search confirmation, required for non-interactive input |
| --dry-run | off | Show plan and estimate without a key or network |
| --timeout SECONDS | 90 | Timeout per request |
| --out DIR | output/ | Output directory |
| --run-name NAME | timestamp | Output filename prefix |
| --key-file PATH | DESEARCH_KEY_FILE or ~/.desearch_api_key | Raw key file |
| --expect-fingerprint PREFIX | unset | Required SHA256 hex prefix of stripped key |

For web, the estimate is searches x --web-price + min(--max-pages, sampled sentences x --verify-pages) x --extract-price. Verification disabled means zero extraction cost. Both query styles double the search count. For search, the estimate remains searches x requested result count x --price-per-result. The plan shows search and extraction estimates separately; their total is used for confirmation and --max-cost. Rates are price list rates, confirm in Console. Actual cost uses X-Desearch-Cost-Usd when present, otherwise the cost_usd response field, counting each call once. Search and extraction costs are reported separately. The estimate is a planning guard, not an enforced billing limit. Failed requests continue except authorization and credit errors, which stop the run. Exit codes: 0 completed, 1 declined or non-interactive confirmation, 2 key or request validation problem or authorization/credit failure, 4 estimate above budget. Other request errors are recorded; inspect the call log before interpreting a run with missing results.

Sentences split at sentence punctuation followed by whitespace; abbreviation handling is intentionally simple. A first line without sentence punctuation is treated as a title. Sampling favors longer sentences with more substantial words, then restores their original order. Source sentence indices start at 1 after title removal. Both engines shorten sentences longer than --max-query-words before applying quoted or plain query style. Window selection uses the same substantial-word rule as sampling. Very long quoted queries came back empty after about 30 s and were still billed in our test.

Scoring normalizes Unicode, case and punctuation, including punctuation without surrounding spaces. An exact normalized substring scores 1. Otherwise the score is the fraction of sentence word triples also found in the page (pairs for sentences shorter than three words). Repeated sentence triples count separately. The longest contiguous word run and its share of the sentence are also reported. These are wording similarity measures, not probabilities or conclusions about authorship. For search, page text is preferred, with highlights as fallback. For web, both the full sentence and its query window are compared against the snippet, keeping the higher score; page scoring always uses the full sentence. The snippet and each part separated by "..." are scored, keeping the best. Candidates at or above --partial-threshold are deduplicated by canonical URL and selected by snippet score, up to --verify-pages per sentence and --max-pages overall. Each selected page is fetched once with GET /web/extract?url=URL&format=text using --timeout, then compared with every sentence result for that canonical URL. Final scores keep the higher of snippet and page scores. Failed extractions are logged and skipped; 401 and 402 stop with exit 2. An evidence passage of about 200 characters is preserved around the longest run when possible.

Outputs use your run name as a prefix:

- `-matches.csv`: every result meeting the threshold, including sentence, query style, rank, URL, canonical URL, score, exact flag, containment, longest run and evidence passage, plus snippet_score, page_score (empty without a successful fetch), and verified_on_page (yes when page_score meets --threshold).
- `-sentences.csv`: each sampled sentence, query_used (the actual query sent, with both styles on separate lines when requested), searches, result and match counts, best score, best canonical URL, and original `best_url` across all returned results, even below the match threshold. The `overlap` column is `match` at or above `--threshold`, `partial` at or above `--partial-threshold` but below the match threshold, and `none` below both. `found_online` is `yes` only for a match.
- `-summary.md`: matching sources found on the web, sentence coverage, grouped canonical sources, mirror URLs, settings and cost totals. Mirror count counts additional distinct returned URLs beyond the first. Archive and translation mirrors are grouped in this summary; the matches CSV retains individual results.
- `-calls.jsonl`: appended query text in `query`, call timing, status, cost, usage, service and Desearch response headers, without request credentials.
- `-raw/`: response JSON per sentence and query style, plus extract-N.txt page texts and an extracts.json URL-to-file index. Use a distinct run name for each run to keep logs separate.

A sentence without a match may simply not have been returned by the search. When no sampled sentence matches, the report says:

No matching sources found among the pages the search returned for the sampled sentences. This does not prove the text is original.

Replay reuses saved extraction text through extracts.json without fetching pages. Keep the original calls log beside the raw directory to preserve header costs in replay reports. Replay uses the same input text, engine, verification, sampling and search options as the original run. For example:

```sh
python plagiarism_checker.py essay.txt --replay output/essay-check-raw --out output --run-name essay-replay
```

Replay writes matches, sentences and summary reports without new searches, a key, confirmation, or a calls log. It reports zero new cost and labels saved response costs as the cost of the original run. Use a new run name to preserve the earlier reports. Missing or invalid response files produce an error. Saved raw files do not contain request timing or HTTP status, so replay timing is zero.
