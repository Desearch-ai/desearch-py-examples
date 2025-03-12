# Import the Datura library
from datura_py import Datura

# Initialize the Datura client with your API key
# Replace 'your-api-key' with your actual API key
datura = Datura(api_key="your-api-key")

"""
This section of the code defines the configuration options for performing a Tweets by URLs using the Datura client.

Attributes:
    urls (List[str]): The search query to be used in the Tweets by URLs.
"""

# Perform an Tweets by URLs using the Datura client
result = datura.twitter_by_urls(
    urls=["https://twitter.com/elonmusk/status/1613000000000000000"]
)

# Print the search results
print(result)
