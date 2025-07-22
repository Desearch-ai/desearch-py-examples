# Import the Desearch library
from desearch_py import Desearch

# Initialize the Desearch client with your API key
# Replace 'your-api-key' with your actual API key
desearch = Desearch(api_key="your-api-key")

"""
This section of the code defines the configuration options for the Web links search using the Desearch client.

Attributes:
    prompt (str): The search query to be used in the Web links search.

    tools (list of str): A list of tools available for conducting the search. These include:
        - "web Search"
        - "hackernews"
        - "reddit"
        - "wikipedia"
        - "youtube"
        - "arxiv"

    count (int): The maximum number of search results to return.
"""

# Perform an Web links search using the Desearch client
result = desearch.web_links_search(
    prompt="Bittensor",
    tools=[
        "web",
        "hackernews",
        "reddit",
        "wikipedia",
        "youtube",
        "arxiv",
    ],
    count=10,
)

# Print the search results
print(result)


"""
Example Result Structure for AI Search

This dictionary represents the structure of the result returned by the AI search using the Desearch client. It contains search results from various platforms, including YouTube, Hacker News, Reddit, arXiv, Wikipedia, and general search results.

Attributes:
    youtube_search_results (list): Contains YouTube search results.
        - title (str): The title of the video.
        - link (str): The URL to the video.
        - snippet (str): A brief snippet or description of the video.
        - summary_description (str): A summary description of the video.

    hacker_news_search_results (dict): Contains Hacker News search results.
        - organic_results (list): A list of dictionaries, each representing a Hacker News article.
            - position (int): The position of the article in the search results.
            - title (str): The title of the article.
            - link (str): The URL to the article.
            - redirect_link (str): A redirect URL to the article.
            - displayed_link (str): The displayed URL of the article.
            - favicon (str): The URL to the favicon of the source.
            - date (str): The date of the article.
            - snippet (str): A brief snippet or description of the article.
            - snippet_highlighted_words (list): Words in the snippet that are highlighted.
            - source (str): The source of the article.

    reddit_search_results (dict): Contains Reddit search results.
        - organic_results (list): A list of dictionaries, each representing a Reddit post.
            - position (int): The position of the post in the search results.
            - title (str): The title of the post.
            - link (str): The URL to the post.
            - redirect_link (str): A redirect URL to the post.
            - displayed_link (str): The displayed URL of the post.
            - favicon (str): The URL to the favicon of the source.
            - snippet (str): A brief snippet or description of the post.
            - snippet_highlighted_words (list): Words in the snippet that are highlighted.
            - source (str): The source of the post.

    arxiv_search_results (list): Contains arXiv search results.
        - title (str): The title of the paper.
        - link (str): The URL to the paper.
        - snippet (str): A brief snippet or description of the paper.
        - with_metadata (bool): Indicates if the result includes metadata.
        - summary_description (str): A summary description of the paper.

    wikipedia_search_results (list): Contains Wikipedia search results.
        - title (str): The title of the page.
        - link (str): The URL to the page.
        - snippet (str): A brief snippet or description of the page.
        - with_metadata (bool): Indicates if the result includes metadata.
        - summary_description (str): A summary description of the page.

    search_results (dict): Contains general search results.
        - organic_results (list): A list of dictionaries, each representing a search result.
            - position (int): The position of the result in the search results.
            - title (str): The title of the result.
            - link (str): The URL to the result.
            - redirect_link (str): A redirect URL to the result.
            - displayed_link (str): The displayed URL of the result.
            - favicon (str): The URL to the favicon of the source.
            - snippet (str): A brief snippet or description of the result.
            - snippet_highlighted_words (list): Words in the snippet that are highlighted.
            - sitelinks (dict): Contains inline sitelinks.
                - inline (list): A list of dictionaries, each representing a sitelink.
                    - title (str): The title of the sitelink.
                    - link (str): The URL to the sitelink.
            - source (str): The source of the result.
"""
