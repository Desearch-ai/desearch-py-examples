# How to use Desearch to export TikTok videos to a spreadsheet

Made by [Desearch](https://desearch.ai).

I am an analyst. I wanted public TikTok data for one topic in a spreadsheet (views, likes, comments, shares, caption, post time) without building or babysitting a scraper. Here is what I did with the Desearch API, and what came back.

## What you need
- A Desearch API key from console.desearch.ai
- Python 3 and the `requests` package

## Steps
1. **Pick a keyword and a hashtag.** I used the keyword "skincare routine" and the hashtag skincare.
2. **Search by keyword.** `POST /desearch/tiktok/search` with a JSON body like `{"query": "skincare routine", "count": 15}`. Each call took about 5 seconds and returned the 15 videos I asked for.
3. **Pull the hashtag feed.** `GET /desearch/tiktok/hashtag/skincare?count=15`. Same shape of result, so both lists go into one table.
4. **Get a second page.** The results are a plain list without a cursor field. Passing the running offset as `cursor` ("15" for page 2) worked in testing: the second keyword page had no repeats and the second hashtag page repeated one video.
5. **Flatten and dedupe.** One row per video id, with a `source` column (search, hashtag or both). Creators become "Creator 1", "Creator 2"; handles inside captions are masked.
6. **Summarise.** Median views, the top 10 by engagement rate ((likes + comments + shares) / views) and how many videos were posted in each UTC hour.

## What I got
- 60 rows returned, 59 unique videos, and in this run the keyword and hashtag sets did not overlap at all, so running both really widens the sample.
- Every row had views, likes, comments, shares and saves filled.
- The hashtag feed is not ordered by date: it mixed videos from several years. Filter on the post time column if you only want recent videos.
- A made-up hashtag came back as "not found" rather than an empty list, so check the status code in your script.

## Tips
- Start small (`count` 15, 1 page) and read the cost header on the first response before you scale up.
- Keep the raw JSON. The script rebuilds the CSV from it with `--from-raw`, so you can change columns without paying again.
- The tool exports public TikToks that Desearch returned for your query; it is a sample, not a full census of a hashtag.
