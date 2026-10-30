# Scholarship Finder
Made by Desearch ([https://desearch.ai](https://desearch.ai))

Find scholarship pages for a field, level, and year. Results show source-stated amounts and dates, sorted by the candidate deadline. Every row includes a source URL.

Deadlines and amounts are as stated by the source page. Check the official page before applying.

## Setup

Use Python 3.10 or newer. No installs or extra packages are needed.
Get an API key at [console.desearch.ai](https://console.desearch.ai).
Save the key alone in `~/.desearch_api_key`, or set the environment variable `DESEARCH_API_KEY`.
The key file takes priority if it exists. Keep it private. The app does not print the key, and request logs redact Authorization values and the active key.

## Run

From this folder:

```sh
python3 scholarship_finder.py --field nursing --level undergraduate --year 2027
python3 scholarship_finder.py --field nursing --level undergraduate --year 2027 --dry-run
python3 scholarship_finder.py --field nursing --level undergraduate --year 2027 --verify 0 --no-web --out ./results
python3 scholarship_finder.py --from-raw out/raw-20261030-120000.json --today 2026-10-30 --out ./replayed
python3 -m unittest discover -s tests -v
```

After sorting, stdout and Markdown show at most `--limit N` rows (default 15; `--limit 0` shows all). Both report `showing N of M rows`. CSV includes all rows after the optional `--hide-unclear` filter. The stdout table truncates long names; exported files keep complete names. All plain table columns are aligned, with Source URL last. Flags appear beside each row. `--out` writes `results.md`, `results.csv`, and `raw-YYYYMMDD-HHMMSS.json`. The raw file contains request methods, paths, parameters, status codes, latency in seconds, costs, usage counts, and response bodies. A retry is recorded as a separate request. Failed runs also attempt to save request logs. Files with the same name are replaced; choose a separate output directory to retain separate runs. Logs can contain source page content.

Replay rebuilds results from saved responses without a key or network. It uses today's local date unless `--today` is supplied, and uses saved extraction responses when available. The recorded query is retained, and a new run time is written. Dry runs print the search calls and the maximum number of conditional extraction calls, without writing files or loading a key.

## Options

| Option | Meaning | Default |
| --- | --- | --- |
| `--field TEXT` | Field of study, required except for replay | None |
| `--level TEXT` | Study level, required except for replay | None |
| `--year YEAR` | Year to include in the query, required except for replay | None |
| `--count N` | Search result count: 10, 15, or 20 | 10 |
| `--limit N` | Maximum rows in stdout and Markdown; 0 shows all | 15 |
| `--hide-unclear` | Drop rows with an empty deadline or flagged `unclear if deadline` or `date negated by source` from stdout, Markdown, and CSV | Off |
| `--out DIR` | Directory for exports and request log | `./out` |
| `--key-file FILE` | File containing the API key | `~/.desearch_api_key` |
| `--no-js` | Disable the conditional JavaScript extraction retry | Off |
| `--no-web` | Skip the secondary web search | Off |
| `--verify N` | Maximum candidate pages to extract; 0 disables | 3 |
| `--timeout SECONDS` | Positive HTTP timeout; JS retry uses at least 45 seconds | 30 |
| `--today YYYY-MM-DD` | Reference date for filtering | Local date |
| `--dry-run` | Print planned calls without HTTP | Off |
| `--from-raw FILE` | Rebuild from a saved raw JSON file | None |
| `--help` | Show command help | Off |

## Endpoints

All calls use `https://api.desearch.ai`, `Authorization: <key>`, and `User-Agent: desearch-scholarship-finder/0.1`.

- `POST /search` sends `query`, `count`, and `highlights: true`. The query is `{field} {level} scholarships {year} application deadline`. The count follows the API's allowed values: 10, 15, or 20.
- `GET /web?query=...` uses `{field} {level} scholarships {year} deadline`. A 503 is reported as an unavailable source with its supplied cost kept.
- `GET /web/extract?url=...&format=text` reads plain text from up to the requested number of candidate pages. Pages with open dates are candidates; pages without dates are not extracted. Multiple rows on the same normalized URL share one verification. If extraction returns `error_code: js_required`, the URL is retried once with `js=true&wait=3000` (exactly lowercase `true`). The wait adds 3000 milliseconds after load and is sent only with JavaScript enabled. This retry uses a timeout of at least 45 seconds, unless `--no-js` is set. Both attempts are recorded in the raw log. Other extraction errors are not retried.

Authentication errors stop the run with `Authentication failed`. Search responses with 429 or 5xx status are retried once after two seconds. Other source failures are reported and remaining sources continue. If all search sources fail, the command exits unsuccessfully. Extraction failures leave the candidate rows visible. Extraction diagnostics on stderr include the error_code and detail, with the active key redacted.

## How dates are found

The parser accepts full or abbreviated English month names, day-first month names, ISO dates, and US numeric dates, with an explicit four-digit year. Missing spaces after commas or after a deadline label are accepted. Invalid dates, dates before the reference date, and dates more than two calendar years ahead are dropped. The reference date itself is included. Yearless dates and academic year ranges are skipped; no year is guessed. The requested year guides the search and does not override source dates.

A deadline keyword within 80 characters before a date marks it as a likely deadline: deadline, due, apply by, applications close, closes, by noon on, submit by, or until. Other dates remain visible with `unclear if deadline`. These may be publication dates, opening dates, or other events. Dates in negating context, including system-generated or placeholder dates, are rejected. If only negated candidate dates remain, the row has no deadline and is flagged `date negated by source`.

Explicit date ranges separated by a hyphen, en dash, `to`, or `through` create a candidate only for the end date, treated as an application deadline without requiring a keyword. Other dates each create a candidate row. A nearby phrase ending in Scholarship supplies the name when recognized; otherwise the page title is used. Dollar amounts are taken from the same nearby sentence, within about 150 characters of the date. Otherwise the amount is `not stated`. This is a text heuristic: nearby names or amounts may belong to a different award, particularly on lists.

Aggregator pages are detected using a small domain list in the code (`AGGREGATORS`) or at least three distinct dates preceded by deadline keywords. Edit that constant to customize the domain list. Verification prefers other pages, then earlier dates. Aggregator snippets can produce multiple rows, with names derived from nearby scholarship phrases. Missing publication metadata produces `no publish date`; source text containing a parsed date from at least two calendar years earlier produces `mixed old dates`.

Names and page titles replace U+2014 and U+2013 with ASCII hyphens in all result outputs; raw responses retain the originals. Duplicates merge by normalized URL, date, and normalized name. Specific scholarship names also merge across URLs on the same normalized host when normalized name, deadline, and amount match. The first URL is retained for different pages, with a flag such as `also on 1 more page` counting other distinct normalized URLs. Page-title fallback rows only use the original URL-based rule. URL normalization removes fragments, trailing slashes, tracking parameters beginning with `utm_`, and the leading `www.` host prefix. Normalization is only a dedupe and lookup key. Source URLs are preserved exactly for display, CSV, links, and extraction. When both sources return the same normalized page, the exact `/web` URL is preferred, even if its snippet has no dates. Endpoint labels show `search`, `web`, or both.

Confidence is `snippet only` until verification. A matching non-negated date in the extracted page becomes `confirmed on page` (or `confirmed on page (js)` after a JavaScript retry); an extraction without that date becomes `date not found on page`; an extraction error becomes `extract failed`. A matching date does not establish eligibility or official status. The unclear-deadline flag remains even after a date is confirmed. Extraction may omit page sections. Always check the official page before applying.

## Cost

JavaScript extraction with `js=true` uses a separate billing tier and may add cost to the initial extraction attempt. A successful `js=true&wait=3000` probe cost $0.0015, measured 2026-10-30 (17.6 seconds). Use `--no-js` to disable this retry.

The app prints `calls: N, cost: $X.XXXXX` to stderr after a run. Each HTTP attempt counts as a call. Search costs come from the JSON body's `cost_usd`; web search uses the body value when present, otherwise its cost header. Plain text extraction uses `X-Desearch-Cost-Usd`. Body and header costs are never added together for one request. Missing costs are recorded as zero, so the reported total only reflects available billing metadata. Usage counts are recorded when supplied. Replay reports the saved calls and costs and makes no new charged calls. Dry runs report zero calls and zero cost.

Sample run on 2026-10-30 (see sample-output.md): **6 calls, $0.00700 total**:

- `/search`: $0.005 for 10 results.
- `/web`: $0.001.
- Two `/web/extract` text calls: $0.0005 each.
- One `/web/extract` attempt returned HTTP 422 with `js_required`: $0, not charged.
- One `js=true` retry returned HTTP 503 with `upstream_failed`: $0, not charged.

## Sample output

Sample run on 2026-10-30, first six result rows. See [the complete sample output](sample-output.md) for the command, all ten displayed rows, and stderr cost line. Re-rendered from the saved raw response after the `--hide-unclear` fix; the UAB row is excluded.

| Name | Amount | Deadline | Confidence | Source URL | Endpoint | Flags |
| --- | --- | --- | --- | --- | --- | --- |
| Healthcare Scholarships: Invitation to Apply by Nov 13 \| Health Professions Advising | not stated | 2026-11-13 | confirmed on page | [source](<https://hpa.princeton.edu/news/healthcare-scholarships>) | search |  |
| 2027 Undergraduate Scholarship Application  \| FNSNA.ORG | not stated | 2027-01-11 | extract failed | [source](<https://www.fnsna.org/2027-undergraduate-scholarship-application>) | search | no publish date |
| Top 50 Nursing Scholarships in 2026 | $8,000 | 2027-02-02 | date not found on page | [source](<https://scholaroo.com/nursing-scholarships/>) | web | no publish date |
| Bachelor of Science in Nursing Academic Scholarships 2027 | not stated | 2027-02-11 | snippet only | [source](<https://usascholarships.net/scholarships/bachelor-of-science-in-nursing-academic-scholarships-usa-2027>) | web | no publish date |
| Jean Andrews Nursing Scholarship | $5,000 | 2027-02-12 | snippet only | [source](<https://www.scholarships.com/financial-aid/college-scholarships/scholarships-by-major/nursing-scholarships>) | web | no publish date |
| Nursing & Health Scholarships for College Students | not stated | 2027-02-25 | snippet only | [source](<https://scholarshipsclosingsoon.com/for/college/nursing/>) | web | no publish date |
