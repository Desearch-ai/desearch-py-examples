import asyncio

from desearch_py import Desearch

# Placeholder only. Use a key from the Desearch console. Do not commit a real key.
API_KEY = "your-api-key"


async def main():
    # desearch-py 1.2.1 ai_search posts to POST /desearch/ai/search.
    # Tools are "web" and "twitter". streaming is not a parameter.
    # result_type is ONLY_LINKS or LINKS_WITH_FINAL_SUMMARY.
    # Pass date_filter=None when tools include "web": the client default is PAST_24_HOURS,
    # and that filter is not sent with the web tool.
    async with Desearch(api_key=API_KEY) as desearch:
        result = await desearch.ai_search(
            prompt="Bittensor",
            tools=[
                "web",
                "twitter",
            ],
            date_filter=None,
            result_type="LINKS_WITH_FINAL_SUMMARY",
            system_message="You are a helpful assistant.",
            count=10,
        )
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
