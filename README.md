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
pip3 install desearch-py==1.2.1
```

## Examples

### 1. Web Links Search

The Web Links Search allows you to search for web links using a specific query. Here's how you can perform a web links search:

```python
import asyncio
from desearch_py import Desearch

async def main():
    async with Desearch(api_key="your-api-key") as desearch:
        result = await desearch.ai_web_links_search(
            prompt="Bittensor",
            tools=["web"],
            count=10,
        )
        print(result)

asyncio.run(main())
```

### 2. AI Search

The AI Search provides a more comprehensive search experience by utilizing AI models to gather and summarize information from various sources:

```python
import asyncio
from desearch_py import Desearch

async def main():
    async with Desearch(api_key="your-api-key") as desearch:
        result = await desearch.ai_search(
            prompt="Bittensor",
            tools=[
                "web",
                "twitter",
            ],
            date_filter=None,
            result_type="LINKS_WITH_FINAL_SUMMARY",
            system_message="You are a helpful assistant.",
            count=10,
        )
        print(result)

asyncio.run(main())
```

### 3. Basic Twitter Search

The Basic Twitter Search allows you to search for tweets based on specific criteria:

```python
import asyncio
from desearch_py import Desearch

async def main():
    async with Desearch(api_key="your-api-key") as desearch:
        # desearch-py 1.2.1: x_search calls GET /twitter.
        # Pass boolean filters as "true" / "false" strings. See basic_twitter_search.py.
        result = await desearch.x_search(
            query="Bittensor",
            sort="Top",
            start_date="2026-01-01",
            end_date="2026-10-01",
            lang="en",
            blue_verified="true",
            is_video="true",
            min_retweets=1,
            min_replies=1,
            min_likes=1,
            count=10,
        )
        print(result)

asyncio.run(main())
```

### 4. Twitter Retweets and Replies

You can also retrieve retweets and replies for a specific tweet using its ID:

```python
import asyncio
from desearch_py import Desearch

async def main():
    async with Desearch(api_key="your-api-key") as desearch:
        # Users who reposted a post. desearch-py 1.2.1: x_post_retweeters(id, cursor).
        result = await desearch.x_post_retweeters(id="123456789")
        print(result)

        # Replies to a post. See twitter_replies_post.py.
        result = await desearch.x_post_replies(post_id="1276418907968925696", count=10)
        print(result)

