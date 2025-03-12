# Import the Datura library
from datura_py import Datura

# Initialize the Datura client with your API key
# Replace 'your-api-key' with your actual API key
datura = Datura(api_key="your-api-key")

"""
This section of the code defines the configuration options for performing a Web links search using the Datura client.

Attributes:
    query (str): The search query to be used in the Web links search.
    
    num (int): The number of search results to return.
    
    start (int): The starting index for the search results.
"""

# Perform an Web links search using the Datura client
result = datura.basic_web_search(query="latest news on AI", num=10, start=0)

# Print the search results
print(result)


"""
Example Data Structure for News Articles

This dictionary represents the structure of a news article search result. It contains a list of articles with detailed information about each article.

Attributes:
    data (list): Contains a list of dictionaries, each representing a news article.
        - title (str): The title of the article.
        - snippet (str): A brief snippet or summary of the article content.
        - link (str): The URL to the full article.
        - date (str): The publication date or time of the article.
        - source (str): The source or publisher of the article.
        - author (str): The author of the article.
        - image (str): The URL to an image associated with the article.
        - favicon (str): The URL to the favicon of the source.
        - highlights (list): A list of highlighted phrases or sentences from the article.
"""
