# Import the Desearch library
from itertools import count
from desearch_py import Desearch

# Initialize the Desearch client with your API key
# Replace 'your-api-key' with your actual API key
desearch = Desearch(api_key="your-api-key")

"""
This section of the code defines the configuration options for the Deep research using the Desearch client.

Attributes:
    prompt (str): The search query to be used in the Deep research.

    tools (list of str): A list of tools available for conducting the search. These include:
        - "web Search"
        - "hackernews"
        - "reddit"
        - "wikipedia"
        - "youtube"
        - "twitter"
        - "arxiv"

    date_filter (str): The time range for filtering search results. Options include:
        - "PAST_24_HOURS"
        - "PAST_2_DAYS"
        - "PAST_WEEK"
        - "PAST_2_WEEKS"
        - "PAST_MONTH"
        - "PAST_2_MONTHS"
        - "PAST_YEAR"
        - "PAST_2_YEARS"

    streaming (bool): A flag indicating whether to stream the search results.
    
    system_message (str): The system message to be used for the Deep research.
"""

# Perform an Deep research using the Desearch client
result = desearch.deep_research(
    prompt="Bittensor",  # The search query
    tools=[
        "web",
        "hackernews",
        "reddit",
        "wikipedia",
        "youtube",
        "twitter",
        "arxiv",
    ],  # List of tools to use for the search
    date_filter="PAST_24_HOURS",  # Filter results from the past 24 hours
    streaming=False,  # Whether to stream results
    system_message="",
)

# Print the search results
print(result)