asyncio.run(main())
```

`x_post_replies` returns up to `count` replies; older posts may return fewer.

These examples demonstrate how to use the Desearch SDK to perform various types of searches. You can customize the queries and parameters to suit your specific needs. Make sure to replace `"your-api-key"` with your actual API key to authenticate your requests.

## Example apps

- [Morning Topic Brief](morning-topic-brief/README.md): Python CLI that builds a morning brief on chosen topics with the Desearch API.
- [Token Narrative Pulse](token-narrative-pulse/README.md): Python CLI that tracks X narrative and mention volume for crypto tokens with the Desearch API.
- [Comment Voice-of-Customer Report](comment-voc-report/README.md): Python CLI that pulls public comments from a brand's recent Instagram and TikTok posts and sorts them into questions, complaints, requests, praise and other.
- [Ad Library Angle Log](ad-library-angle-log/README.md): Python CLI that logs public Ad Library angles for a store and diffs them over time with the Desearch API.
- [City Trends Pulse](city-trends-pulse/README.md): Python CLI that compares X trends across cities and countries, pulls the top posts per trend and checks their relevance, freshness and language with the Desearch API.
- [TikTok Trend Board](tiktok-trend-board/README.md): Python CLI that builds a daily board of TikTok trending posts and hashtags per region, with hashtag drill-downs and top-post comments, with the Desearch API.
- [Instagram Creator Shortlist](instagram-creator-shortlist/README.md): Python CLI that turns a niche keyword into a ranked shortlist of Instagram creators by follower tier, engagement rate and posting cadence with the Desearch API.
- [YouTube Angle Finder](youtube-angle-finder/README.md): Python CLI that finds YouTube videos on a niche and writes an angles and gaps brief with the Desearch API.
- [AI Answer Check](ai-answer-check/README.md): Python CLI that checks whether an AI answer names your brand on buyer questions with the Desearch API.
- [Agent Search Toolbelt](agent-search-toolbelt/README.md): Python research agent that answers a question with four Desearch MCP tools and writes a run log of each call.
- [Arxiv Chatter Digest](arxiv-chatter-digest/README.md): Python CLI that digests recent arXiv papers on a topic and the public X posts that named them with the Desearch API.
- [Complaint Radar](complaint-radar/README.md): Python CLI that sorts recent public X complaint posts about a brand into themes with the Desearch API.
- [Forum Intent Board](forum-intent-board/README.md): Python CLI that lists public Hacker News and Reddit threads asking for a tool with the Desearch API.
- [Hashtag Shortlist](hashtag-shortlist/README.md): Python CLI that ranks candidate TikTok and Instagram hashtags for a niche by median likes, freshness and creator spread with the Desearch API.
- [Hiring Signal Radar](hiring-signal-radar/README.md): Python CLI that finds companies hiring for a role from public posts and job pages with the Desearch API.
- [Holiday Promo Watch](holiday-promo-watch/README.md): Python CLI that snapshots Black Friday promo wording on brand sites and social posts with the Desearch API.
- [Reply Ledger](reply-ledger/README.md): Python CLI that turns a public X account's recent posts and replies into a reply ledger with the Desearch API.
- [Investor Topic Tracker](investor-topic-tracker/README.md): Python CLI that builds a reading list of public investor posts on a topic with the Desearch API.
- [Listicle Gap Finder](listicle-gap-finder/README.md): Python CLI that finds roundup pages naming competitors but not your brand with the Desearch API.
- [Posting Time Check](posting-time-check/README.md): Python CLI that scores posting time by weekday and hour for TikTok, Instagram and Facebook accounts with the Desearch API.
- [Repo Buzz Tracker](repo-buzz-tracker/README.md): Python CLI that tracks public X posts and web pages mentioning a GitHub repo with the Desearch API.
- [RAG Corpus Builder](rag-corpus-builder/README.md): Python CLI that builds a starter corpus from ranked web pages on a topic with the Desearch API.
- [Tweet Scraper to CSV](tweet-scraper-csv/README.md): Python CLI that writes public X posts for a query to a clean CSV with the Desearch API.
- [Page to Markdown](page-to-markdown-api/README.md): Python CLI that turns a list of URLs into clean Markdown files with the Desearch API.
- [SERP API Rank Checker](serp-api-rank-checker/README.md): Python CLI that reports the best rank a domain got for each keyword in the web results Desearch returned with the Desearch API.
- [Launch Quote Ledger](launch-quote-ledger/README.md): Python CLI that collects quote posts of a product launch on X and notes disclosure wording with the Desearch API.
- [Social Listening Report](social-listening-report/README.md): Python CLI that pulls recent public X posts and web pages for a brand into a listening sheet with the Desearch API.
- [Market Research Brief](market-research-brief/README.md): Python CLI that drafts a short market brief from web pages and recent posts with the Desearch API.
- [X Trends Dashboard](x-trends-dashboard/README.md): Python CLI that compares X trends across places and writes a static HTML dashboard with the Desearch API.
- [Trending Hashtags Finder](trending-hashtags-finder/README.md): Python CLI that pulls X trend lists by location, keeps hashtags only, merges them across countries, checks activity on the latest posts and writes a use, cooling or skip verdict with the Desearch API.
- [TikTok Scraper to CSV](tiktok-scraper-csv/README.md): export public TikToks for a keyword and hashtag to one clean CSV.
- [Brand Mentions Finder](brand-mentions-finder/README.md): Saved prompt and Python CLI that lists third-party web pages and public X posts about a brand with the Desearch API.
- [X Keyword Monitor](x-keyword-monitor/README.md): Saved prompt and Python CLI that lists new public X posts for a few keywords since the last check with the Desearch API.
- [Podcast Guest Shortlist](podcast-guest-shortlist/README.md): Saved prompt and Python CLI that builds a podcast guest shortlist from public X posts and web pages with the Desearch API.
- [TikTok Comments Export](tiktok-comments-export/README.md): export public comments from TikTok videos to one clean CSV.
- [Tweet Search Web App](tweet-search-web-app/): one-page web app to search X posts with filters and export CSV.
- [Reddit Search (MCP)](reddit-search-mcp/README.md): Saved prompt and Python CLI that searches Reddit threads on a topic through the Desearch MCP ai-search tool and prints links, a short summary and the cost.
- [arXiv Paper Search to CSV](arxiv-paper-search-csv/README.md): search arXiv papers by topic and export one clean, deduplicated CSV.
- [X User Lookup App](x-user-lookup-app/): look up an X account's recent posts in a small web app or CLI and export CSV.
- [Web Search API Quickstart](web-search-api-quickstart/): a tiny search endpoint and page on top of the Desearch web search API, with curl, Python and JS snippets.
- [Find X Influencers (MCP)](find-x-influencers-mcp/README.md): Saved prompt and Python CLI that finds active X voices on a topic through the Desearch MCP x-search tool, ranked by posts and likes with follower counts.
- [News Monitoring to CSV](news-monitoring-csv/README.md): track topics across the web and X and append only new items to one CSV.
- [Launch Video Swipe File](launch-video-swipe-file/): collect product launch video posts from X into a CSV and Markdown swipe file.
- [Directory Finder](directory-finder/README.md): type a category and get the directories that accept submissions, with a CSV and a shortlist.
- [Hacker News Search App](hacker-news-search-app/): search Hacker News discussions with Desearch AI search (hackernews tool), export JSON or CSV.
- [Instagram Engagement Rate Calculator](instagram-engagement-rate-calculator/README.md): Python CLI that computes the engagement rate of a public Instagram account from its latest posts, with the formula shown and a split by format (image, carousel, video/reel), using the Desearch API.
- [Content Ideas Finder (MCP)](content-ideas-finder-mcp/README.md): Saved prompt and Python CLI that turns questions from Reddit, Hacker News and X into a content plan with a source link per idea, through the Desearch MCP ai-search and x-search tools.
- [AI Fact Checker](ai-fact-checker/): paste one claim and get web sources that back it or push back on it, a summary that keeps only cited sentences, and related X posts, in a small web app or CLI (deploys to Vercel).
- [AI News Today Board](ai-news-today-board/README.md): Python script that builds a once-a-day board of AI posts and tech news pages from a fixed query plan, deduped, tagged by sub-query and marked new against a seen-links file, using the Desearch API.
- [Article Summarizer (MCP)](article-summarizer-mcp/README.md): Saved prompt and Python CLI that reads one public article with the Desearch MCP extract tool and lists its key points and the numbers it mentions, quoted from the page, with optional links to other coverage through ai-search.
- [Wikipedia Primer (MCP)](wikipedia-primer/README.md): Saved prompt and Python CLI that builds a short, Wikipedia-grounded primer on any topic through the Desearch MCP ai-search tool, with links after each fact and an optional web cross-check.
