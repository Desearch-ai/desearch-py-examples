# Hiring Signal Radar

Made by [Desearch](https://desearch.ai).

Which companies are hiring for the role your product helps? Give the script one role. It collects public posts and job pages found by search from the last 30 days with the Desearch API, reads each job page, pulls out company, role, location and date, scores each company and writes a ranked CSV plus an "accounts worth researching" list with source links.

Output is company-level only. Posts from recruiters, job boards and people are used only for the company they name; their handles are never saved in `output/`, and their post links use the handle-free `https://x.com/i/status/<id>` form.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # create a key at console.desearch.ai
```

## Run

```bash
python hiring_signal_radar.py --role "data analyst"
python hiring_signal_radar.py --role "data analyst" --x-keyword "crypto OR web3 OR blockchain OR onchain OR defi" --web-keyword crypto
python hiring_signal_radar.py --from-raw output/raw-2026-10-10-data-analyst.json   # offline, no API calls, no cost
```

Options: `--days` (default 30), `--fresh-days` (default 14), `--x-query` (repeatable template, `{role}` is replaced), `--x-count` (1 to 100, default 50), `--boards` (comma-separated job board domains), `--web-start` (comma-separated `start` values, default `0`), `--max-pages` (job pages to read, default 160), `--no-html-dates`, `--labels` (CSV `username,label` to set the poster type by hand), `--exclude` (companies to leave out), `--redact` (words to replace in saved titles), `--full-raw <path>` (keep every response, including post text, in a private file), `--today` (UTC date to count back from).

Endpoints used:
- `GET https://api.desearch.ai/twitter?query=...&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&sort=Latest&count=50`: hiring posts on X
- `GET https://api.desearch.ai/web?query=<role> site:<job board>`: job pages on public job boards
- `GET https://api.desearch.ai/web/extract?url=<page>&format=text&js=false`: page text (company, role, location, open or closed)
- `GET https://api.desearch.ai/web/extract?url=<page>&format=html&js=false`: only when the text has no date, to read the page's `datePosted`

## How it works

1. **X posts.** Default queries: `"we're hiring" "<role>"`, `"we are hiring" "<role>"`, `"is hiring" "<role>"`, plus `hiring "<role>" (<keyword>)` with `--x-keyword`. Each runs twice: the last 14 days, and days 15 to 30 (`start_date` / `end_date`), with `sort=Latest`. Two windows let one query return up to 2 x `count` posts.
2. **Job pages.** One `GET /web` call per board with `site:<board>` (default boards: `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`), plus a `<role> <keyword>` variant with `--web-keyword`. Only URLs that look like a single job (board, company, job id) are kept.
3. **Read.** Extract with `js=false`, `format=text`, retried once if no text comes back (both tries are logged). If the text has no date, one `format=html` read looks for `datePosted`. A page whose html points back to the company's board, or whose text does not name the role, is counted as closed and not used.
4. **Poster type.** Each X post is tagged `company` (the employer's own account), `agency` (recruiter, agency, job board or job-sharing account) or `individual`. A keyword heuristic sets the tag; `--labels` overrides it.
5. **Company.** Own account: its display name. Other posters: the company named in the text ("Company: X", "X is hiring", "we're hiring at X"). Job pages: the page title or the board URL. Names are merged after removing suffixes such as Inc or Careers.
6. **Score per company** = 3 x role match (1 exact role, 0.5 related) + 3 x freshness (1 within 14 days, 0.5 within 30, 0.25 no date, 0 older) + distinct roles (max 3) + 2 if both an X post and a job page + 1 if the company posted from its own account.

## Output (in `output/`)

- `<date>-<role>-accounts.md`: the "accounts worth researching" list (score 6 or more, top 15) and the cost line
- `<date>-<role>-companies.csv`: every company with score, signal counts, roles, newest signal age, locations and source links
- `<date>-<role>-x-posts.csv`: one row per X post: date, poster type, company, role, location (no text, no individual handles)
- `<date>-<role>-job-pages.csv`: one row per job page: company, role, location, date and where it came from, open or closed, both Extract tries
- `<date>-<role>-costs.csv`: every call with status, items, billed units and the `X-Desearch-Cost-Usd` header
- `<date>-<role>-roles-per-company.png`: signals for the top companies
- `raw-<date>-<role>.json`: parsed records and the call log, for `--from-raw`

## Sample (measured on 2026-10-10, 09:42 to 09:48 Asia/Tbilisi)

Role: data analyst, with a crypto keyword for one X query and four job-board queries. Command:

```bash
python hiring_signal_radar.py --role "data analyst" --x-keyword "crypto OR web3 OR blockchain OR onchain OR defi" \
    --web-keyword crypto --today 2026-10-10 --labels <your labels CSV> --exclude "<names>" --full-raw <private path>
```

- X: 8 calls, 130 posts returned, 123 unique. All 123 fell inside the requested date windows and every `sort=Latest` call came back newest first.
- Poster types (labelled by hand with `--labels`): 8 posts from companies' own accounts, 90 from recruiters, job boards and job-sharing accounts, 25 from individuals. The keyword heuristic alone matched the hand labels on 107 of 123 posts.
- 60 of 123 posts named a company.
- Web: 8 calls, 160 results, all 160 on the requested job-board domain. 150 job pages read: 21 were open postings, 64 showed a closed posting, 65 returned no text with `js=false` after 2 tries, mostly pages that need JavaScript to render.
- 10 of the 21 open pages carried a posted date (from the page's `datePosted`); their ages were 37 to 82 days. Every X post has a date.
- 70 companies (53 from X posts, 19 from job pages, 2 from both); 35 scored 6 or more.
- The full run cost $0.1125 (324 calls, sum of the `X-Desearch-Cost-Usd` headers) and took about 5.5 minutes with 3 Extract workers.

## Notes

- A hiring post is a timing signal, not proof that a company will buy. Check each account before you reach out.
- Many hiring posts on X come from job-sharing accounts. Use `--labels` to tag posters by hand for a list you plan to act on.
- Wrap OR terms in parentheses, as in `("we're hiring" OR "we are hiring") "data analyst"`.
- Job pages found by search can be older than the window. The script reads each page and keeps only open postings; check the `date` column in the job-pages CSV.
