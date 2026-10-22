"""Who's Asking For It: find recent public X posts where people ask for a tool like yours.

Made by Desearch, https://desearch.ai
Runs a few phrase-group searches through the hosted Desearch MCP `x-search` tool,
keeps posts inside your date window, scores buying intent and prints a ranked table.
"""
import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import sys

MCP_URL = "https://mcp.desearch.ai/mcp"
DEFAULT_KEY_FILE = os.path.expanduser("~/.desearch-api-key")

DEFAULT_GROUPS = [
    '("which newsletter platform" OR "what newsletter platform" OR "best newsletter platform" OR "newsletter platform recommendations")',
    '("alternative to" OR "switching from" OR "moving my newsletter") newsletter',
    '("recommend" OR "looking for" OR "suggestions") ("newsletter platform" OR "newsletter tool")',
]

ASK = re.compile(r"\b(anyone recommend|can anyone recommend|any recommendations|recommendations\?|suggestions\?|i'?m looking for|we'?re looking for|which \w+ should i|thinking of switching|switching from|alternative to)\b", re.I)
QUESTION = re.compile(r"\b(which|what|best|anyone use|thoughts on)\b", re.I)
PROMO = re.compile(r"\b(check out|launch(ed|ing)?|sign up|subscribe|join us|webinar|newsletter is out)\b", re.I)


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


def window(days, today=None):
    end = today or dt.date.today()
    return (end - dt.timedelta(days=days)).isoformat(), end.isoformat()


def build_args(group, start, end, count=50):
    """x-search arguments for one phrase group. OR terms stay inside parentheses."""
    if not group or not group.strip():
        raise ValueError("phrase group is empty")
    q = group.strip()
    if "-filter:retweets" not in q:
        q += " -filter:retweets"
    return {"query": q, "count": int(count), "start_date": start, "end_date": end, "lang": "en"}


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


def post_date(p):
    try:
        return dt.datetime.strptime(p.get("created_at", ""), "%a %b %d %H:%M:%S %z %Y").date()
    except ValueError:
        return None


def intent(text):
    """High = asking for a recommendation or ready to switch. Medium = open question. Low = the rest."""
    t = text or ""
    if ASK.search(t) and "?" in t and not PROMO.search(t):
        return "High"
    if QUESTION.search(t) and "?" in t and not PROMO.search(t):
        return "Medium"
    return "Low"


def rank(posts, start, end):
    """Dedupe by URL, drop posts outside the window, sort High > Medium > Low, then newest."""
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    seen, rows = set(), []
    for p in posts:
        url = p.get("url")
        d = post_date(p)
        if not url or url in seen or d is None or not (s <= d <= e):
            continue
        seen.add(url)
        text = " ".join((p.get("text") or "").split())
        rows.append({"intent": intent(text), "date": d.isoformat(),
                     "who": (p.get("user") or {}).get("username", ""), "text": text[:100], "link": url})
    order = {"High": 0, "Medium": 1, "Low": 2}
    rows.sort(key=lambda r: r["date"], reverse=True)
    rows.sort(key=lambda r: order[r["intent"]])
    return rows


def format_table(rows, hide_handles=False):
    lines = ["Rank | Intent | Date | Who | What they said | Link"]
    for i, r in enumerate(rows, 1):
        who = f"person #{i}" if hide_handles else f"@{r['who']}"
        link = "(hidden)" if hide_handles else r["link"]
        said = "(hidden)" if hide_handles else r["text"]
        lines.append(f"{i} | {r['intent']} | {r['date']} | {who} | {said} | {link}")
    return "\n".join(lines)


async def search_all(arg_list, key):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    out = []
    async with create_mcp_http_client(headers={"Authorization": key}) as hc, \
            streamable_http_client(MCP_URL, http_client=hc) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            for args in arg_list:
                res = await s.call_tool("x-search", args, read_timeout_seconds=180)
                out.append(parse_posts([c.model_dump() for c in res.content]))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Find people asking for a tool like yours (Desearch MCP)")
    p.add_argument("--group", action="append", help="phrase group with OR terms in parentheses (repeatable)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    p.add_argument("--hide-handles", action="store_true")
    a = p.parse_args(argv)
    try:
        key = read_key(a.key_file)
    except (OSError, ValueError) as e:
        sys.exit(f"Put your Desearch API key (console.desearch.ai) in {a.key_file}: {e}")
    print(f"key sha256 ...{key_fingerprint(key)}", file=sys.stderr)
    start, end = window(a.days)
    arg_list = [build_args(g, start, end, a.count) for g in (a.group or DEFAULT_GROUPS)]
    results = asyncio.run(search_all(arg_list, key))
    posts = [x for r in results for x in r]
    rows = rank(posts, start, end)
    print(f"{' + '.join(str(len(r)) for r in results)} posts returned, {len(rows)} kept ({start} to {end})")
    print(format_table(rows, a.hide_handles))


if __name__ == "__main__":
    main()
