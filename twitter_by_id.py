import asyncio

from desearch_py import Desearch

# Placeholder only. Use a key from the Desearch console. Do not commit a real key.
API_KEY = "your-api-key"


async def main():
    # desearch-py 1.2.1: x_post_by_id(id) calls GET /twitter/post. Replace the sample id with a public post id.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.x_post_by_id(id="1276418907968925696")
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
