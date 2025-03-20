# Import the Datura library
from datura_py import Datura

# Initialize the Datura client with your API key
# Replace 'your-api-key' with your actual API key
datura = Datura(api_key="your-api-key")

"""
This section of the code defines the configuration options for performing a Twitter search using the Datura client.

Attributes:
    query (str): The search query to be used in the Twitter search.
    
    sort (str): The sorting order of the search results. Options might include "Top", "Latest", etc.
    
    user (str): The Twitter username to filter the search results by.
    
    start_date (str): The start date for the search results in the format "YYYY-MM-DD".
    
    end_date (str): The end date for the search results in the format "YYYY-MM-DD".
    
    lang (str): The language code to filter the search results by.
    
    verified (bool): A flag indicating whether to filter for verified users.
    
    blue_verified (bool): A flag indicating whether to filter for users with a blue verification badge.
    
    is_quote (bool): A flag indicating whether to include quoted tweets in the search results.
    
    is_video (bool): A flag indicating whether to include tweets with videos in the search results.
    
    is_image (bool): A flag indicating whether to include tweets with images in the search results.
    
    min_retweets (int): The minimum number of retweets a tweet must have to be included in the search results.
    
    min_replies (int): The minimum number of replies a tweet must have to be included in the search results.
    
    min_likes (int): The minimum number of likes a tweet must have to be included in the search results.
    
    count (int): The maximum number of search results to return.
"""

# Perform an Web links search using the Datura client
result = datura.basic_twitter_search(
    query="Whats going on with Bittensor",
    sort="Top",
    user="elonmusk",
    start_date="2024-12-01",
    end_date="2025-02-25",
    lang="en",
    verified=True,
    blue_verified=True,
    is_quote=True,
    is_video=True,
    is_image=True,
    min_retweets=1,
    min_replies=1,
    min_likes=1,
    count=10,
)

# Print the search results
print(result)


"""
Example List Structure for Tweets

This list contains dictionaries representing individual tweets and their associated user data. Each dictionary provides detailed information about a tweet and the user who posted it.

Attributes:
    user (dict): Contains information about the user who posted the tweet.
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

    id (str): The unique identifier for the tweet.
    text (str): The text content of the tweet.
    reply_count (int): The number of replies to the tweet.
    retweet_count (int): The number of times the tweet has been retweeted.
    like_count (int): The number of likes the tweet has received.
    view_count (int): The number of views the tweet has received.
    quote_count (int): The number of times the tweet has been quoted.
    impression_count (int): The number of times the tweet has been seen.
    bookmark_count (int): The number of times the tweet has been bookmarked.
    url (str): The URL to the tweet.
    created_at (str): The date and time when the tweet was created.
    media (list): A list of media items associated with the tweet.
    is_quote_tweet (bool): Indicates if the tweet is a quote tweet.
    is_retweet (bool): Indicates if the tweet is a retweet.
"""
