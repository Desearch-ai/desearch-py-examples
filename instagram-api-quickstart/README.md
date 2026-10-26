# Instagram API Quickstart
Made by Desearch, https://desearch.ai

Read public profiles, posts, comments and hashtag media from Instagram with code and one Desearch API key. You do not create an Instagram app; you call the Desearch API with your Desearch key. No Instagram app review is needed on your side. The CLI uses only the standard library.

## Get the code

```sh
git clone https://github.com/Desearch-ai/desearch-py-examples
cd desearch-py-examples/instagram-api-quickstart
```

## Get a key

Sign up at https://console.desearch.ai and create an API key.

```sh
export DESEARCH_API_KEY=...
```

Alternatively, set DESEARCH_API_KEY_FILE to a key file path or pass `--key-file`.

## Try one call with curl

```sh
curl -s https://api.desearch.ai/desearch/instagram/profile/natgeo -H "Authorization: $DESEARCH_API_KEY" -H "User-Agent: my-app/1.0" -D -
```

The cost is in the `X-Desearch-Cost-Usd` response header. Always set your own `User-Agent` header.

## Python example

Fetch profile posts using standard library urllib, print each post's `shortcode` and `createTime`, and read the next cursor from the response header:

```python
import json
import os
from urllib.request import Request, urlopen

request = Request(
    "https://api.desearch.ai/desearch/instagram/profile/natgeo/posts?count=3",
    headers={
        "Authorization": os.environ["DESEARCH_API_KEY"],
        "User-Agent": "my-app/1.0",
    },
)
with urlopen(request, timeout=60) as response:
    posts = json.load(response)
    cursor = response.headers.get("x-desearch-next-cursor")
for post in posts:
    print(post["shortcode"], post["createTime"])
print("x-desearch-next-cursor:", cursor)
```

## The CLI

| Command | Route |
| --- | --- |
| `profile USERNAME` | `GET /desearch/instagram/profile/{username}` |
| `posts USERNAME [--count N --pages P --cursor C]` | `GET /desearch/instagram/profile/{username}/posts` |
| `media SHORTCODE_OR_URL` | `GET /desearch/instagram/media/{id}` |
| `comments SHORTCODE_OR_URL [--count N --pages P --cursor C --with-authors]` | `GET /desearch/instagram/comments/{shortcode}` |
| `hashtag TAG [--count N --pages P --cursor C]` | `GET /desearch/instagram/hashtag/{tag}` |
| `search QUERY [--count N]` | `POST /desearch/instagram/search` |

`--key-file`, `--log-dir` (saves each call with the key redacted) and `--raw` (keeps response fields) go before the command. `--max-cost` works before or after the command (default 0.10 USD; stops paging before a page whose estimate would go over).

```sh
python3 ig.py --max-cost 0.05 profile natgeo
python3 ig.py profile natgeo --max-cost 0.05
```

```sh
python3 ig.py profile natgeo
python3 ig.py posts natgeo --count 3 --pages 2
python3 ig.py search "national geographic" --count 3
```

The CLI prints indented JSON to stdout, including errors. An excerpt from `samples/posts-natgeo.json`:

```json
{
  "command": "posts",
  "target": "natgeo",
  "count_requested": 3,
  "pages_fetched": 1,
  "returned": 3,
  "next_cursor": "<opaque cursor from the x-desearch-next-cursor header>",
  "cost_usd": 0.00621,
  "calls": 1
}
```

Each call also prints a cost line to stderr in this format:

```text
[time] 200 /desearch/instagram/profile/natgeo/posts 15.488s items=3 cost=$0.006210 next_cursor=yes
```

## Paging

The next page cursor comes only in the `x-desearch-next-cursor` response header. Send it back unchanged as `cursor` on the same route and target. Per the API docs, it is valid for 24 hours. A made-up cursor or one from another route returned 422 and was not charged in our tests.

Search has one page. Sending a cursor to search returned 422 with `cursor is not supported on instagram search` and was not charged.

## What it cost in our runs (2026-10-26)

| Request | Measured cost |
| --- | --- |
| Profile | $0.00207 per call |
| Media | $0.00207 per call |
| Posts, hashtag, comments, search | $0.00207 per returned item |
| `count=3` | $0.00621 |
| Comments with `count=5` | $0.01035 |
| 422 for a bad cursor | $0 |

Prices can change: https://desearch.ai/pricing.

## Response notes

What we saw on 2026-10-26:

- `createTime` is a Unix integer in seconds on profile posts and media lookup, but an ISO 8601 string on hashtag media and comments. The CLI adds `created_at` in ISO UTC and keeps `created_raw`.
- The first profile posts page held 3 posts older than the posts on page 2, likely pinned posts. There is no pinned flag. Sort by `created_at` if you need newest first.
- For like and comment counts, use the profile posts or hashtag routes.
- Use the post shortcode as your key across routes.
- Comments take the shortcode from the post URL.
- Search returns profiles with type `"profile"`.
- Successful calls took roughly 2 to 22 seconds each in our runs on 2026-10-26: media and comments about 2 to 4 seconds; profile, posts, hashtag and search about 9 to 22 seconds. Use a timeout of 60 seconds or more.

## Privacy

The CLI leaves commenter identities out of comments output unless you pass `--with-authors`. Use public brand accounts in examples.

## Tests

Run from this folder:

```sh
python3 -m pip install -r requirements.txt
python3 -m pytest -q
```

Tests run offline with no key needed.

## Files

- `ig.py`: CLI, requests, billing logs and paging.
- `igcore.py`: input validation and response normalization.
- `test_ig.py`: offline CLI tests.
- `test_igcore.py`: validation and normalization tests.
- `requirements.txt`: test dependency.
- `samples/profile-natgeo.json`: measured public profile output.
- `samples/posts-natgeo.json`: measured public posts output with a placeholder cursor.
- `samples/search-national-geographic.json`: measured search output filtered to usernames starting with `natgeo`.
