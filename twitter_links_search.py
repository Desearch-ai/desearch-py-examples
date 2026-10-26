import asyncio
import os

from desearch_py import Desearch

# Set DESEARCH_API_KEY in your environment to a key from the Desearch console. Do not commit a real key.
API_KEY = os.environ["DESEARCH_API_KEY"]


async def main():
    # desearch-py 1.2.1: ai_x_links_search(prompt, count)
    # posts to POST /desearch/ai/search/links/twitter.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.ai_x_links_search(prompt="Bittensor", count=10)
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
