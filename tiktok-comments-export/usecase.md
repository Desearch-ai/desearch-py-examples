# How to use Desearch to export TikTok comments to a spreadsheet

Made by [Desearch](https://desearch.ai).

You have a few TikTok videos (your own, a partner's, or a topic you track) and you want to read what viewers said in a spreadsheet: sort by likes, spot questions, flag complaints. Here is how I did it with the Desearch API and one short Python script.

## What you need
- A Desearch API key from console.desearch.ai
- Python 3 and the `requests` package
- The ids of 2 to 5 TikTok videos (the long number at the end of a video link)

## Steps
1. **Call the comments endpoint.** `GET /desearch/tiktok/comments/{video_id}` with `count=10` returns a list of public comments for that video: text, likes, time and the commenter. Each call took about one second in my test.
2. **Get more than one page.** The response is a plain list. Sending `cursor=10` for page 2 and `cursor=20` for page 3 gave new comments each time in my test. This worked in testing; it is not described in the docs, so dedupe your rows anyway.
3. **Dedupe.** The comments did not include an id in my test, so I made a short key from the commenter id, the time and the text. Duplicates across pages drop out.
4. **Keep people out of the file.** Commenters become `Viewer 1`, `Viewer 2` and so on, `@mentions` become `[viewer]`, and video links are rebuilt from the video id.
5. **Tag and sort.** A tiny keyword rule marks each comment as question, complaint or praise. The summary lists the top 10 comments by likes and how many comments each page added.
6. **Rebuild offline.** The script saves the raw responses, so `--from-raw` rebuilds the CSV without new calls.

## Run it
```bash
export DESEARCH_API_KEY=...
python tiktok_comments.py --videos <video id or link> <video id or link> --count 10 --pages 3
```

## What to expect
- In my run, 2 videos at 10 comments for 3 pages each gave a CSV of a few dozen unique comments in under 10 seconds.
- Comments are billed per comment returned, so start with a low count and check the cost on your first call. A video id with no comments came back as an empty list and was not billed in my test.
- The order of comments within a page is not sorted by likes or by time, so sort in your spreadsheet.
- You get the public comments Desearch returned for those pages, not every comment on a video. Reply threads were empty in my test.
