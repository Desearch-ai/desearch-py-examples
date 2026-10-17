import asyncio

from desearch_py import Desearch

# Placeholder only. Use a key from the Desearch console. Do not commit a real key.
API_KEY = "your-api-key"


async def main():
    # desearch-py 1.2.1: x_posts_by_urls(urls) calls GET /twitter/urls. Replace the sample URL with public post URLs.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.x_posts_by_urls(
            urls=["https://x.com/elonmusk/status/1276418907968925696"]
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
