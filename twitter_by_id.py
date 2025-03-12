# Import the Datura library
from datura_py import Datura

# Initialize the Datura client with your API key
# Replace 'your-api-key' with your actual API key
datura = Datura(api_key="your-api-key")

"""
This section of the code defines the configuration options for performing a Tweets by ID using the Datura client.

Attributes:
    id (str): The search query to be used in the Tweets by ID.
"""

# Perform an Tweets by ID using the Datura client
result = datura.twitter_by_id(id="123456789")

# Print the search results
print(result)
