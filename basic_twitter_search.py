import asyncio
import os

from desearch_py import Desearch

# Set DESEARCH_API_KEY in your environment to a key from the Desearch console. Do not commit a real key.
API_KEY = os.environ["DESEARCH_API_KEY"]


async def main():
    # desearch-py 1.2.1: x_search(query, sort, user, start_date, end_date, lang, verified,
    # blue_verified, is_quote, is_video, is_image, min_retweets, min_replies, min_likes, count)
    # calls GET /twitter. Pass the boolean filters as "true" / "false" strings: the client sends
    # them as query parameters, and Python True / False raise TypeError before the request is sent.
    # user, verified, is_quote and is_image take the same form. Stacking every filter on one
    # account can return an empty list, so this sample keeps a few.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.x_search(
            query="Bittensor",
            sort="Top",
            start_date="2026-01-01",
            end_date="2026-10-01",
            lang="en",
            blue_verified="true",
            is_video="true",
            min_retweets=1,
            min_replies=1,
            min_likes=1,
            count=10,
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
