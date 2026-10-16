# How to use Desearch to compare X trends across countries

Made by [Desearch](https://desearch.ai).

If you track social conversation for more than one market, the first question each morning is simple: what is trending where, and what is trending everywhere? This guide builds a small Python dashboard that answers it with the Desearch API. A full snapshot of 5 places cost under 3 cents.

## What you get

- A static HTML page with the top 30 trends for each place side by side, shared trends highlighted.
- A list of trends that appear in two or more places.
- A few of the latest posts for the top shared trends, with authors shown as Account A, Account B and so on.
- CSV and JSON files you can open in a spreadsheet or notebook.
- On a second run, which trends are new and which changed rank.

## Steps

1. **Get a key.** Sign up at console.desearch.ai, create an API key and export it as `DESEARCH_API_KEY`.
2. **Pick places.** Trends are requested by WOEID (a location ID). I used Worldwide (1), United States (23424977), United Kingdom (23424975), India (23424848) and Brazil (23424768).
3. **Pull trends.** One call per place:
   ```
   GET /twitter/trends?woeid=23424977&count=30
   ```
   `count` takes 30 to 100. Each call returned 30 trends in testing, and the response names the location it answered for. Compare that name with what you asked for before you label the column.
4. **Find shared trends.** Match names ignoring case, spaces and a leading `#`. In my run, the same topic showed up as a hashtag in one country and as a plain word in four others, so this step matters.
5. **Add context.** For the top shared trends, fetch the latest posts:
   ```
   GET /twitter?query=<trend>&sort=Latest&count=10
   ```
   The 10 posts I got for each trend were all from the previous 15 seconds, so this is a quick look at what people are saying right now, not a summary of the day.
6. **Build the page.** Write a CSV per snapshot and an HTML table. Run again later with the previous snapshot to mark new trends.

## What to expect

- Trends shift fast. A second snapshot 45 seconds after the first had 1 new trend and 19 of 150 rows at a different rank, so always stamp each snapshot with its time.
- The trend list gives names and ranks. Volume per trend was empty in my run, so rank is the signal.
- Two related trends (for example a fan chant and an event hashtag) can return mostly the same sample posts. Dedupe posts by ID if you show several trends.
- Validate input before you call: a search for a phrase nobody uses still costs a normal call.

## Cost (measured 2026-10-16 by response headers)

- 30 trends for one place: $0.0045.
- 10 latest posts: $0.0015.
- One full snapshot (5 places plus 3 post samples): $0.027.

## Ideas to extend it

- Schedule it morning and evening and keep the CSVs to see which trends last.
- Add more places, or raise `count` to 50.
- Feed the shared trends into a short daily note for your team.
