# Wikipedia Primer: a Wikipedia search API for agents (Desearch MCP)

Made by Desearch, https://desearch.ai

Use Desearch as a Wikipedia search API for agents: ask a question in plain words and get back clean Wikipedia articles with links, plus a short summary where each fact keeps its source. This folder turns that into a short, Wikipedia-grounded primer on any topic: a plain summary with a link after each fact, the related Wikipedia pages, and an optional web cross-check. A saved prompt for Cursor or Claude does it with no code. The tiny Python CLI calls the hosted Desearch MCP `ai-search` tool with the `wikipedia` source and, with `--web`, the `web-search` tool.

In plain words, the CLI keeps only real articles, keeps only results whose title matches the page they link to, and keeps a summary sentence only while it still has a source. If you build your own agent, `clean_pages()` in `wikipedia_primer.py` gives you the cleaned list of pages (title, link, language) and, if you pass it a list, what it left out and why.

What the CLI does with the results:
- keeps only Wikipedia article links (`https://<language>.wikipedia.org/wiki/<page>`) and marks pages that are not in English
- drops pages that are not articles: `Talk:`, `User:`, `File:`, `Category:`, `Template:`, `Help:`, `Portal:`, `Wikipedia:`, `Draft:`, `Special:`, `Module:`, `MediaWiki:`, `Book:`, `TimedText:` and the other Wikipedia namespaces, plus the "talk" variants such as `User talk:`. It checks both the link and the title.
- drops a page when its title does not match the page it links to (see the rule below)
- removes summary links to pages it left out, and leaves out a fact whose only link was one of those pages
- swaps citation numbers for the page link
- keeps a fact with a number only if a returned page shows that number, re-links it to the page that does, or leaves it out with a note

## Setup
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# put your key from console.desearch.ai in a file only you can read
echo "<your key>" > ~/.desearch-api-key && chmod 600 ~/.desearch-api-key
```
The script reads the key from `~/.desearch-api-key` (or `--key-file PATH`) and prints only the last 4 characters of its sha256.

## Run
```
python wikipedia_primer.py "carbon credits"
python wikipedia_primer.py "retrieval-augmented generation" --web
```

## How the title check works
Sometimes a result's title names one page while its link opens another, for example the title "Climate finance" with the link `/wiki/Carbon_finance`. The CLI leaves those out, because you cannot tell which page the summary used.

The rule: take the title and drop the site name at the end (" - Wikipedia" and its versions in other languages). Take the part of the link after `/wiki/`, decode it (`%C3%A9` becomes `é`) and cut anything after `#`. In both, turn underscores into spaces and ignore upper and lower case. If the two are not the same text, the page is left out. Each page that is left out is listed under "Notes" with the reason.

Only the English names of Wikipedia namespaces are checked. On other language editions a page in a translated namespace can still get through, but it will usually fail the title check.

## Sample output
`sample-output.md` is the CLI output for "carbon credits" with `--web`, built from saved tool results of 2026-10-04. `samples/live-run-2026-10-19.md` is a live run of the same command on 2026-10-19.

## No-code version
Paste the prompt in `saved-prompt.md` into Cursor or Claude with the Desearch MCP server connected (`https://mcp.desearch.ai/mcp`, key in the `Authorization` header). The assistant also picks neutral web sources and writes the "What to read next" list.

## Tests (offline, no key needed)
```
pytest -q tests
```
