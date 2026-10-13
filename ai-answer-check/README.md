# AI Answer Check (Desearch API example)

Made by Desearch. Built with the [Desearch API](https://desearch.ai) (https://desearch.ai).

A small Python CLI that asks your buyers' questions to an AI answer built from live web and X sources (Desearch AI Search) and tells you whether your brand is in the answer. Give it your brand, a few competitors and 15 to 20 buyer questions. It asks each question 3 times with a fixed system message and records, per answer:

- whether your brand is named, and its position among the brands you listed (1 = named first)
- which of the other brands are named
- the sentence that names your brand
- the domains the answer links to

It writes:

- `answer-check.md`: a share-of-answer table, a per-question table (named in how many runs, positions, same brand set or not, cited-domain overlap), the top cited domains, the top source domains, every sentence that describes your brand, and a cost line
- `runs.csv`: one row per answer
- `snapshot.json`: every answer, its sources, the per-run analysis and every call with status, latency, units and cost
- `raw/`: raw responses (the key is never written; `--no-raw` to skip)

It reads public sources only and does not post anything.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai
```

| Variable | Meaning |
|---|---|
| `DESEARCH_API_KEY` | your API key |
| `DESEARCH_API_KEY_FILE` | optional: path to a file holding the key, used when `DESEARCH_API_KEY` is not set |

## Run

```bash
python answercheck.py examples/project-management.json --runs 3
```

Output goes to `runs/<timestamp>-<brand>/`. See `sample-output.md` (my run on 2026-10-10 09:29 Asia/Tbilisi: 18 questions about project-management tools, 3 runs each, Asana as the example brand).

The config is one JSON file:

```json
{
  "brand": {"name": "Asana", "aliases": []},
  "competitors": [
    {"name": "monday.com", "aliases": ["monday work management"]},
    {"name": "Notion", "aliases": [], "case_sensitive": true}
  ],
  "questions": ["best project management tool for a 5-person remote team", "Asana alternatives"]
}
```

Names match whole words, case-insensitive. Set `case_sensitive` for names that are also common words ("Notion" vs "the notion that").

| Flag | Default | Meaning |
|---|---|---|
| `config` | | JSON file with brand, competitors and questions |
| `--runs N` | 3 | runs per question |
| `--system-message TEXT` | neutral buyer's advisor prompt | sent as `system_message` on every call |
| `--tools a,b` | `web,twitter` | AI Search `tools` |
| `--count N` | API default (10) | results per source, 10 to 200 |
| `--date-filter X` | off | `PAST_24_HOURS` ... `PAST_2_YEARS` |
| `--questions N` | all | only the first N questions |
| `--ab N` | 0 | also ask the first N questions without the system message, and add a with/without table |
| `--max-spend USD` | 0.50 | stop calling once the run has cost this much |
| `--out DIR` | `runs` | output folder |
| `--no-raw` | off | do not save raw responses |
| `--reanalyse RUN_DIR` | | re-score a previous run's saved answers with an edited config (new competitor, new alias). No API calls, no cost |

Offline tests (no network, no key): `pytest -q test_answercheck.py`.

## How it works

Base URL `https://api.desearch.ai`, header `Authorization: <key>`.

1. One call per question and run:

   ```
   POST /desearch/ai/search
   {"prompt": "<question>", "tools": ["web", "twitter"], "result_type": "LINKS_WITH_FINAL_SUMMARY",
    "system_message": "<fixed prompt>", "streaming": false}
   ```

   With `"streaming": false` the response is one JSON object: `completion` (the answer, Markdown with `[n](url)` citations), `search` (10 web results with `title`, `link`, `snippet`, `highlights`), `tweets` (10 X posts), plus `cost_usd`, `usage_count`, `service` and `currency`. Leave out `streaming` and you get a server-sent event stream instead.
2. The answer text is cleaned (links, citation numbers and Markdown removed, HTML links reduced to their text) before brand matching, so a link to `asana.com` does not count as naming Asana.
3. Position = the order in which your listed brands are first named. The brand sentence is the first sentence that names your brand.
4. Cited domains come from the links inside the answer (`[n](url)`, HTML links and bare URLs). Source domains come from the `search` and `tweets` lists.
5. Share of answer = answers that name a brand / all answers. Because "Asana alternatives" names Asana in the question, the table also shows the share over questions that do not name that brand.
6. Cost comes from the `X-Desearch-Cost-Usd` header of each response. Calls that fail with 429, 5xx or a network error are retried once.

## Cost

Measured on 2026-10-10 (Asia/Tbilisi) from the `X-Desearch-Cost-Usd` response header:

- `python answercheck.py examples/project-management.json --runs 3 --ab 3`: 63 calls, 630 billed units, **$0.252**. Every call cost $0.004 (10 units at the AI Search rate of $0.40 per 1,000 items on [desearch.ai/pricing](https://desearch.ai/pricing), checked 2026-10-10).
- A plain 18 questions x 3 runs check is 54 calls, $0.216.

## Tips

- The same question gives different answers from run to run. In my run, only 5 of 18 questions named the same set of brands in all 3 runs, so read the share over 3 or more runs, not one answer.
- Ask the questions your buyers ask without your name in them ("best project management tool for a team of 50 people"). Those decide your share; "<brand> alternatives" almost always names the brand.
- `system_message` controls language and format well: "Reply only in French. List exactly 3 products as a numbered list" was followed in 3 of 3 answers. A softer "act as a neutral advisor" prompt did not change which brands were named compared with no system message (see the with/without table in `sample-output.md`).
- The top cited domains are review and comparison pages. In my run the most cited were thedigitalprojectmanager.com, hive.com, zapier.com and cloudwards.net.
- Use `--reanalyse` to add a competitor you spotted in the brand sentences without paying for the questions again.

## Known issues

Seen on 2026-10-10; details and evidence are in `report.md`.

- X posts returned with the answers were mostly not about the question (I judged 23 of 180 on topic in one run of each question), and X posts were linked in only 5 of 54 answers. Web results were on topic (0 of 180 off topic). If you only care about the web side, use `--tools web`.
- In a few answers a citation number links to an X post although the sentence comes from a web page. Check a surprising citation against the `search` list in `snapshot.json`.
- 1 of the 63 answers in my run contained HTML links (`<a href="...">Name</a>`) instead of Markdown links. The tool parses both.
- Citation numbers follow the order of a combined source list that is sometimes X first and sometimes web first, so do not map `[n]` to a list position yourself; use the URL in the link.
- Every answer starts with two newlines; some web results from Reddit carry the title "Welcome to Reddit" instead of the thread title.
- Send `"streaming": false` to get one JSON body.
- Latency in my runs: 5.5 to 11.0 s per call (median 9.3 s, 63 calls). 18 questions x 3 runs take about 9 minutes.
