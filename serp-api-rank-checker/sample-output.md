# Sample output

Made by Desearch | https://desearch.ai

Run on 2026-10-16 at 11:54 (Asia/Tbilisi), 10 keywords, domain `desearch.ai`, `--pages 2 --step 20`, diffed against a run at 11:52. 20 calls, header total $0.02.

```
serp api                                 not in top 37
web search api                           12
search api for ai agents                 not in top 39
twitter search api                       11
ai search engine api                     not in top 40
bittensor subnet 22                      not in top 38
decentralized search engine              16
x posts search api                       not in top 14
json search results api                  4
search api for llm                       not in top 40
diff decentralized search engine         16 -> 16 (same)
diff json search results api             4 -> 4 (same)
diff twitter search api                  11 -> 11 (same)
diff web search api                      12 -> 12 (same)
diff x posts search api                  4 -> None (dropped out)
20 calls, header total $0.020000
```
(Unchanged "None -> None" diff lines trimmed.)

`samples/results-sample.csv` shows the first 12 rows for two keywords. Pages that are not the checked domain are masked as `[tool]`. `samples/summary.json` is the full summary from this run.

"x posts search api" dropped out because that query only returned 14 unique results on this run, and the earlier match was not among them. Low-result keywords move more between runs, so check them twice before acting.
