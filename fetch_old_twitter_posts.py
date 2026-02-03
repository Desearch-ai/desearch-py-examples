from datetime import datetime

from desearch_py import Desearch

desearch = Desearch("API_KEY")

TOTAL_TWEETS_TO_FETCH = 100


def parse_twitter_date(date_str: str) -> datetime:
    """Parse Twitter's date format: 'Tue Feb 03 09:38:44 +0000 2026'"""
    return datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")


def format_end_date(dt: datetime) -> str:
    """Format datetime to API end_date format: '2021-12-31_23:59:59_UTC'"""
    return dt.strftime("%Y-%m-%d_%H:%M:%S_UTC")


def fetch_tweets(query: str, total: int = TOTAL_TWEETS_TO_FETCH) -> list:
    """Fetch tweets with pagination using end_date cursor."""
    all_tweets = []
    end_date = None

    while len(all_tweets) < total:
        query_with_filter = query

        if end_date:
            query_with_filter += f" until:{end_date}"

        result = desearch.basic_twitter_search(
            query=query_with_filter,
            sort="Latest",
            count=20,
        )

        if not result:
            print("No more results")
            break

        print("\n--- Batch dates (UTC) ---")
        for tweet in result:
            dt = parse_twitter_date(tweet["created_at"])
            print(dt.strftime("%Y-%m-%d %H:%M:%S UTC"))

        all_tweets.extend(result)
        print(f"Fetched {len(result)} tweets, total: {len(all_tweets)}")

        # Find the oldest tweet in this batch
        oldest_tweet = min(result, key=lambda t: parse_twitter_date(t["created_at"]))
        oldest_date = parse_twitter_date(oldest_tweet["created_at"])

        # Use oldest date as next end_date
        end_date = format_end_date(oldest_date)
        print(f"Next end_date: {end_date}")

    return all_tweets


if __name__ == "__main__":
    tweets = fetch_tweets("bittensor")
    print(f"\nFetched {len(tweets)} tweets total")
