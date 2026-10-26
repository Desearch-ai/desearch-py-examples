import asyncio
import os

from desearch_py import Desearch

# Set DESEARCH_API_KEY in your environment to a key from the Desearch console. Do not commit a real key.
API_KEY = os.environ["DESEARCH_API_KEY"]


async def main():
    # desearch-py 1.2.1: x_post_replies(post_id, count, query)
    # calls GET /twitter/replies/post. Replace the sample post id with a public id.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.x_post_replies(
            post_id="1276418907968925696",
            count=10,
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
