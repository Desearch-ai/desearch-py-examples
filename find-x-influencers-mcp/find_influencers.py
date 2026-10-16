"""Find active X voices on a topic through the hosted Desearch MCP `x-search` tool.

Made by Desearch, https://desearch.ai
Searches public posts on a topic, groups them by author, keeps authors with
2 or more posts, and ranks them by total likes.
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys

MCP_URL = "https://mcp.desearch.ai/mcp"
DEFAULT_KEY_FILE = os.path.expanduser("~/.desearch-api-key")


def read_key(path):
    """Read the API key from a file (never from the environment)."""
    with open(path) as f:
        key = f.read().strip()
    if not key:
        raise ValueError(f"key file {path} is empty")
    return key


def key_fingerprint(key):
    """Last 4 hex chars of the key's sha256, safe to print."""
    return hashlib.sha256(key.encode()).hexdigest()[-4:]


def build_args(topic, count=50, verified=None, min_likes=None):
    """Arguments for x-search. Wrap OR terms in parentheses yourself."""
    if not topic or not topic.strip():
        raise ValueError("topic is empty")
    q = topic.strip()
    if "-is:retweet" not in q:
        q += " -is:retweet"
    args = {"query": q, "count": int(count)}
    if verified is not None:
        args["verified"] = bool(verified)
    if min_likes is not None:
        args["min_likes"] = int(min_likes)
    return args


def parse_posts(content):
    """MCP text content -> list of posts."""
    for item in content:
        text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        if text:
            try:
                data = json.loads(text)
            except ValueError:
                return []
            if isinstance(data, dict):
                data = data.get("data") or data.get("results") or []
            return data if isinstance(data, list) else []
    return []


def rank_authors(posts, min_posts=2):
    """Group posts by author; keep authors with >= min_posts; rank by total likes."""
    by = {}
    seen = set()
    for p in posts:
        u = p.get("user") or {}
        handle = u.get("username")
        if not handle or p.get("id") in seen:
            continue
        seen.add(p.get("id"))
        a = by.setdefault(handle, {"handle": handle, "name": u.get("name", ""),
                                   "followers": u.get("followers_count"),
                                   "posts": 0, "likes": 0, "top_link": None, "_top": -1})
        likes = p.get("like_count") or 0
        a["posts"] += 1
        a["likes"] += likes
        if likes > a["_top"]:
            a["_top"] = likes
            a["top_link"] = p.get("url") or f"https://x.com/i/status/{p.get('id')}"
    out = [a for a in by.values() if a["posts"] >= min_posts]
    for a in out:
        a.pop("_top")
    out.sort(key=lambda a: (a["likes"], a["posts"]), reverse=True)
    return out


async def search(args, key):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    async with create_mcp_http_client(headers={"Authorization": key}) as hc, \
            streamable_http_client(MCP_URL, http_client=hc) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            res = await s.call_tool("x-search", args, read_timeout_seconds=180)
            return parse_posts([c.model_dump() for c in res.content])


def format_table(ranked, hide_handles=False):
    lines = ["#  author | followers | posts | likes | top post"]
    for i, a in enumerate(ranked, 1):
        who = f"a creator #{i}" if hide_handles else f"@{a['handle']}"
        link = "(hidden)" if hide_handles else a["top_link"]
        lines.append(f"{i}. {who} | {a['followers']} | {a['posts']} | {a['likes']} | {link}")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="Find X voices on a topic via Desearch MCP")
    p.add_argument("topic", help='e.g. \'("sourdough" OR "bread baking") lang:en\'')
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--min-posts", type=int, default=2)
    p.add_argument("--verified", action="store_true")
    p.add_argument("--min-likes", type=int)
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    p.add_argument("--hide-handles", action="store_true")
    p.add_argument("--raw", help="save raw posts JSON to this file")
    a = p.parse_args(argv)
    try:
        key = read_key(a.key_file)
    except (OSError, ValueError) as e:
        sys.exit(f"Put your Desearch API key (console.desearch.ai) in {a.key_file}: {e}")
    print(f"key sha256 ...{key_fingerprint(key)}", file=sys.stderr)
    args = build_args(a.topic, a.count, True if a.verified else None, a.min_likes)
    posts = asyncio.run(search(args, key))
    if a.raw:
        with open(a.raw, "w") as f:
            json.dump(posts, f, indent=2, ensure_ascii=False)
    ranked = rank_authors(posts, a.min_posts)
    print(f"{len(posts)} posts, {len({(x.get('user') or {}).get('username') for x in posts})} authors, "
          f"{len(ranked)} with {a.min_posts}+ posts")
    print(format_table(ranked, a.hide_handles))


if __name__ == "__main__":
    main()
