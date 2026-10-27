"""Article Summarizer: a 5-bullet summary and the numbers in an article, through the hosted Desearch MCP.

Made by Desearch, https://desearch.ai

Reads one public article with the MCP `extract` tool (plain text, no JavaScript
rendering), picks 5 key sentences and up to 8 sentences that carry a number, and
quotes them as written. With --related it also runs the MCP `ai-search` tool
(web) to list other pages that cover the same story.
Nothing is rewritten: each bullet is a sentence from the text Desearch fetched.
"""
import argparse
import asyncio
import collections
import hashlib
import json
import os
import re
import sys
import urllib.parse

MCP_URL = "https://mcp.desearch.ai/mcp"
DEFAULT_KEY_FILE = os.path.expanduser("~/.desearch-api-key")
MIN_WORDS = 150  # below this the page is treated as near-empty (login wall, app shell, error page)
HANDLE_RE = re.compile(r"(?<![\w/@.])@\w{1,15}\b")
NUMBER_RE = re.compile(r"(?:[$£€]\s?)?\d[\d,.]*(?:\s?(?:%|percent|bn|billion|million|m\b|k\b|trillion))?", re.I)
FOOTNOTE_RE = re.compile(r"\[(?:\d+|[a-z]|note \d+|citation needed)\]")
HATNOTE_RE = re.compile(r"^(?:(?:For broader coverage|For other uses|For the |For a |For more ).*(?:, see |[sS]ee also)|.*redirects here\.|Main articles?:|See also:|Further information:|Not to be confused with|This article is about.*\bFor\b.*, see )")
STOP = set("""a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having
he her here hers him his how i if in into is it its itself just me more most my no nor not now of off on once only
or other our out over own said same she should so some such than that the their them then there these they this
those through to too under until up very was we were what when where which while who whom why will with would you
your one two new like says say get got make made many much even well way back still""".split())


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


def check_url(url):
    """Accept only a full http(s) link to a page."""
    u = (url or "").strip()
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or "." not in p.netloc:
        raise ValueError(f"not a full http(s) link: {url!r}")
    return u


def build_extract_args(url):
    """MCP extract arguments: plain text, no JavaScript rendering."""
    return {"url": check_url(url), "format": "text", "js": False}


def title_from_url(url):
    """'.../2026/oct/18/world-bank-small-ai' -> 'world bank small ai' (a search phrase, not the headline)."""
    path = urllib.parse.urlparse(url).path.rstrip("/")
    parts = [p for p in path.split("/") if p and not p.isdigit() and len(p) > 3]
    slug = parts[-1] if parts else urllib.parse.urlparse(url).netloc
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug)
    words = [w for w in re.split(r"[-_+]", slug) if w and not re.fullmatch(r"[a-z]*\d[a-z0-9]*", w)]
    return " ".join(words[:12])


def build_related_args(title):
    """ai-search arguments to find other pages on the same story. No domain filters."""
    t = " ".join((title or "").split())
    if not t:
        raise ValueError("title is empty")
    return {"prompt": f"news and articles about: {t}", "tools": ["web"], "result_type": "ONLY_LINKS"}


def parse_extract(content):
    """MCP extract content -> {"text": str} or {"error": str, "cost_usd": float|None}."""
    text = ""
    for item in content or []:
        t = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        if t:
            text += t
    if text.startswith("Extract error:"):
        cost = None
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                cost = json.loads(m.group(0)).get("cost_usd")
            except ValueError:
                pass
        return {"error": text, "cost_usd": cost}
    try:
        val = json.loads(text)
        if isinstance(val, str):
            text = val
        elif isinstance(val, dict):
            text = val.get("content") or val.get("text") or ""
    except ValueError:
        pass
    return {"text": text}


def parse_json_content(content):
    for item in content or []:
        t = item.get("text") if isinstance(item, dict) else getattr(item, "text", None)
        if t:
            try:
                return json.loads(t)
            except ValueError:
                return {"text": t}
    return {}


def word_count(text):
    return len(re.findall(r"\w+", text or ""))


def is_near_empty(text, min_words=MIN_WORDS):
    return word_count(text) < min_words


def sentences(text):
    """Split into sentences, keeping each one exactly as written."""
    out = []
    for para in re.split(r"\n\s*\n|\n", text or ""):
        para = para.strip()
        if not para or (len(para.split()) <= 40 and HATNOTE_RE.match(para)):
            continue
        para = re.sub(r'([.!?](?:' + FOOTNOTE_RE.pattern + r')+)\s+(?=[\u201c"A-Z0-9$£€])', r"\1\n", para)
        for s in re.split(r"\n|(?<=[.!?\u201d\"])\s+(?=[\u201c\"A-Z0-9$£€])", para):
            s = s.strip()
            if 6 <= len(s.split()) <= 60:
                out.append(s)
    return out


def _words(s):
    return [w for w in re.findall(r"[a-z][a-z'\u2019]+", s.lower()) if w not in STOP and len(w) > 2]


def key_sentences(text, n=5):
    """The opening sentence plus the n-1 sentences that share the most frequent words, in article order."""
    sents = sentences(text)
    if len(sents) <= n:
        return sents
    freq = collections.Counter(w for s in sents for w in set(_words(s)))
    def score(i):
        ws = set(_words(sents[i]))
        return sum(freq[w] for w in ws) / (len(ws) ** 0.5 + 1)
    picked = {0}
    for i in sorted(range(1, len(sents)), key=score, reverse=True):
        if len(picked) >= n:
            break
        if all(_overlap(sents[i], sents[j]) < 0.6 for j in picked):
            picked.add(i)
    return [sents[i] for i in sorted(picked)]


