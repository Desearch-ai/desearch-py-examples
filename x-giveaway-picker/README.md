# X Giveaway Picker
Made by Desearch, https://desearch.ai

A standard library Python scaffold for collecting public X giveaway entries, applying rules, drawing winners and exporting an entrants CSV. This scaffold has not yet been run live.

Run from the repository root:

```sh
python3 -m pip install -r x-giveaway-picker/requirements.txt
python3 x-giveaway-picker/app.py --port 8000
python3 x-giveaway-picker/app.py --cli https://x.com/demo_brand/status/900001234567890 --mode both --winners 2 --min-tags 1 --csv entrants.csv
python3 -m pytest -q x-giveaway-picker
```

Configure DESEARCH_API_KEY or DESEARCH_API_KEY_FILE. No default key files are read. Open the local address printed by the server and paste a post URL. CLI modes are repost, reply and both. Other options include --min-account-age-days, --min-followers, --count (1 to 100, default 50), and --draw-timestamp.

Inputs and rules are validated before any API call. The post lookup always runs first. An empty lookup stops immediately with "post not found or not public" and no collection calls.

The demo caps reposter collection at 25 pages, about 500 reposters. A remaining cursor at that cap produces "first 500 reposters only". A null or repeated cursor stops paging. A failed page is retried once, then partial results are kept with a notice. Replies use one call only, with a notice showing how many replies the API returned and the post's reported reply count. Coverage reports returned counts beside the post's reported counts. Reported cost headers are accumulated when present; missing headers contribute nothing.

Both modes require an account in both sets. Each account has one entry. The author is ineligible, including self replies. A qualifying reply must contain the required number of distinct tagged accounts, excluding the author's handle. Tags across separate replies are not combined. Missing age or follower data fails an enabled filter. CSV includes collected accounts, eligibility and exclusion reasons.

The displayed seed is the post id plus an ISO UTC draw timestamp. Drawing uses Python random.Random with that seed over eligible accounts sorted by user id. The same seed and entrant list reproduce the draw. Supply the original --draw-timestamp and identical collected data to reproduce a draw; API results can change. Fewer eligible accounts than requested winners returns the available eligible accounts. The web CSV link uses the stored collection without additional API calls, until the server restarts or its 100-result cache evicts it.

core.py contains network-free logic with an injectable fetch function and clock. app.py owns HTTP, credentials, CLI and the local server. Tests use fake responses only. samples/ contains made-up neutral fixtures.
