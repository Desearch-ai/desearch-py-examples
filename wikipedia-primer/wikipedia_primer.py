"""Wikipedia Primer: a short, Wikipedia-grounded primer on any topic.

Made by Desearch, https://desearch.ai
Calls the hosted Desearch MCP `ai-search` tool with the Wikipedia source, cleans the
results (drops File:, Talk:, Category: and Wikipedia: pages, marks non-English pages),
turns citation numbers into links, and can add a short web cross-check with `web-search`.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from urllib.parse import urlparse

MCP_URL = "https://mcp.desearch.ai/mcp"
DEFAULT_KEY_FILE = os.path.expanduser("~/.desearch-api-key")
SKIP_PREFIXES = ("File:", "Talk:", "Category:", "Wikipedia:", "Template:", "Help:", "Portal:")
SKIP_WEB_HOSTS = ("reddit.com", "x.com", "twitter.com", "youtube.com", "facebook.com", "tiktok.com")
CITE = re.compile(r"\s*\[\d+\]\((https?://[^)\s]+)\)")
CITE_PLAIN = re.compile(r" \((https?://[^)\s]+)\)")


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


def build_args(topic):
    if not topic or not topic.strip():
        raise ValueError("topic is empty")
    t = topic.strip()
    return {"prompt": f"{t}: what it is, how it works, key facts, criticism, and related topics",
            "tools": ["wikipedia"], "result_type": "LINKS_WITH_FINAL_SUMMARY"}


def web_args(topic):
    return {"query": f"{topic.strip()} explained"}


def parse_json(content):
    for item in content:
        text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return None
    return None


def page_title(r):
    return (r.get("title") or "").replace(" - Wikipedia", "").strip()


def clean_pages(results):
    """Drop non-article pages and duplicates; mark non-English Wikipedia pages."""
    out, seen = [], set()
    for r in results or []:
        link, title = r.get("link") or "", page_title(r)
        host = urlparse(link).netloc
        if not link or link in seen or "wikipedia.org" not in host:
            continue
        path_title = link.rsplit("/wiki/", 1)[-1]
        if title.startswith(SKIP_PREFIXES) or path_title.startswith(tuple(p.replace(" ", "_") for p in SKIP_PREFIXES)):
            continue
        seen.add(link)
        lang = host.split(".")[0]
        out.append({"title": title, "link": link, "lang": lang,
                    "note": "" if lang == "en" else f"{lang} Wikipedia"})
    return out


def link_citations(summary):
    """Replace numbered citations like [3](url) with (url) so numbers are never copied."""
    return CITE.sub(lambda m: f" ({m.group(1)})", summary or "").strip()


NUM = re.compile(r"\d[\d,.]*\d|\d")
SENT = re.compile(r"(?<=[.!?\)])\s+(?=[A-Z])")


def page_texts(results):
    """link -> snippet + highlights text, used to check numbers in the summary."""
    out = {}
    for r in results or []:
        out[r.get("link")] = " ".join([r.get("snippet") or ""] + list(r.get("highlights") or []))
    return out


def check_numbers(summary, results):
    """Keep a sentence's link only if every number in it appears on that page.
    If another returned page has the numbers, link that page instead; otherwise drop the sentence.
    Returns (text, notes)."""
    texts = page_texts(results)
    kept, notes = [], []
    for sent in SENT.split(link_citations(summary)):
        nums = [n.rstrip(".,") for n in NUM.findall(CITE_PLAIN.sub("", sent))]
        links = CITE_PLAIN.findall(sent)
        if not nums or not links or all(all(n in texts.get(l, "") for n in nums) for l in links):
            kept.append(sent)
            continue
        better = next((l for l, t in texts.items() if l and all(n in t for n in nums)), None)
        if better:
            kept.append(CITE_PLAIN.sub(f" ({better})", sent, count=1))
            notes.append(f"Re-linked a fact with {', '.join(nums)} to the page that contains it.")
        else:
            notes.append(f"Left out a fact with {', '.join(nums)}: no returned page contains it.")
    return " ".join(kept), notes


def pick_web(results, n=3):
    out = []
    for r in (results or []):
        host = urlparse(r.get("link") or "").netloc.lower()
        if not host or any(host == h or host.endswith("." + h) for h in SKIP_WEB_HOSTS):
            continue
        out.append({"title": r.get("title", ""), "link": r["link"]})
        if len(out) == n:
            break
    return out


def format_primer(topic, wiki, web=None):
    pages = clean_pages((wiki or {}).get("search"))
    lines = [f"## {topic}: a primer", ""]
    if not any(p["lang"] == "en" for p in pages):
        lines += ["No English Wikipedia article came back for this topic.", ""]
    text, notes = check_numbers((wiki or {}).get("completion"), (wiki or {}).get("search"))
    lines += [text, "", "### Wikipedia pages"]
    lines += [f"- {p['title']}{' (' + p['note'] + ')' if p['note'] else ''}: {p['link']}" for p in pages[:6]]
    if web is not None:
        lines += ["", "### Web cross-check (read these next)"]
        picks = pick_web((web or {}).get("data"))
        lines += [f"- {w['title']}: {w['link']}" for w in picks] or ["- No web pages came back."]
    if notes:
        lines += ["", "### Notes"] + [f"- {n}" for n in notes]
    return "\n".join(lines)


async def run(topic, key, cross_check):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    async with create_mcp_http_client(headers={"Authorization": key}) as hc, \
            streamable_http_client(MCP_URL, http_client=hc) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            res = await s.call_tool("ai-search", build_args(topic), read_timeout_seconds=180)
            wiki = parse_json([c.model_dump() for c in res.content])
            web = None
            if cross_check:
                res = await s.call_tool("web-search", web_args(topic), read_timeout_seconds=180)
                web = parse_json([c.model_dump() for c in res.content]) or {}
            return wiki, web


def main(argv=None):
    p = argparse.ArgumentParser(description="Wikipedia-grounded primer via Desearch MCP")
    p.add_argument("topic", help='e.g. "carbon credits"')
    p.add_argument("--web", action="store_true", help="add a web cross-check")
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    a = p.parse_args(argv)
    try:
        key = read_key(a.key_file)
    except (OSError, ValueError) as e:
        sys.exit(f"Put your Desearch API key (console.desearch.ai) in {a.key_file}: {e}")
    print(f"key sha256 ...{key_fingerprint(key)}", file=sys.stderr)
    wiki, web = asyncio.run(run(a.topic, key, a.web))
    print(format_primer(a.topic, wiki, web))


if __name__ == "__main__":
    main()
