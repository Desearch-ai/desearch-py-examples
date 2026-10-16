# Launch Quote Ledger

Made by [Desearch](https://desearch.ai).

Give it a few product launch posts on X. For each one it fetches the post by id, finds the quote posts that quote it, and writes a ledger of who quoted the launch, what they said, and any disclosure wording found in public text (for example #ad, sponsored, partner).

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DESEARCH_API_KEY=...   # your key from console.desearch.ai
```

Environment variables (names only):

| Variable | Meaning |
|---|---|
| `DESEARCH_API_KEY` | your API key |
| `DESEARCH_API_KEY_FILE` | optional: path to a file holding the key, used when `DESEARCH_API_KEY` is not set |

The key is sent only in the `Authorization` header and is never written to output.

## Run

```bash
python launch_quote_ledger.py config.json
python launch_quote_ledger.py --from-raw path/to/raw.json   # offline rebuild, no API calls
```

`config.json` lists the launch posts (id and author) and `count` (quotes per call).

A live run writes `output/` and `evidence/raw-<date>.json`. Both folders are gitignored.

| Flag | Default | Meaning |
|---|---|---|
| `config` | `config.json` | launch posts and count |
| `--from-raw PATH` | | rebuild the ledger from a saved raw file |
| `--out DIR` | `output` | output folder |

Offline tests (no API calls): `pytest -q test_launch_quote_ledger.py`.

## How it works

Base URL `https://api.desearch.ai`, header `Authorization: <key>`.

1. `GET /twitter/post?id=<post id>` loads the launch post (text, quote count, date).
2. `GET /twitter?query=quoted_tweet_id:<post id>&is_quote=true&count=20&sort=Latest` returns quote posts of that launch. `quoted_tweet_id:` is an operator that worked in testing, not a documented feature. On 2026-10-15 every result of this query quoted the launch post (60 of 60 over 3 launches).
3. Each quote is checked against the launch id (`quoted_status_id`), then scanned for disclosure wording.

The same run also compares three other queries (`url:<post url>`, the author handle with `is_quote=true`, and that handle with `blue_verified=true`) and writes the counts to `variant-stats.csv`. It sends three probe calls as well: an unknown post id, a non-numeric id, and a nonsense quote search. Those probes are stored in the raw file.

Tips from the build:

- Filter on `quoted_tweet_id:` rather than the author handle. A handle search with `is_quote=true` also returns quotes of the author's other posts.
- `blue_verified=true` keeps only verified quoters.
- The disclosure column shows wording found in public text, not a judgement. Read the sentence: "Not sponsored" also contains "sponsored". The ledger marks those in a `negated` column.

## Output

- `output/quotes.csv`: one row per quote (launch, quoter, date, likes, views, disclosure wording, text).
- `output/quotes.md`: per-launch table. Quoters are shown as Account A, Account B and so on.
- `output/variant-stats.csv`: results per query variant.

Sample from the 2026-10-15 run: `sample-output.md` and `samples/`.

## Cost

Measured on 2026-10-15 from the `X-Desearch-Cost-Usd` response header. Each `quoted_tweet_id:` call that returned 20 quotes cost $0.003. Per-call cost is in `samples/variant-stats.csv` and on stderr.