def _overlap(a, b):
    wa, wb = set(_words(a)), set(_words(b))
    return len(wa & wb) / (min(len(wa), len(wb)) or 1)


def numbers_mentioned(text, limit=8):
    """Sentences that carry a figure, with the figures found. Bare years (1990-2099) alone do not count."""
    rows, seen = [], set()
    for s in sentences(text):
        figs = [m.group(0).strip(" ,.") for m in NUMBER_RE.finditer(FOOTNOTE_RE.sub(" ", s))]
        figs = [f for f in figs if f and not re.fullmatch(r"(19|20)\d\d", f) and not re.fullmatch(r"\d\.\d+\.?", f)]
        if figs and s not in seen:
            seen.add(s)
            rows.append({"figures": figs, "sentence": s})
        if len(rows) >= limit:
            break
    return rows


def related_links(data, article_url, limit=3):
    """Links from an ai-search response, skipping the article's own site."""
    own = urllib.parse.urlparse(article_url).netloc.lower().removeprefix("www.")
    rows, seen = [], set()
    if not isinstance(data, dict):
        return rows
    for val in data.values():
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
            host = urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
            if host == own:
                continue
            seen.add(link)
            rows.append({"title": (r.get("title") or "").strip(), "link": link})
    return rows[:limit]


def hide_handles(text):
    return HANDLE_RE.sub("(an account)", text or "")


def render(url, text, bullets=5, related=None, error=None):
    lines = [f"Article: {url}"]
    if error:
        lines += ["", f"Desearch could not read this page: {error}",
                  "Nothing to summarize. Check the link, or try again in a minute."]
        return "\n".join(lines)
    wc = word_count(text)
    lines.append(f"Text Desearch fetched: {wc} words")
    if is_near_empty(text):
        lines += ["", "This page came back nearly empty (it may need a login or a browser to show the article).",
                  "Not summarizing it, so nothing gets guessed. What came back:", "",
                  "> " + hide_handles(" ".join(text.split()))[:400]]
        return "\n".join(lines)
    lines += ["", f"Key points (sentences quoted from the article):"]
    lines += [f"- {hide_handles(s)}" for s in key_sentences(text, bullets)]
    nums = numbers_mentioned(text)
    lines += ["", "Numbers mentioned:"]
    lines += [f"- {', '.join(n['figures'])}: \"{hide_handles(n['sentence'])}\"" for n in nums] or ["- none found"]
    if related is not None:
        lines += ["", "Other pages on the same story:"]
        lines += [f"- {r['title'] or 'untitled'}: {r['link']}" for r in related] or ["- none found"]
    return "\n".join(lines)


async def call_tools(calls, key):
    """Run [(tool, args), ...] in one MCP session; return raw content lists."""
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
                out.append([c.model_dump(mode="json") for c in res.content])
    return out


def fetch(url, key, related=False, retries=1):
    """Extract the article (one retry if the page came back with no content), then optionally search."""
    calls, results = [], []
    args = build_extract_args(url)
    for _ in range(retries + 1):
        content = asyncio.run(call_tools([("extract", args)], key))[0]
        calls.append(("extract", args)); results.append(content)
        if "No content found" not in json.dumps(content):
            break
    ex = parse_extract(results[-1])
    if related and "text" in ex and not is_near_empty(ex["text"]):
        rargs = build_related_args(title_from_url(url))
        results.append(asyncio.run(call_tools([("ai-search", rargs)], key))[0])
        calls.append(("ai-search", rargs))
    return calls, results


def summarize(url, calls, results, bullets=5):
    ex, related, cost = None, None, 0.0
    for (tool, _), content in zip(calls, results):
        if tool == "extract":
            ex = parse_extract(content)
        else:
            data = parse_json_content(content)
            related = related_links(data, url)
            if isinstance(data, dict) and isinstance(data.get("cost_usd"), (int, float)):
                cost += data["cost_usd"]
    ex = ex or {"error": "no extract call"}
    return render(url, ex.get("text", ""), bullets, related, ex.get("error")), cost


def main(argv=None):
    p = argparse.ArgumentParser(description="Summarize one article with the Desearch MCP extract tool")
    p.add_argument("url", help="a full link to a public article")
    p.add_argument("--related", action="store_true", help="also list other pages on the same story (ai-search, web)")
    p.add_argument("--bullets", type=int, default=5, help="key sentences to keep (default 5)")
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    p.add_argument("--raw", help="save raw responses JSON to this file")
    p.add_argument("--from-raw", help="rebuild the summary from a saved --raw file (no API calls)")
    a = p.parse_args(argv)
    try:
        url = check_url(a.url)
    except ValueError as e:
        sys.exit(str(e))

    if a.from_raw:
        with open(a.from_raw) as f:
            saved = json.load(f)
        calls = [(c["tool"], c["args"]) for c in saved]
        results = [c["content"] for c in saved]
        key = None
    else:
        try:
            key = read_key(a.key_file)
        except (OSError, ValueError) as e:
            sys.exit(f"Put your Desearch API key (console.desearch.ai) in {a.key_file}: {e}")
        calls, results = fetch(url, key, a.related)
        if a.raw:
            with open(a.raw, "w") as f:
                json.dump([{"tool": t, "args": g, "content": r} for (t, g), r in zip(calls, results)],
                          f, indent=2, ensure_ascii=False)
    out, cost = summarize(url, calls, results, a.bullets)
    print(f"(key ...{key_fingerprint(key)})" if key else "(from saved run)")
    print(out)
    n_extract = sum(1 for t, _ in calls if t == "extract")
    print(f"\nCalls: {n_extract} extract" + (f", 1 ai-search (${cost:.4f})" if len(calls) > n_extract else ""))


if __name__ == "__main__":
    main()
