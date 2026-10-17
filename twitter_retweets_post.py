import asyncio

from desearch_py import Desearch

# Placeholder only. Use a key from the Desearch console. Do not commit a real key.
API_KEY = "your-api-key"


async def main():
    # desearch-py 1.2.1: x_post_retweeters(id, cursor) calls GET /twitter/post/retweeters
    # and returns the users who reposted the post plus a cursor for the next page.
    # There is no count or query argument. Replace the sample id with a public post id.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.x_post_retweeters(id="1276418907968925696")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
