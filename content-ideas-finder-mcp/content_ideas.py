"""Content Ideas Finder: turn real questions into a post plan, through the hosted Desearch MCP.

Made by Desearch, https://desearch.ai

Searches Reddit (and Hacker News for tech niches) with the MCP `ai-search` tool and
X with the MCP `x-search` tool, pulls out the questions people ask, and prints a
content plan: one row per question with a suggested format and the source link.
"""
import argparse
import asyncio
import datetime
import hashlib
import json
import os
import re
import sys

MCP_URL = "https://mcp.desearch.ai/mcp"
DEFAULT_KEY_FILE = os.path.expanduser("~/.desearch-api-key")
QUESTION_WORDS = ("how", "what", "why", "when", "where", "which", "who", "should",
                  "can", "is", "are", "do", "does", "any", "anyone", "has", "have", "will")
HANDLE_RE = re.compile(r"(?<![\w/])@\w{1,15}")


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


def clean_niche(niche):
    if not niche or not niche.strip():
        raise ValueError("niche is empty")
    return " ".join(niche.split())


def build_ai_args(niche, source):
    """ai-search arguments for one source (reddit or hackernews). No domain filters."""
    if source not in ("reddit", "hackernews"):
        raise ValueError("source must be reddit or hackernews")
    return {"prompt": f"questions beginners ask about {clean_niche(niche)}",
            "tools": [source], "result_type": "LINKS_WITH_FINAL_SUMMARY"}


def build_x_args(niche, count=20):
    """x-search arguments. OR terms stay inside parentheses."""
    q = f'({clean_niche(niche)}) ("how do i" OR "how do you" OR "any tips") lang:en -is:retweet'
    return {"query": q, "count": max(1, min(int(count), 100))}


def parse_content(content):
    """MCP text content -> parsed JSON (dict or list), or {"text": ...}."""
    for item in content:
        text = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}
    return {}


def ai_items(data, source):
    """Collect link rows from an ai-search response, under whatever key the API used."""
    rows, seen = [], set()
    if not isinstance(data, dict):
        return rows
    for key, val in data.items():
        if isinstance(val, dict):
            val = val.get("organic_results") or val.get("results") or []
        if not isinstance(val, list):
            continue
        for r in val:
            if not isinstance(r, dict):
                continue
            link = r.get("link") or r.get("url")
            if not link or link in seen:
                continue
            seen.add(link)
            title = clean_title(r.get("title"), link)
            rows.append({"source": source, "title": title, "text": r.get("snippet") or "",
                         "link": link, "date": r.get("date") or r.get("created_at") or ""})
    return rows


def clean_title(title, link=""):
    """Drop site suffixes and the Reddit login-page title; fall back to the link slug."""
    t = (title or "").strip()
    t = re.sub(r"\s*\|\s*Hacker News$", "", t)
    t = re.sub(r"^r/\w+ on Reddit:\s*", "", t)
    t = re.sub(r"\s*:\s*r/\w+$", "", t)
    t = re.sub(r"^(Ask|Tell|Show) HN:\s*", "", t)
    if t == "Welcome to Reddit":
        m = re.search(r"/comments/\w+/([^/?#]+)", link or "")
        t = m.group(1).replace("_", " ").strip().capitalize() if m else ""
    return t


def short_date(value):
    """'Mon Feb 10 19:27:01 +0000 2025' -> '2025-02-10'; other values unchanged."""
    try:
        return datetime.datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").date().isoformat()
    except (TypeError, ValueError):
        return value or ""


def x_items(data):
    posts = data if isinstance(data, list) else (data.get("data") or [] if isinstance(data, dict) else [])
    rows = []
    for p in posts:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        rows.append({"source": "x", "title": "", "text": p.get("text") or "",
                     "link": f"https://x.com/i/status/{pid}" if pid else (p.get("url") or ""),
                     "date": short_date(p.get("created_at"))})
    return rows


def hide_handles(text):
    return HANDLE_RE.sub("(an account)", text)


def _norm(q):
    return re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()


def questions_in(text, is_title=False):
    """Sentences that read like questions. Titles may lack the question mark."""
    text = re.sub(r"https?://\S+", "", text or "")
    text = text.strip()
    parts = [text] if is_title else re.split(r"(?<=[?.!])\s+|\n+", text)
    out = []
    for s in parts:
        s = s.strip(" -\u2022\"'")
        words = s.split()
        if len(words) < 4 or len(words) > 30:
            continue
        first = words[0].lower().strip(",")
        if "?" in s:
            out.append(s[: s.index("?") + 1] if not s.endswith("?") else s)
        elif is_title and first in QUESTION_WORDS and first not in ("is", "are", "do", "does", "has", "have", "can", "will"):
            out.append(s + "?")
    return out


def niche_words(niche):
    """Word stems from the niche, used to keep only on-topic questions."""
    stop = {"about", "with", "from", "your", "that", "this", "what", "for", "the", "and",
            "start", "starting", "begin", "beginner", "beginners", "learn", "learning",
            "getting", "making", "using", "best", "tips", "ideas", "first", "small", "home"}
    return [w[:5] for w in re.findall(r"[a-z0-9]+", (niche or "").lower()) if len(w) >= 4 and w not in stop]


