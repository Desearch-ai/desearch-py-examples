# Sample output

Made by Desearch · https://desearch.ai

Run on 2026-10-15 18:28 Asia/Tbilisi:

```bash
python tweets_csv.py "home espresso" "espresso machine" --days 7 --sort Latest --count 50 --lang en
```

Query sent: `("home espresso" OR "espresso machine")`, `start_date` 2026-10-08. Desearch returned 50 public posts and all 50 were inside the date window. Files: `samples/posts.csv`, `samples/snapshot.json`.

First rows of `posts.csv`:

| date | text | likes | replies | author |
|---|---|---|---|---|
| 2026-10-15 14:23 UTC | Tomorrow morning an espresso from my espresso machine and a grilled blueberry cheese sandwich is calling my name. | 0 | 1 | a user |
| 2026-10-15 14:14 UTC | shopping for an espresso machine is not as easy as I thought it would be | 0 | 2 | a user |

The 50 posts in this run were all from 2026-10-15 (UTC), because `Latest` returns the newest matches first. The list includes deal and ad posts, so read it before you use it. Cost: $0.0075.
