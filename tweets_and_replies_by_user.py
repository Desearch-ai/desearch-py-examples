import asyncio

from desearch_py import Desearch

# Placeholder only. Use a key from the Desearch console. Do not commit a real key.
API_KEY = "your-api-key"


async def main():
    # desearch-py 1.2.1: x_user_replies(user, count, query) calls GET /twitter/replies.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.x_user_replies(user="elonmusk", query="Tesla", count=10)
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
