"""Pricing Page Snapshot: read pricing pages and save a plan and price table.

Made by Desearch, https://desearch.ai
Reads each page with the hosted Desearch MCP `extract` tool (text, js false), pulls
plan names and prices from the page text, prints a table and can save it as JSON so the
next run can show what changed.
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
PRICE = re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\bCustom\b|\bFree\b)", re.I)
NO_NAME = "(name not in page text)"


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


def build_args(url):
    """extract arguments: plain text, js false."""
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(f"not a URL: {url!r}")
    return {"url": url, "format": "text", "js": False}


def page_text(content):
    """MCP content -> page text ('' when empty or an error)."""
    for item in content:
        if (item.get("type") if isinstance(item, dict) else None) == "text":
            text = item.get("text") or ""
            if text.startswith("Extract error"):
                return ""
            try:
                val = json.loads(text)
                return val if isinstance(val, str) else ""
            except ValueError:
                return text
    return ""


def is_price_line(line):
    return bool(re.match(r"^\s*(?:[$€£]\s?\d|Custom\s*$)", line, re.I))


def parse_plans(text):
    """Find 'Plan name' followed by a price line, in page order. First match per plan only."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    plans, seen = [], set()
    for i, line in enumerate(lines):
        if not is_price_line(line):
            continue
        name = NO_NAME
        prev = lines[i - 1] if i else ""
        if prev and len(prev) <= 30 and not is_price_line(prev) and not prev.endswith((".", ":", "+")):
            name = prev
        if name in seen:
            continue
        seen.add(name)
        period = ""
        for nxt in lines[i + 1:i + 3]:
            if re.search(r"billed (yearly|annually|monthly)|annual billing", nxt, re.I):
                period = nxt
                break
        plans.append({"plan": name, "price": line, "billing": period or "not shown"})
        if name == NO_NAME:
            seen.discard(name)
    return plans


def compare(old, new):
    """Return change lines between two {url: [plans]} snapshots."""
    out = []
    for url in sorted(set(old) | set(new)):
        o = {p["plan"]: p for p in old.get(url, [])}
        n = {p["plan"]: p for p in new.get(url, [])}
        if url in new and not new[url]:
            out.append(f"{url} | could not check (no prices in page text)")
            continue
        for plan in sorted(set(o) | set(n)):
            if plan not in o:
                out.append(f"{url} | {plan} | added | - | {n[plan]['price']}")
            elif plan not in n:
                out.append(f"{url} | {plan} | removed | {o[plan]['price']} | -")
            elif o[plan]["price"] != n[plan]["price"]:
                out.append(f"{url} | {plan} | price | {o[plan]['price']} | {n[plan]['price']}")
    return out


def format_table(snapshot, date):
    lines = ["Page | Plan | Price as written | Billing | Snapshot date"]
    for url, plans in snapshot.items():
        if not plans:
            lines.append(f"{url} | No prices in page text | | | {date}")
        for p in plans:
            lines.append(f"{url} | {p['plan']} | {p['price']} | {p['billing']} | {date}")
    return "\n".join(lines)


async def read_pages(urls, key, retry_wait=5):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    out = {}
    async with create_mcp_http_client(headers={"Authorization": key}) as hc, \
            streamable_http_client(MCP_URL, http_client=hc) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            for url in urls:
                text = ""
                for attempt in range(2):  # one retry if the page text comes back empty
                    res = await s.call_tool("extract", build_args(url), read_timeout_seconds=180)
                    text = page_text([c.model_dump() for c in res.content])
                    if text.strip():
                        break
                    await asyncio.sleep(retry_wait)
                out[url] = text
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Pricing page snapshot via Desearch MCP extract")
    p.add_argument("urls", nargs="+")
    p.add_argument("--save", help="save today's snapshot JSON here")
    p.add_argument("--compare", help="earlier snapshot JSON to compare with")
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    a = p.parse_args(argv)
    for u in a.urls:
        build_args(u)
    try:
        key = read_key(a.key_file)
    except (OSError, ValueError) as e:
        sys.exit(f"Put your Desearch API key (console.desearch.ai) in {a.key_file}: {e}")
    print(f"key sha256 ...{key_fingerprint(key)}", file=sys.stderr)
    texts = asyncio.run(read_pages(a.urls, key))
    snap = {u: parse_plans(t) for u, t in texts.items()}
    date = dt.date.today().isoformat()
    print(format_table(snap, date))
    if a.compare:
        with open(a.compare) as f:
            old = json.load(f)["pages"]
        changes = compare(old, snap)
        print("\nChanges:\n" + ("\n".join(changes) if changes else "No pricing changes since the last snapshot"))
    if a.save:
        with open(a.save, "w") as f:
            json.dump({"date": date, "pages": snap}, f, indent=2)


if __name__ == "__main__":
    main()
