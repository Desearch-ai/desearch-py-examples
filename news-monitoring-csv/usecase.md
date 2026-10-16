# How to use Desearch for news monitoring

Made by [Desearch](https://desearch.ai).

You follow three to five topics and want one spreadsheet of what is new since the last time you looked. Here is how I set that up with the Desearch API in about half an hour, with one short Python script.

## What you need
- A Desearch API key from console.desearch.ai.
- Python 3 and the `requests` package.

## Steps
1. **Pick your topics.** I used two: "open source llm release" and "ai chip export controls".
2. **Call web search for each topic.** `GET /web?query=<topic>` returned about 20 results, each with a title, link and snippet.
3. **Call X search for each topic.** `GET /twitter?query=<topic>&sort=Latest&start_date=<yesterday>&count=30` returned the latest posts Desearch had since that date, each with the text, a link and a post time.
4. **Turn both into rows.** One row per item: topic, kind (web or post), source domain, title, link, published date, snippet and the time the script first saw it.
5. **Keep a list of links you have already saved.** Before writing a row, the script normalizes the link and checks it against that list, so a second run only appends new items.
6. **Run it on a schedule.** A cron job every couple of hours keeps the CSV growing with new items only.

## What I saw
- Two topics, one web call and one X call each, took about 20 seconds end to end.
- The first run saved 88 unique items. A second run a minute later added 1 new item, which is what a seen-list is for: you only read what changed.
- X posts carry a post time, so you can sort them. Web results had no date in testing, so for web rows the useful time is "first seen".
- Web results for a broad topic mixed fresh news with evergreen guides. Adding "news" or the month to the topic helps.

## Tips
- Skip blank topics before calling the API.
- Dedupe by link, not by title: the same story can come back with different titles.
- Treat the CSV as "new items Desearch returned since the last run", not as every story on the topic.

Code, sample data and an offline mode are in the example folder (`news_monitor.py --from-raw samples/raw-sample.json`).
