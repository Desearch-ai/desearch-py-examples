# Repo Buzz Tracker

Made by Desearch · https://desearch.ai

A small Python CLI for open-source maintainers: give it a GitHub `owner/repo`, get back `mentions.csv` and a day-by-day `buzz.md` built from the public posts and pages Desearch returned for that repo.

## What it does

1. **Search X twice, separately.** Desearch X Search (`GET /twitter`) with a URL query, `("github.com/<owner>/<repo>" OR "<owner>/<repo>")`, and a name query, `("<repo>")` (plus a spaced form for names with dashes). Every OR group is in parentheses. Each query runs one `sort=Latest` pass and one `sort=Top` pass with `start_date` = N days ago (UTC) and `count` 50.
2. **Check each post.** Every post is tagged by how it points at the repo: `url` (a link that expands to the repo), `owner/repo` (the text), `name+context` (the name next to words like GitHub, repo, open source), `name-only`, or `x-article` (a long-form X Article whose text is not in the result). Posts created before `start_date` 00:00 UTC are dropped in code. `--strict` keeps only the first three tags.
3. **Replies.** `GET /twitter/replies/post` with `count` 20 on the 3 loudest kept posts (likes + 2 x reposts + replies).
4. **Web pages.** `POST /desearch/ai/search/links/web` with `tools: ["web"]` and `count: 10`. Default prompt `"<owner>/<repo> github"`; change it with `--web-prompt`.
5. **Write output.** `mentions.csv` (date, source x|web, match, author, url, likes, reposts, replies, snippet, found_by) and `buzz.md` (day-by-day table, the 3 loudest posts with the replies returned, web pages). Post links use the form `https://x.com/i/status/<id>`, and in `buzz.md` individual authors show as "a developer" (org accounts keep their name) with @mentions replaced by `@user`.

Tip: check post dates. Each row carries its date, and the script filters on it in code.

Counts are what the search returned for your query and window. They are not a full count of every post about the repo. Posts near a star jump are shown side by side only; read them as timing, not cause and effect.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # pytest only; the CLI uses the standard library
echo "<your key from console.desearch.ai>" > ~/.desearch_key && chmod 600 ~/.desearch_key
export DESEARCH_API_KEY_FILE=~/.desearch_key     # or DESEARCH_API_KEY; the file wins when both are set
```

## Run

```bash
python repobuzz.py heygen-com/hyperframes
# options: --days 14  --count 50  --replies 20  --web-prompt "..."  --strict  --out runs
python repobuzz.py --render runs/<run folder>    # rebuild mentions.csv and buzz.md from raw/, no API calls
pytest -q test_repobuzz.py                       # offline tests
```

Each run writes `runs/<timestamp>-<owner>-<repo>/`: `mentions.csv`, `buzz.md`, `snapshot.json` (per-pass counts and match tags), `calls.jsonl` (one line per call with status, latency, items and cost) and `raw/` (each response). The key goes only in the `Authorization` header; the client refuses to write a file that contains it. Requests send their own `User-Agent`.

## Cost

Each response carries `X-Desearch-Cost-Usd`, and `calls.jsonl` records it (`cost_source: header`). If a header is missing, the script writes a calculated X Search value from the public rate and labels it `calculated`. My sample run (8 calls: 4 X Search passes, 3 replies calls, 1 web call) cost **$0.0325** by the headers on 2026-10-13.

## Sample output

See `sample-output.md` and `samples/` (run of 2026-10-13 09:37 Asia/Tbilisi on `heygen-com/hyperframes`, a repo on GitHub's weekly trending page that day).

## Known issues

- The web call can return the repo's own GitHub pages or general pages on the topic; a more specific `--web-prompt` (for example the project name plus "open source") gave more third-party write-ups.
- X Article posts come back without their article text, so the script cannot check them and leaves them out.
