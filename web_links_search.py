import asyncio

from desearch_py import Desearch

# Placeholder only. Use a key from the Desearch console. Do not commit a real key.
API_KEY = "your-api-key"


async def main():
    # desearch-py 1.2.1: ai_web_links_search(prompt, tools, count)
    # posts to POST /desearch/ai/search/links/web. This example uses the web tool.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.ai_web_links_search(
            prompt="Bittensor",
            tools=["web"],
            count=10,
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
