# Saved prompt: Find X Influencers in MCP

Made by Desearch, https://desearch.ai

Works in any MCP client connected to the hosted Desearch MCP server (`https://mcp.desearch.ai/mcp`, with your Desearch API key in the `Authorization` header). Setup: https://www.desearch.ai/docs/guide/sdk/mcp

Replace `<topic words>` (wrap OR terms in parentheses) and paste:

```
Use the Desearch x-search tool with query '(<topic words>) lang:en -is:retweet', count 50, verified true, min_likes 10.
Then group the posts by author and keep authors with 2 or more posts.
Give me a table ranked by total likes: author, followers, number of posts, total likes, their most liked post link.
Below the table, list authors with only 1 post but more than 10,000 followers as "worth a look".
Say how many posts came back in total and how old the oldest one is.
If fewer than 3 authors have 2+ posts, say so plainly and suggest a broader topic.
```

Tip: add start_date and end_date (YYYY-MM-DD) to keep the list to people who post about the topic now.

Tested 2026-10-16 15:14 Asia/Tbilisi with the topic `"sourdough" OR "bread baking"`: 50 posts, 38 authors, 5 authors with 2+ posts, follower counts on every row.
