# Sample output

Made by Desearch · https://desearch.ai

Run on 2026-10-14 09:30 Asia/Tbilisi:

```bash
python swipe.py "mobile apps" --terms "iOS app" "mobile app" "Android app" "App Store" --min-likes 50 --compare
```

Public X video posts Desearch returned for this search: 26 from the Top pass and 50 from the Latest pass, 61 unique. The script kept the 15 most-liked (one per author) and refreshed their metrics by URL. Files: `samples/swipe.csv`, `samples/swipe.md`.

First rows of `swipe.csv`:

| rank | opening | date | author | likes | hook |
|---|---|---|---|---|---|
| 1 | announcement | 2026-10-13 | a creator | 6015 | You waited; you yearned… |
| 2 | announcement | 2026-09-28 | a creator | 1351 | Introducing Built on iPhone. |
| 4 | announcement | 2026-10-01 | a creator | 758 | Introducing Conductor Mobile! |
| 6 | announcement | 2026-10-13 | a creator | 730 | Introducing Selfdrive. |

Groups in `swipe.md` for this run: announcement 11, demo-first 2, problem-first 1, other 1. Some kept posts were news or promos that used launch wording, so read each one before you use it.
