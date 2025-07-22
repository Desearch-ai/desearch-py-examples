# Import the Desearch library
from desearch_py import Desearch

# Initialize the Desearch client with your API key
# Replace 'your-api-key' with your actual API key
desearch = Desearch(api_key="your-api-key")

"""
This section of the code defines the configuration options for the Twitter post search using the Desearch client.

Attributes:
    prompt (str): The search query to be used in the Twitter post search.  

    count (int): The maximum number of search results to return.
"""

# Perform an Twitter post search using the Desearch client
result = desearch.twitter_links_search(prompt="Bittensor", count=10)

# Print the search results
print(result)

"""
Example Result Structure for Miner Tweets

This dictionary represents the structure of the result returned by a miner tweets search. It contains detailed information about tweets and their associated user data.

Attributes:
    miner_tweets (list): Contains a list of tweets with detailed information.
        - user (dict): Contains information about the user who posted the tweet.
            - id (str): The unique identifier for the user.
            - url (str): The URL to the user's Twitter profile.
            - name (str): The name of the user.
            - username (str): The username of the user.
            - created_at (str): The date and time when the user account was created.
            - description (str): The description of the user.
            - favourites_count (int): The number of tweets the user has liked.
            - followers_count (int): The number of followers the user has.
            - listed_count (int): The number of public lists the user is a member of.
            - media_count (int): The number of media items the user has uploaded.
            - profile_image_url (str): The URL to the user's profile image.
            - statuses_count (int): The number of tweets (including retweets) posted by the user.
            - verified (bool): Indicates if the user is verified.

        - id (str): The unique identifier for the tweet.
        - text (str): The text content of the tweet.
        - reply_count (int): The number of replies to the tweet.
        - retweet_count (int): The number of times the tweet has been retweeted.
        - like_count (int): The number of likes the tweet has received.
        - view_count (int): The number of views the tweet has received.
        - quote_count (int): The number of times the tweet has been quoted.
        - impression_count (int): The number of times the tweet has been seen.
        - bookmark_count (int): The number of times the tweet has been bookmarked.
        - url (str): The URL to the tweet.
        - created_at (str): The date and time when the tweet was created.
        - media (list): A list of media items associated with the tweet.
        - is_quote_tweet (bool): Indicates if the tweet is a quote tweet.
        - is_retweet (bool): Indicates if the tweet is a retweet.
        - entities (dict): Contains metadata and entities associated with the tweet.
        - summary_description (str): A summary description of the tweet.
"""
