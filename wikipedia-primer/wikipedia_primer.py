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
import unicodedata
from urllib.parse import unquote, urlparse

MCP_URL = "https://mcp.desearch.ai/mcp"
DEFAULT_KEY_FILE = os.path.expanduser("~/.desearch-api-key")
# Wikipedia namespaces that are not articles. "<name> talk" variants (User talk, File talk...) are caught too.
NON_ARTICLE_NAMESPACES = {
    "talk", "user", "wikipedia", "wp", "project", "file", "image", "media", "mediawiki", "template",
    "help", "category", "portal", "draft", "timedtext", "module", "book", "special", "gadget",
    "gadget definition", "education program", "topic", "event",
}
TITLE_SUFFIX = re.compile(r"\s+[-\u2013\u2014|]\s+[^-\u2013\u2014|]*(wiki|\u0432\u0438\u043a\u0438|\u7dad\u57fa|\u7ef4\u57fa)[^-\u2013\u2014|]*$", re.I)
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
    """Result title without the trailing site name (" - Wikipedia", " - Wikip\u00e9dia" and so on)."""
    return TITLE_SUFFIX.sub("", (r.get("title") or "").strip()).strip()


def norm(text):
    """Lowercase, URL-decoded, underscores as spaces, no #fragment, single spaces."""
    t = unicodedata.normalize("NFC", unquote(text or "").split("#", 1)[0]).replace("_", " ")
    return " ".join(t.split()).casefold()


def is_non_article(name):
    """True for Talk:, User:, File:, Category:, ... and every "<namespace> talk:" page."""
    n = norm(name)
    if ":" not in n:
        return False
    ns = n.split(":", 1)[0].strip()
    return ns in NON_ARTICLE_NAMESPACES or ns.endswith(" talk")


def wiki_slug(link):
    """Article name from a Wikipedia link, or None if it is not https://<lang>.wikipedia.org/wiki/<name>."""
    u = urlparse(link or "")
    host = u.netloc.lower()
    if not (host == "wikipedia.org" or host.endswith(".wikipedia.org")) or not u.path.startswith("/wiki/"):
        return None
    return u.path[len("/wiki/"):] or None


def drop_reason(r):
    """Why a result is left out of the page list, or None to keep it."""
    link, title = r.get("link") or "", page_title(r)
    slug = wiki_slug(link)
    if slug is None:
        return "not a Wikipedia article link"
    if is_non_article(slug) or is_non_article(title):
        return "not an article (talk, user, file, category or other namespace page)"
    if norm(title) != norm(slug):
        return "title does not match the page it links to"
    return None


def clean_pages(results, dropped=None):
    """Keep Wikipedia articles whose title matches their link; drop duplicates; mark non-English pages.
    If a list is passed as `dropped`, each left-out result is added to it with the reason."""
    out, seen = [], set()
    for r in results or []:
        link, title = r.get("link") or "", page_title(r)
        reason = drop_reason(r)
        if reason:
            if dropped is not None:
                dropped.append({"title": title, "link": link, "reason": reason})
            continue
        if link in seen:
            continue
        seen.add(link)
        lang = urlparse(link).netloc.lower().split(".")[0]
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


def check_numbers(summary, results, dropped_links=()):
    """Keep a sentence's link only if every number in it appears on that page.
    If another returned page has the numbers, link that page instead; otherwise drop the sentence.
    Links to pages in `dropped_links` are removed first; a sentence left with no link is dropped.
    Returns (text, notes)."""
    dropped_links = set(dropped_links)
    texts = {l: t for l, t in page_texts(results).items() if l not in dropped_links}
    kept, notes = [], []
    for sent in SENT.split(link_citations(summary)):
        if dropped_links and any(l in dropped_links for l in CITE_PLAIN.findall(sent)):
            sent = CITE_PLAIN.sub(lambda m: "" if m.group(1) in dropped_links else m.group(0), sent)
            if not CITE_PLAIN.findall(sent):
                notes.append("Left out a fact cited only to a page that was left out.")
                continue
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
    dropped = []
    pages = clean_pages((wiki or {}).get("search"), dropped)
    lines = [f"## {topic}: a primer", ""]
    if not any(p["lang"] == "en" for p in pages):
        lines += ["No English Wikipedia article came back for this topic.", ""]
    text, notes = check_numbers((wiki or {}).get("completion"), (wiki or {}).get("search"),
                                {d["link"] for d in dropped})
    lines += [text, "", "### Wikipedia pages"]
    lines += [f"- {p['title']}{' (' + p['note'] + ')' if p['note'] else ''}: {p['link']}" for p in pages[:6]]
    if web is not None:
        lines += ["", "### Web cross-check (read these next)"]
        picks = pick_web((web or {}).get("data"))
        lines += [f"- {w['title']}: {w['link']}" for w in picks] or ["- No web pages came back."]
    notes += [f"Left out {d['title'] or d['link']}: {d['reason']}." for d in dropped]
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
