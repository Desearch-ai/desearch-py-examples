# Sample output

Made by Desearch · https://desearch.ai

Run on 2026-10-15 at 15:35 Asia/Tbilisi with `python page2md.py urls.txt --out out/` over 10 URLs: 3 static pages, 3 docs pages, 2 news pages, 1 page that builds its content with JavaScript, and 1 URL that does not exist.

Console output:

```
200 24w a=1 1.07s $0.0005 https://example.com
200 4031w a=1 2.22s $0.0005 https://www.gnu.org/philosophy/free-sw.en.html
200 3194w a=1 1.3s $0.0005 https://en.wikipedia.org/wiki/Markdown
200 2539w a=1 1.09s $0.0005 https://docs.python.org/3/tutorial/introduction.html
200 403w a=1 1.94s $0.0005 https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
200 2620w a=1 3.72s $0.0005 https://requests.readthedocs.io/en/latest/user/quickstart/
200 1215w a=1 4.83s $0.0005 https://www.bbc.com/news/technology
404 0w a=1 6.84s $0.0000 https://apnews.com/technology
200 EMPTY 0w a=2 1.8s $0.0010 https://app.element.io/
404 0w a=1 5.35s $0.0000 https://www.gnu.org/page-that-does-not-exist-404
done: 10 URLs, 11 calls, header total $0.0045
```

7 of 10 URLs became Markdown files. The JavaScript page returned its HTML shell with no readable text on both tries, and two URLs returned 404 with no charge in the cost header.

Files in `samples/`:

- `run-summary.md`: the summary table from this run
- `01-example-com.md`, `04-docs-python-org-3-tutorial-introduction-html.md`, `06-requests-readthedocs-io-en-latest-user-quickstart.md`: Markdown pages from this run, re-rendered from the saved responses with the current converter (word counts differ slightly from the console output above because navigation blocks are now dropped)

Start of `04-docs-python-org-3-tutorial-introduction-html.md`:

```markdown
---
source: https://docs.python.org/3/tutorial/introduction.html
title: "3. An Informal Introduction to Python - Python 3.15.0 documentation"
fetched: 2026-10-15T15:35:58+04:00
status: 200
attempts: 1
words: 2459
---

# 3. An Informal Introduction to Python

In the following examples, input and output are distinguished by the presence or absence of prompts ...
```
