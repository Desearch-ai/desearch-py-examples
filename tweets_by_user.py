import asyncio
import os

from desearch_py import Desearch

# Set DESEARCH_API_KEY in your environment to a key from the Desearch console. Do not commit a real key.
API_KEY = os.environ["DESEARCH_API_KEY"]


async def main():
    # desearch-py 1.2.1: x_posts_by_user(user, query, count) calls GET /twitter/post/user.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.x_posts_by_user(user="elonmusk", query="Tesla", count=10)
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
