"""Search Reddit through the hosted Desearch MCP `ai-search` tool.

Made by Desearch, https://desearch.ai
Reddit is a source of the MCP ai-search tool only, so this script talks to MCP.
"""
import argparse
import asyncio
import json
import os
import sys

MCP_URL = "https://mcp.desearch.ai/mcp"


def build_args(topic, result_type="LINKS_WITH_FINAL_SUMMARY"):
    """Arguments for the ai-search tool with Reddit as the only source."""
    if not topic or not topic.strip():
        raise ValueError("topic is empty")
    return {"prompt": topic.strip(), "tools": ["reddit"], "result_type": result_type}


def parse_result(content):
    """Turn MCP text content into a dict (links, summary, cost)."""
    for item in content:
        text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}
    return {}


def reddit_links(data):
    """Collect reddit.com links from the response, wherever the API put them."""
    found = []
    for key in ("search", "reddit_search", "reddit_search_results"):
        val = data.get(key)
        if isinstance(val, dict):
            val = val.get("organic_results") or val.get("results") or []
        for r in val or []:
            if isinstance(r, dict) and "reddit.com" in (r.get("link") or r.get("url") or ""):
                title = r.get("title", "")
                if title.strip() == "Welcome to Reddit":
                    title = "(title hidden by Reddit login page)"
                found.append({"title": title, "link": r.get("link") or r.get("url")})
    return found


async def search(topic, key, result_type="LINKS_WITH_FINAL_SUMMARY"):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    async with create_mcp_http_client(headers={"Authorization": key}) as hc, \
            streamable_http_client(MCP_URL, http_client=hc) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            res = await s.call_tool("ai-search", build_args(topic, result_type),
                                    read_timeout_seconds=180)
            content = [c.model_dump() for c in res.content]
            return parse_result(content)


def main(argv=None):
    p = argparse.ArgumentParser(description="Search Reddit via Desearch MCP")
    p.add_argument("topic")
    p.add_argument("--links-only", action="store_true")
    p.add_argument("--raw", help="save the full JSON response to this file")
    a = p.parse_args(argv)
    key = os.environ.get("DESEARCH_API_KEY")
    if not key:
        sys.exit("Set DESEARCH_API_KEY (get one at console.desearch.ai)")
    rt = "ONLY_LINKS" if a.links_only else "LINKS_WITH_FINAL_SUMMARY"
    data = asyncio.run(search(a.topic, key, rt))
    if a.raw:
        with open(a.raw, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    for i, r in enumerate(reddit_links(data), 1):
        print(f"{i}. {r['title']}\n   {r['link']}")
    if data.get("completion"):
        print("\nSummary:\n" + str(data["completion"]))
    if "cost_usd" in data:
        print(f"\nCost: ${data['cost_usd']}")


if __name__ == "__main__":
    main()
