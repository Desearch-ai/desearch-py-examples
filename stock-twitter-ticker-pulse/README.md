# Stock Twitter Ticker Pulse
Made by Desearch ([https://desearch.ai](https://desearch.ai))

Build a daily Markdown and CSV board for a small stock watchlist. Uses GET /twitter with separate Latest + Top calls per ticker, merges duplicate posts, and drops rule-matched spam and off-topic posts. Retweets stay in the sample and are marked in the posts CSV.

## Setup

Python 3.10+ is required. No packages to install. Get a key at https://console.desearch.ai and set the environment variable DESEARCH_API_KEY, or use a private key file with `--key-file PATH`. The key file takes precedence and whitespace is stripped. Keep keys outside this repository.

## Run

```sh
python3 ticker_pulse.py NVDA TSLA AMD
python3 ticker_pulse.py '$NVDA' --watchlist watchlist.txt --count 30 --out output
python3 ticker_pulse.py NVDA --dry-run
python3 ticker_pulse.py NVDA --top-only --key-file /path/to/private-key
python3 ticker_pulse.py --from-raw output/raw-2026-10-28.json --out replay
```

Watchlist files contain one ticker per line; blank lines and `#` comments are supported. Tickers normalize to uppercase, deduplicate in input order, and must have 1 to 6 letters.

| Option | Default | Meaning |
| --- | --- | --- |
| --watchlist FILE | none | Add tickers from a file |
| --max-tickers | 10 | Refuse larger watchlists |
| --count | 20 | Posts requested per call, 1..100 |
| --lang | en | Language; pass `--lang ''` to omit |
| --days | 3 | Top start_date: UTC today minus days |
| --min-likes | 50 | Top call minimum likes |
| --latest-only / --top-only | both sorts | Select one sort |
| --max-cashtags | 5 | Drop posts at or above this distinct cashtag count |
| --timeout | 60 | Request timeout in seconds; timeouts are recorded without retry |
| --anonymize | off | Replace usernames and X/Twitter post URL accounts with stable account-1, account-2 labels in Markdown and CSV; raw JSON stays unchanged |
| --out | output | Output directory |
| --key-file PATH | none | Read API key instead of environment |
| --dry-run | off | Print planned calls without a key or API calls |
| --from-raw FILE | none | Render saved data without a key or API calls |

## Outputs

Files use the UTC run date: `board-DATE.md`, `board-DATE.csv`, `posts-DATE.csv`, `costs-DATE.csv`, and `raw-DATE.json`. Posts CSV includes every unique post per ticker, including dropped posts and reasons. Raw JSON preserves the response sample and call metadata without credentials. Treat public post text and URLs as untrusted content.

Replay uses the original date and filtering parameters, writes the Markdown and CSV files but no new raw file, and reports zero new spend alongside the original run cost. Exit status is 0 for a successful call, replay, or dry run; 1 when every call fails; 2 for invalid CLI input or missing credentials.

## Filters

Posts are deduplicated by ID per ticker before filtering. The two groups are:

- Spam: `invite_link` matches chat.whatsapp.com, wa.me/, t.me/, telegram.me, discord.gg, or discord.com/invite in text or expanded entity URLs.
- Spam: `group_pitch` matches any of these phrases in text, case-insensitively: join my group, join our group, join my whatsapp, join the group, whatsapp group, telegram group, telegram channel, our group, this community, join our community, join my community, free group, free signals, dm me for, link in bio, join us on telegram, join us on whatsapp.
- Spam: `watchlist_spam` matches at least `--max-cashtags` distinct cashtags (default 5), including the searched ticker, across text and entities.symbols.
- Off-topic: `off_topic` means both post text and entities.symbols lack the searched $TICKER. The company name alone does not qualify.

Spam wins when a post matches both groups. Board Spam and Off-topic counts and shares use these exclusive groups, with unique posts as the denominator. Kept posts match no rules. Per-ticker sections show both counts and reason breakdowns; reason counts can overlap. Posts CSV includes `filter_group` (`kept`, `spam`, or `off_topic`) and all matching reasons in `spam_reasons`. Board CSV includes `spam_dropped`, `spam_share`, `off_topic`, and `off_topic_share`; shares are percentages.

The rules can miss spam or over-drop legitimate list posts, such as daily options movers with 5+ cashtags. Tune with `--max-cashtags` to raise or lower that threshold.

Per-ticker Top window shows the oldest and newest valid created_at among kept Top posts, plus minimum and maximum likes among kept Top posts. This exposes how far back the returned Top sample with min_likes reached. Empty windows or bounds show unknown. Invalid dates do not contribute to either sort's window.

## Sample output

`sample-output.md` is produced with `--anonymize` from a real run.

| Ticker | Returned | Spam | Off-topic | Kept | Latest span (h) | Top post likes | Tilt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NVDA | Latest: 20; Top: 20 | 7 (17.5%) | 0 (0.0%) | 33 | 0.7 | 1184 | more bullish words |
| TSLA | Latest: 20; Top: 20 | 1 (2.5%) | 10 (25.0%) | 29 | 5.6 | 347 | more bullish words |
| SOFI | Latest: 20; Top: 20 | 0 (0.0%) | 0 (0.0%) | 40 | 5.5 | 1732 | more bullish words |

```sh
python3 ticker_pulse.py NVDA --timeout 60 --anonymize --out sample
```

## Cost

Each call is billed per the X-Desearch-Cost-Usd response header. On 2026-10-28 every X search call with count=20 cost $0.003, so one ticker (Latest + Top) cost $0.006 and a 3-ticker run (NVDA, TSLA, SOFI, 6 calls) cost $0.018 and took about 55 seconds. Use --dry-run to see the planned calls first, and --latest-only or --top-only to halve the calls. Prices can change; check the totals the script prints.

Up to two billed calls per ticker. Actual cost is read from X-Desearch-Cost-Usd; missing or invalid values display as unknown and count as zero with a note. X-Desearch-Usage-Count is retained when returned. No requests are retried automatically, because another request can be billed again. A 503 is uncharged; errors are recorded and the next planned call proceeds.

Live runs print total cost, call count, unknown-cost call count, and the output folder path to stderr.

## Known limits

A slow Latest call can time out after it is billed; raise `--timeout` if needed.

This is a sample, not total volume. There is no paging, and busy tickers return only the newest requested count. Each ticker is searched separately so one ticker cannot dominate an OR query. min_likes narrows Top by engagement but does not guarantee relevance or remove spam. The rules-based spam filter can miss spam or over-drop useful posts. start_date is a UTC day. Posts with invalid dates stay in the sample but do not contribute to the Latest time span. Keyword tilt counts words, not sentiment or trading opportunities. Not investment advice.

## Offline tests

From this directory:

```sh
python3 -m unittest discover -s tests -v
uv run --python 3.10 python -m unittest discover -s tests
```

Tests use synthetic posts, mocked HTTP responses, and no network calls.
