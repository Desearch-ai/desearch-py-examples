# Python Desearch SDK Examples

This document provides examples of how to use the Desearch SDK to perform various types of searches. The Desearch SDK allows you to interact with multiple platforms and retrieve data using a unified interface.

## Setup

**Create and activate a virtual environment**:

```bash
python3 -m venv venv
source venv/bin/activate
```

**Install dependencies**:

```bash
pip3 install desearch-py
```

## Examples

### 1. Web Links Search

The Web Links Search allows you to search for web links using a specific query. Here's how you can perform a web links search:

```python
from desearch_py import Desearch

# Initialize the Desearch client with your API key
desearch = Desearch(api_key="your-api-key")

# Perform a web links search
result = desearch.web_links_search(
    prompt="Bittensor",
    tools=["web", "hackernews", "reddit", "wikipedia", "youtube", "arxiv"],
    model="NOVA"
)

# Print the search results
print(result)
```

### 2. AI Search

The AI Search provides a more comprehensive search experience by utilizing AI models to gather and summarize information from various sources:

```python
from desearch_py import Desearch

# Initialize the Desearch client with your API key
desearch = Desearch(api_key="your-api-key")

# Perform an AI search
result = desearch.ai_search(
    prompt="Bittensor",
    tools=["web", "hackernews", "reddit", "wikipedia", "youtube", "twitter", "arxiv"],
    model="NOVA",
    date_filter="PAST_24_HOURS",
    streaming=False,
    result_type="LINKS_WITH_SUMMARIES",
    system_message="You are a helpful assistant."
)

# Print the search results
print(result)
```

### 3. Basic Twitter Search

The Basic Twitter Search allows you to search for tweets based on specific criteria:

```python
from desearch_py import Desearch

# Initialize the Desearch client with your API key
desearch = Desearch(api_key="your-api-key")

# Perform a basic Twitter search
result = desearch.basic_twitter_search(
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
    count=10
)

# Print the search results
print(result)
```

### 4. Twitter Retweets and Replies

You can also retrieve retweets and replies for a specific tweet using its ID:

```python
from desearch_py import Desearch

# Initialize the Desearch client with your API key
desearch = Desearch(api_key="your-api-key")

# Perform a search for retweets of a specific tweet
result = desearch.twitter_retweets_post(post_id="123456789", count=10, query="Bittensor")

# Print the search results
print(result)

# Perform a search for replies to a specific tweet
result = desearch.twitter_replies_post(post_id="123456789", count=10, query="Bittensor")

# Print the search results
print(result)
```

These examples demonstrate how to use the Desearch SDK to perform various types of searches. You can customize the queries and parameters to suit your specific needs. Make sure to replace `"your-api-key"` with your actual API key to authenticate your requests.