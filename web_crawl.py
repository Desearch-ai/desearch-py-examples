# Import the Desearch library
from desearch_py import Desearch

# Initialize the Desearch client with your API key
# Replace 'your-api-key' with your actual API key
desearch = Desearch(api_key="your-api-key")

"""
This section of the code defines the configuration options for performing a Web crawl using the Desearch client.

Attributes:
    url (str): The url of the website to crawl
"""

# Perform an Web crawl using the Desearch client
result = desearch.web_crawl("https://docs.desearch.ai/docs/desearch-api")

# Print the web content
print(result)
