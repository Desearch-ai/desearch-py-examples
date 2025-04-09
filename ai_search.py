# Import the Datura library
from datura_py import Datura

# Initialize the Datura client with your API key
# Replace 'your-api-key' with your actual API key
datura = Datura(api_key="your-api-key")

"""
This section of the code defines the configuration options for the AI search using the Datura client.

Attributes:
    prompt (str): The search query to be used in the AI search.

    tools (list of str): A list of tools available for conducting the search. These include:
        - "web Search"
        - "hackernews"
        - "reddit"
        - "wikipedia"
        - "youtube"
        - "twitter"
        - "arxiv"

    models (str): The models available for the search. Options include:
        - "NOVA"
        - "ORBIT"
        - "HORIZON"

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
    
    result_type (str): The type of search results to return. Options include:
        - "ONLY_LINKS"
        - "LINKS_WITH_SUMMARIES"
        - "LINKS_WITH_FINAL_SUMMARY"

    system_message (str): The system message to be used for the AI search.
"""

# Perform an AI search using the Datura client
result = datura.ai_search(
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
    model="NOVA",  # The model to use for the search
    date_filter="PAST_24_HOURS",  # Filter results from the past 24 hours
    streaming=False,  # Whether to stream results
    result_type="LINKS_WITH_SUMMARIES",
    system_message="You are a helpful assistant.",
)

# Print the search results
print(result)

"""
Example Result Structure for AI Search

This dictionary represents the structure of the result returned by the AI search using the Datura client. It contains search results from various platforms and a completion section with summarized information.

Attributes:
    youtube_search_results (dict): Contains YouTube search results.
        - organic_results (list): A list of dictionaries, each representing a YouTube video result.
            - title (str): The title of the video.
            - link (str): The URL to the video.
            - snippet (str): A brief snippet or description of the video.
            - summary_description (str): A summary description of the video.

    hacker_news_search_results (dict): Contains Hacker News search results.
        - organic_results (list): A list of dictionaries, each representing a Hacker News article.
            - title (str): The title of the article.
            - link (str): The URL to the article.
            - snippet (str): A brief snippet or description of the article.
            - summary_description (str): A summary description of the article.

    reddit_search_results (dict): Contains Reddit search results.
        - organic_results (list): A list of dictionaries, each representing a Reddit post.
            - title (str): The title of the post.
            - link (str): The URL to the post.
            - snippet (str): A brief snippet or description of the post.
            - summary_description (str): A summary description of the post.

    arxiv_search_results (dict): Contains arXiv search results.
        - organic_results (list): A list of dictionaries, each representing an arXiv paper.
            - title (str): The title of the paper.
            - link (str): The URL to the paper.
            - snippet (str): A brief snippet or description of the paper.
            - with_metadata (bool): Indicates if the result includes metadata.
            - summary_description (str): A summary description of the paper.

    wikipedia_search_results (dict): Contains Wikipedia search results.
        - organic_results (list): A list of dictionaries, each representing a Wikipedia page.
            - title (str): The title of the page.
            - link (str): The URL to the page.
            - snippet (str): A brief snippet or description of the page.
            - with_metadata (bool): Indicates if the result includes metadata.
            - summary_description (str): A summary description of the page.

    text_chunks (dict): Contains summaries from Twitter.
        - twitter_summary (list): A list of strings, each representing a summary from Twitter.

    search_completion_links (list): A list of URLs representing the completion of the search.

    completion_links (list): A list of URLs representing the completion of the search.

    completion (dict): Contains summarized information from the search.
        - key_posts (list): A list of dictionaries, each representing a key post.
            - text (str): The text of the post.
            - url (str): The URL to the post.
        - key_tweets (list): A list of dictionaries, each representing a key tweet.
            - text (str): The text of the tweet.
            - url (str): The URL to the tweet.
        - key_news (list): A list of dictionaries, each representing a key news article.
            - text (str): The text of the news article.
            - url (str): The URL to the news article.
        - key_sources (list): A list of dictionaries, each representing a key source.
            - text (str): The text of the source.
            - url (str): The URL to the source.
        - twitter_summary (str): A summary of Twitter results.
        - summary (str): A general summary of the search results.
        - reddit_summary (str): A summary of Reddit results.
        - hacker_news_summary (str): A summary of Hacker News results.
"""