def on_topic(question, stems):
    q = question.lower()
    return not stems or any(st in q for st in stems)


def find_questions(items, limit=10, niche=None):
    """Rank on-topic questions by how often they show up (one per thread or post);
    keep one source link each, and take turns between sources."""
    found = {}
    stems = niche_words(niche)
    for it in items:
        all_qs = questions_in(it["title"], True) + questions_in(it["text"])
        qs = [q for q in all_qs if on_topic(q, stems)]
        weak = False
        # a short post about the niche may ask its question without repeating the niche words
        if not qs and len(it["text"]) < 400 and on_topic(it["title"] + " " + it["text"], stems):
            qs, weak = all_qs, True
        for q in qs[:1]:
            q = re.sub(r"[.\s]+\?$", "?", q)
            k = _norm(q)
            if not k:
                continue
            row = found.setdefault(k, {"question": hide_handles(q), "count": 0, "weak": weak,
                                       "source": it["source"], "link": it["link"], "date": it["date"]})
            row["count"] += 1
    ranked = []
    for weak in (False, True):  # questions that name the niche first
        by_src = {}
        for r in sorted(found.values(), key=lambda r: r["count"], reverse=True):
            if r["weak"] == weak:
                by_src.setdefault(r["source"], []).append(r)
        while any(by_src.values()) and len(ranked) < limit:
            for src in list(by_src):
                if by_src[src] and len(ranked) < limit:
                    ranked.append(by_src[src].pop(0))
    for r in ranked:
        r.pop("weak", None)
    return ranked


def suggest_format(question):
    q = question.lower()
    if re.search(r"\b(best|top|ideas|tips|tools|examples|list|ways)\b", q):
        return "carousel"
    if q.startswith(("how", "can", "what's the easiest", "what is the easiest")):
        return "short video"
    return "thread"


def plan_table(questions):
    lines = ["| # | Question people asked | Post idea | Format | Source | Date |",
             "|---|---|---|---|---|---|"]
    for i, q in enumerate(questions, 1):
        idea = f"Answer it: \"{q['question'].rstrip('?')}\", with your own example"
        lines.append(f"| {i} | {q['question']} | {idea} | {suggest_format(q['question'])} | "
                     f"{q['link']} | {q['date'] or 'not shown'} |")
    return "\n".join(lines)


async def call_tools(calls, key):
    """Run [(tool, args), ...] in one MCP session; return parsed results."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    out = []
    async with create_mcp_http_client(headers={"Authorization": key}) as hc, \
            streamable_http_client(MCP_URL, http_client=hc) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            for tool, args in calls:
                res = await s.call_tool(tool, args, read_timeout_seconds=180)
                out.append(parse_content([c.model_dump() for c in res.content]))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Find content ideas from real questions via Desearch MCP")
    p.add_argument("niche", help='e.g. "starting a newsletter"')
    p.add_argument("--no-hackernews", action="store_true", help="skip Hacker News (non-tech niches)")
    p.add_argument("--no-x", action="store_true", help="skip X")
    p.add_argument("--count", type=int, default=20, help="X posts to read (default 20)")
    p.add_argument("--limit", type=int, default=10, help="questions to keep")
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    p.add_argument("--raw", help="save raw responses JSON to this file")
    p.add_argument("--from-raw", help="rebuild the plan from a saved --raw file (no API calls)")
    a = p.parse_args(argv)

    if a.from_raw:
        with open(a.from_raw) as f:
            saved = json.load(f)
        calls = [(c["tool"], c["args"]) for c in saved]
        results = [c["response"] for c in saved]
        key = None
    else:
        try:
            key = read_key(a.key_file)
        except (OSError, ValueError) as e:
            sys.exit(f"Put your Desearch API key (console.desearch.ai) in {a.key_file}: {e}")
        calls = [("ai-search", build_ai_args(a.niche, "reddit"))]
        if not a.no_hackernews:
            calls.append(("ai-search", build_ai_args(a.niche, "hackernews")))
        if not a.no_x:
            calls.append(("x-search", build_x_args(a.niche, a.count)))
        results = asyncio.run(call_tools(calls, key))
    if a.raw and not a.from_raw:
        with open(a.raw, "w") as f:
            json.dump([{"tool": t, "args": g, "response": r} for (t, g), r in zip(calls, results)],
                      f, indent=2, ensure_ascii=False)

    items, cost = [], 0.0
    for (tool, args), data in zip(calls, results):
        if tool == "ai-search":
            items += ai_items(data, args["tools"][0])
            if isinstance(data, dict) and isinstance(data.get("cost_usd"), (int, float)):
                cost += data["cost_usd"]
        else:
            items += x_items(data)
    questions = find_questions(items, a.limit, a.niche)
    print(f"Niche: {clean_niche(a.niche)}" + (f"  (key ...{key_fingerprint(key)})" if key else "  (from saved run)"))
    print(f"Read {len(items)} threads and posts Desearch returned; found {len(questions)} questions.")
    if len(questions) < a.limit:
        print(f"Fewer than {a.limit} questions came back. Try a broader niche, or ask your assistant with the saved prompt.")
    print()
    print(plan_table(questions))
    print(f"\nai-search cost: ${cost:.4f}")


if __name__ == "__main__":
    main()
