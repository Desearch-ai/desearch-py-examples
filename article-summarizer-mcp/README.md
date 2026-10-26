# Article Summarizer (Desearch MCP)

Made by Desearch, https://desearch.ai

Paste an article link and get the main points and the numbers it mentions, taken only from the text Desearch could fetch from the page. It uses the hosted Desearch MCP server: the `extract` tool reads the page as plain text, and the optional `ai-search` tool (web) finds other pages on the same story.

There are two ways to use it:
- **No code:** paste `saved-prompt.md` into Claude or Cursor with the Desearch MCP server connected. Your assistant reads the article and writes 5 bullets plus "Numbers mentioned" (example: `sample_summary.md`).
- **Small script:** `article_summarizer.py` makes the same calls and prints 5 key sentences and the sentences that carry figures, quoted as written, with no rewriting (example: `sample_output.md`).

## Setup
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```
Get an API key at console.desearch.ai and save it in a file only you can read:
```
printf '%s' 'YOUR_KEY' > ~/.desearch-api-key && chmod 600 ~/.desearch-api-key
```
The script reads the key from `~/.desearch-api-key` (or `--key-file PATH`) and prints only the last 4 characters of its sha256 fingerprint.

## Run
```
python article_summarizer.py https://www.theguardian.com/technology/2026/oct/18/world-bank-artificial-intelligence-developing-economies
python article_summarizer.py <link> --related             # also list other pages on the same story
python article_summarizer.py <link> --raw raw.json
python article_summarizer.py <link> --from-raw raw.json   # rebuild the summary, no API calls
```
Options: `--related` (one extra ai-search call), `--bullets` (key sentences to keep, default 5), `--raw` (save the responses), `--from-raw` (work offline from a saved file), `--key-file`.

## What it does
1. `extract` with `format: "text"` and `js: false` on your link. If the page comes back with no content, it tries once more.
2. If the text is under 150 words (a login page or an app shell, for example), it says so and stops instead of guessing.
3. Picks the opening sentence plus the 4 sentences that share the most words with the rest of the article, in article order.
4. Lists the sentences that carry figures written as digits (amounts, percentages, counts). Bare years are skipped. Footnote markers such as [1] do not count as figures. Short navigation notes, such as "For other uses, see ..." lines, are skipped.
5. With `--related`: `ai-search` with `tools: ["web"]`, `result_type: "ONLY_LINKS"` and the words from the link, then shows up to 3 links from other sites.

## Sample output (2026-10-18)
```
Article: https://www.theguardian.com/technology/2026/oct/18/world-bank-artificial-intelligence-developing-economies
Text Desearch fetched: 616 words

Key points (sentences quoted from the article):
- The World Bank is urging developing countries to kickstart the creation of “small AI” models, which can run on a mobile phone with low connectivity, to reap the full benefits of artificial intelligence.
...
Numbers mentioned:
- 40%: "Georgieva warned that over time 40% of jobs worldwide were likely to be either augmented or eliminated by AI, with the impact particularly acute for young people at the start of their careers."
...
```
Full output: `sample_output.md`.

## Good to know
- It summarizes the text Desearch could fetch. Pages behind a login, or pages that only show their text after scripts run, can come back nearly empty, and the script tells you so.
- The script only picks sentences; it does not rewrite them. Use the saved prompt if you want bullets in plain words.
- Figures written as words ("a third") are not picked up by the script. Your assistant catches those with the saved prompt.
- Docs and tutorial pages work, but code samples on them show up in "Numbers mentioned". It reads best on news and blog articles.
- The related links are found from the words in the link, so they are often about the wider topic, not the same story. Open them before you share.

## Tests (offline, no key needed)
```
pytest -q tests
```
