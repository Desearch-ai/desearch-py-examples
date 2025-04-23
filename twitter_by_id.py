# Import the Desearch library
from desearch_py import Desearch

# Initialize the Desearch client with your API key
# Replace 'your-api-key' with your actual API key
desearch = Desearch(api_key="your-api-key")

"""
This section of the code defines the configuration options for performing a Tweets by ID using the Desearch client.

Attributes:
    id (str): The search query to be used in the Tweets by ID.
"""

# Perform an Tweets by ID using the Desearch client
result = desearch.twitter_by_id(id="123456789")

# Print the search results
print(result)

"""
Example Data Structure for Basic Twitter Search Response

This class represents the structure of a basic Twitter search response. It contains detailed information about a tweet and its associated user.

Attributes:
    user (Optional[TwitterScraperUser]): Information about the user who posted the tweet.
        - id (str): The unique identifier for the user.
        - url (str): The URL to the user's profile.
        - name (str): The name of the user.
        - username (str): The username of the user.
        - created_at (str): The date and time when the user's account was created.
        - description (str): A brief description of the user.
        - favourites_count (int): The number of tweets the user has liked.
        - followers_count (int): The number of followers the user has.
        - listed_count (int): The number of public lists the user is a member of.
        - media_count (int): The number of media items the user has posted.
        - profile_image_url (str): The URL to the user's profile image.
        - statuses_count (int): The number of tweets (including retweets) posted by the user.
        - verified (bool): Indicates if the user is verified.

    id (Optional[str]): The unique identifier for the tweet.
    text (Optional[str]): The text content of the tweet.
    reply_count (Optional[int]): The number of replies to the tweet.
    retweet_count (Optional[int]): The number of times the tweet has been retweeted.
    like_count (Optional[int]): The number of likes the tweet has received.
    view_count (Optional[int]): The number of times the tweet has been viewed.
    quote_count (Optional[int]): The number of times the tweet has been quoted.
    impression_count (Optional[int]): The number of times the tweet has been seen.
    bookmark_count (Optional[int]): The number of times the tweet has been bookmarked.
    url (Optional[str]): The URL to the tweet.
    created_at (Optional[str]): The date and time when the tweet was created.
    media (Optional[List[TwitterScraperMedia]]): A list of media items associated with the tweet.

    is_quote_tweet (Optional[bool]): Indicates if the tweet is a quote tweet.
    is_retweet (Optional[bool]): Indicates if the tweet is a retweet.
"""
