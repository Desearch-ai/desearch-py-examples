import asyncio

from desearch_py import Desearch

# Placeholder only. Use a key from the Desearch console. Do not commit a real key.
API_KEY = "your-api-key"


async def main():
    # desearch-py 1.2.1: web_search(query, start) calls GET /web.
    # start is how many results to skip. There is no num argument.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.web_search(query="latest news on AI", start=0)
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
