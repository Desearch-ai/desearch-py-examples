#!/usr/bin/env python3
"""Morning Topic Brief: a daily cited digest of the last 24h for a few topics.

Calls Desearch AI Search (POST https://api.desearch.ai/desearch/ai/search) once per
topic, builds a Markdown digest, writes it to a file, prints it, and optionally sends
it to Telegram.

Env vars (by name only):
  DESEARCH_API_KEY    required, your key from console.desearch.ai
  TELEGRAM_BOT_TOKEN  optional, Telegram bot token
  TELEGRAM_CHAT_ID    optional, chat id to send the digest to
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
import yaml

API_URL = "https://api.desearch.ai/desearch/ai/search"

SYSTEM_MESSAGE = (
    "You are writing a short morning research brief for a developer. "
    "Use only the search results provided, from the last 24 hours. "
    "Write 3 to 5 bullet points, one sentence each, most important first. "
    "End every bullet with the source URL in square brackets, e.g. [https://example.com/post]. "
    "If the results contain nothing new from the last 24 hours, say so in one line. "
    "No intro, no outro, no headings."
)

# Response keys that hold result lists, per tool, as seen in the live API and docs.
RESULT_KEYS = {
    "tweets": "twitter",
    "search": "web",
    "reddit_search": "reddit",
    "hacker_news_search": "hackernews",
    "youtube_search": "youtube",
    "arxiv_search": "arxiv",
    "wikipedia_search": "wikipedia",
}
COST_HEADERS = ["X-Desearch-Cost-Usd", "X-Desearch-Usage-Count",
                "X-Desearch-Service", "X-Desearch-Currency"]


def now_local() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def norm_url(u: str) -> str:
    """Normalise a URL for duplicate detection (drop query/fragment, trailing slash, x/twitter host)."""
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return u
    host = p.netloc.lower().removeprefix("www.")
    if host in ("twitter.com", "mobile.twitter.com"):
        host = "x.com"
    # keep the query (Hacker News ids live in ?id=), drop tracking params and fragment
    q = "&".join(x for x in p.query.split("&") if x and not x.startswith(("utm_", "s=", "t=")))
    return urlunsplit(("https", host, p.path.rstrip("/"), q, ""))


def build_payload(topic: str, cfg: dict) -> dict:
    payload = {
        # Bare topic works better than a sentence: the X source matches prompt words literally
        # (a "what happened in the last 24 hours" prompt pulled unrelated recap posts).
        "prompt": topic,
        "tools": cfg.get("tools", ["web", "twitter", "reddit", "hackernews"]),
        "date_filter": cfg.get("date_filter", "PAST_24_HOURS"),
        "result_type": cfg.get("result_type", "LINKS_WITH_FINAL_SUMMARY"),
        "system_message": SYSTEM_MESSAGE,
        "streaming": False,
    }
    if cfg.get("count"):
        payload["count"] = int(cfg["count"])
    return payload


def call_http(payload: dict, api_key: str, timeout: int) -> dict:
    """Plain HTTP call. Returns status, headers, body, latency."""
    t0 = time.perf_counter()
    r = requests.post(API_URL, json=payload, timeout=timeout,
                      headers={"Authorization": api_key, "Content-Type": "application/json"})
    latency = time.perf_counter() - t0
    try:
        body = r.json()
    except ValueError:
        body = r.text
    return {"status": r.status_code, "headers": dict(r.headers), "body": body, "latency_s": round(latency, 2)}


def call_sdk(payload: dict, api_key: str, timeout: int) -> dict:
    """Same call through the official desearch-py SDK (async). Error bodies are not exposed by the SDK."""
    from desearch_py import Desearch  # imported lazily so the SDK stays optional

    async def run():
        async with Desearch(api_key=api_key) as client:
            return await client.ai_search(
                prompt=payload["prompt"], tools=payload["tools"],
                date_filter=payload["date_filter"], result_type=payload["result_type"],
                system_message=payload["system_message"], count=payload.get("count"),
                include_metadata=True,
            )

    t0 = time.perf_counter()
    try:
        res = asyncio.run(run())
    except Exception as e:  # aiohttp.ClientResponseError on non-2xx
        # Do NOT log repr(e): aiohttp's ClientResponseError repr includes the request headers,
        # i.e. the Authorization key. Keep only status + reason (the SDK drops the error body).
        return {"status": getattr(e, "status", None), "headers": {},
                "body": {"sdk_error": f"{type(e).__name__}: {getattr(e, 'message', '')}"},
                "latency_s": round(time.perf_counter() - t0, 2)}
    latency = time.perf_counter() - t0
    data = res.data.model_dump() if hasattr(res.data, "model_dump") else res.data
    meta = res.metadata.model_dump() if res.metadata else {}
    headers = {
        "X-Desearch-Cost-Usd": meta.get("cost_usd"), "X-Desearch-Usage-Count": meta.get("usage_count"),
        "X-Desearch-Service": meta.get("service"), "X-Desearch-Currency": meta.get("currency"),
    }
    return {"status": 200, "headers": {k: v for k, v in headers.items() if v is not None},
            "body": data, "latency_s": round(latency, 2)}


def guess_source(url: str, default: str) -> str:
    host = urlsplit(url).netloc.lower()
    if "reddit.com" in host:
        return "reddit"
    if "ycombinator.com" in host:
        return "hackernews"
    if host.endswith(("x.com", "twitter.com")):
        return "twitter"
    return default


def clean_title(title: str, url: str) -> str:
    title = (title or "").strip()
    if not title or title.lower() in ("welcome to reddit", "reddit - the heart of the internet"):
        # Reddit pages sometimes come back with the login-wall title; use the URL slug instead.
        parts = [x for x in urlsplit(url).path.split("/") if x]
        if "comments" in parts and len(parts) > parts.index("comments") + 2:
            sub = parts[parts.index("r") + 1] if "r" in parts else "reddit"
            return f"r/{sub}: " + parts[parts.index("comments") + 2].replace("_", " ")
        return url
    return title


def item_date(item: dict) -> dt.datetime | None:
    raw = item.get("created_at") or item.get("published_date")
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def _flatten(body: dict, keys: list[str]) -> list[dict]:
    links = []
    for key in keys:
        for item in body.get(key) or []:
            if not isinstance(item, dict):
                continue
            url = item.get("link") or item.get("url")
            if not url:
                continue
            title = item.get("title") or (item.get("text") or "").replace("\n", " ")[:100]
            links.append({"source": guess_source(url, RESULT_KEYS[key]), "title": clean_title(title, url),
                          "url": url, "date": item_date(item)})
    return links


CITE_LINKED = re.compile(r"\[(\d+)\]\((\S+?)\)")
CITE_BARE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\](?!\()")


def citation_order(body: dict) -> list[dict] | None:
    """Work out which flattened result list the completion's [n] numbers point into.

    Observed 2026-10-03: the completion numbers results 1..N, but sometimes X posts come
    first and sometimes web results come first, independent of JSON key order. We test both
    orders against the citations the API already linked ([n](url)); None if undecidable.
    """
    others = [k for k in RESULT_KEYS if k not in ("tweets", "search")]
    candidates = [_flatten(body, ["tweets", "search"] + others), _flatten(body, ["search", "tweets"] + others)]
    linked = [(int(n), u) for n, u in CITE_LINKED.findall(body.get("completion") or "")]
    if not linked:
        return None
    ok = [c for c in candidates if all(0 < n <= len(c) and c[n - 1]["url"] == u for n, u in linked)]
    return ok[0] if ok else None


def extract_links(body: dict) -> list[dict]:
    if not isinstance(body, dict):
        return []
    return _flatten(body, list(RESULT_KEYS))


def resolve_citations(summary: str, order: list[dict] | None) -> str:
    """Turn bare citations like [8, 17] into links when the numbering order is known."""
    if order is None:
        return summary

    def repl(m):
        out = []
        for n in re.split(r"\s*,\s*", m.group(1)):
            i = int(n)
            out.append(f"[{i}]({order[i - 1]['url']})" if 0 < i <= len(order) else f"[{i}]")
        return "".join(out)
    return CITE_BARE.sub(repl, summary)


def get_cost(resp: dict) -> float | None:
    h = {k.lower(): v for k, v in resp.get("headers", {}).items()}
    v = h.get("x-desearch-cost-usd")
    if v is None and isinstance(resp.get("body"), dict):
        v = resp["body"].get("cost_usd")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def topic_section(topic: str, resp: dict, max_links: int, strict: bool = True) -> tuple[str, dict]:
    body = resp["body"]
    stats = {"topic": topic, "status": resp["status"], "latency_s": resp["latency_s"],
             "cost_usd": get_cost(resp)}
    lines = [f"## {topic}", ""]
    if resp["status"] != 200 or not isinstance(body, dict):
        lines += [f"_Desearch returned HTTP {resp['status']}: {json.dumps(body)[:300]}_", ""]
        return "\n".join(lines), stats
    summary = (body.get("completion") or "").strip()
    # Undocumented "warnings" list, e.g. {"code": "tool_no_results", "tool": "web", ...}
    warnings = body.get("warnings") or []
    stats["warnings"] = warnings
    links = extract_links(body)
    seen, uniq = set(), []
    for l in links:
        k = norm_url(l["url"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(l)
    stats.update(links_total=len(links), links_unique=len(uniq),
                 result_keys=[k for k in body if k in RESULT_KEYS],
                 per_source={s: sum(1 for l in links if l["source"] == s) for s in set(RESULT_KEYS.values())})
    # citations in the summary that are not among returned links
    cited = re.findall(r"https?://[^\s\]\)>,]+", summary)
    known = {norm_url(l["url"]) for l in links}
    stats["summary_citations"] = len(cited)
    stats["summary_citations_not_in_results"] = [c for c in cited if norm_url(c) not in known]
    order = citation_order(body)
    stats["bare_citations"] = len(CITE_BARE.findall(summary))
    stats["citation_order"] = None if order is None else ("tweets-first" if order and order[0]["source"] == "twitter" and body.get("tweets") and order[0]["url"] == (body["tweets"][0].get("url")) else "search-first")
    rendered = resolve_citations(summary, order)
    if CITE_BARE.search(rendered):
        rendered += "\n\n_Some numbered citations could not be matched to a link; see Sources below._"
    lines.append(rendered or "_No summary returned._")
    # Freshness: the API returns some dated web results older than the 24h window.
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    for l in uniq:
        l["fresh"] = None if l["date"] is None else l["date"] >= cutoff.replace(hour=0, minute=0, second=0, microsecond=0)  # day granularity for date-only values
    stale = [l for l in uniq if l["fresh"] is False]
    # flag stale sources that the summary itself cites
    for l in stale:
        lines = [x.replace(f"]({l['url']})", f"]({l['url']}) (older: {l['date'].date()})") for x in lines]
    stats["stale_links"] = [{"url": l["url"], "date": l["date"].date().isoformat()} for l in stale]
    stats["undated_links"] = sum(1 for l in uniq if l["fresh"] is None)
    keep = [l for l in uniq if l["fresh"] is not False] if strict else uniq
    cited_urls = {norm_url(u) for u in re.findall(r"https?://[^\s\]\)>,]+", rendered)}
    # cited sources first, then dated-fresh, then undated, then stale
    keep.sort(key=lambda l: (norm_url(l["url"]) not in cited_urls, {True: 0, None: 1, False: 2}[l["fresh"]]))
    lines += ["", "**Sources**", ""]
    for l in keep[:max_links]:
        title = l["title"].replace("[", "(").replace("]", ")").replace("\n", " ")
        tag = "" if l["fresh"] else (" (date unknown)" if l["fresh"] is None else f" (older: {l['date'].date()})")
        lines.append(f"- [{title}]({l['url']}) ({l['source']}){tag}")
    for w in warnings:
        lines.append(f"- _Note from Desearch: {w.get('message') or w}_")
    if strict and stale:
        lines.append(f"- _{len(stale)} older result(s) outside the 24h window were dropped._")
    if not uniq:
        lines.append("- _No links returned._")
    lines.append("")
    return "\n".join(lines), stats


def send_telegram(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set, skipping.", file=sys.stderr)
        return
    # Telegram limit is 4096 chars per message; send in chunks, plain text to avoid Markdown parse errors.
    for i in range(0, len(text), 4000):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text[i:i + 4000],
                                "disable_web_page_preview": "true"}, timeout=30)
        print(f"[telegram] chunk {i // 4000 + 1}: HTTP {r.status_code}", file=sys.stderr)


def redact(obj, secret: str):
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return s.replace(secret, "<REDACTED>") if secret else s


def main() -> int:
    ap = argparse.ArgumentParser(description="Morning Topic Brief (Desearch AI Search)")
    ap.add_argument("--config", default="topics.yaml")
    ap.add_argument("--out", default=None, help="digest output path (default: digests/brief-YYYY-MM-DD.md)")
    ap.add_argument("--sdk", action="store_true", help="use the official desearch-py SDK instead of raw HTTP")
    ap.add_argument("--evidence-dir", default=None, help="save raw request/response JSON here (key redacted)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--replay", default=None, metavar="PREFIX",
                    help="re-render from saved evidence files PREFIX-<topic>.json instead of calling the API (no cost)")
    args = ap.parse_args()

    api_key = os.environ.get("DESEARCH_API_KEY", "").strip()
    if not api_key and not args.replay:
        print("DESEARCH_API_KEY is not set.", file=sys.stderr)
        return 2
    cfg = yaml.safe_load(Path(args.config).read_text())
    topics = cfg["topics"]
    caller = call_sdk if args.sdk else call_http
    run_stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    ev = Path(args.evidence_dir) if args.evidence_dir else None
    if ev:
        ev.mkdir(parents=True, exist_ok=True)

    today = dt.date.today().isoformat()
    parts = [f"# Morning Topic Brief, {today}", "",
             f"_Generated {now_local()} with Desearch AI Search (last 24 hours: web, X, Reddit, Hacker News)._", ""]
    all_stats, total_cost, cost_seen = [], 0.0, False
    for topic in topics:
        payload = build_payload(topic, cfg)
        started = now_local()
        print(f"[{started}] {topic}: calling {'SDK' if args.sdk else 'HTTP'} ...", file=sys.stderr)
        if args.replay:
            resp = json.loads(Path(f"{args.replay}-{slug(topic)}.json").read_text())["response"]
        else:
            resp = caller(payload, api_key, args.timeout)
        section, stats = topic_section(topic, resp, int(cfg.get("max_links", 8)),
                                       bool(cfg.get("drop_stale", True)))
        parts.append(section)
        stats["started"] = started
        all_stats.append(stats)
        if stats["cost_usd"] is not None:
            cost_seen = True
            total_cost += stats["cost_usd"]
        print(f"  -> HTTP {resp['status']} in {resp['latency_s']}s, cost_usd={stats['cost_usd']}", file=sys.stderr)
        if ev and not args.replay:
            rec = {"timestamp": started, "client": "desearch-py SDK" if args.sdk else "requests",
                   "request": {"method": "POST", "url": API_URL,
                               "headers": {"Authorization": "<REDACTED>", "Content-Type": "application/json"},
                               "json": payload},
                   "response": resp}
            (ev / f"{run_stamp}-{'sdk' if args.sdk else 'http'}-{slug(topic)}.json").write_text(redact(rec, api_key))

    cost_line = f"${total_cost:.6f} (from X-Desearch-Cost-Usd)" if cost_seen else "not reported by API"
    parts.append(f"---\nTotal Desearch cost for this brief: {cost_line}\n\nMade by Desearch, https://desearch.ai\n")
    digest = "\n".join(parts)

    out = Path(args.out or f"digests/brief-{today}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(digest)
    print(digest)
    print(f"[done] wrote {out}; total cost: {cost_line}", file=sys.stderr)
    if ev and not args.replay:
        (ev / f"{run_stamp}-{'sdk' if args.sdk else 'http'}-stats.json").write_text(redact(all_stats, api_key))
    if not args.no_telegram:
        send_telegram(digest)
    return 0 if all(s["status"] == 200 for s in all_stats) else 1


if __name__ == "__main__":
    sys.exit(main())
