"""AI News Today Board: a once-a-day list of AI posts and pages Desearch returned today, with links.

Made by Desearch (https://desearch.ai).

It runs a fixed query plan (a few AI sub-queries). For each sub-query it asks the Desearch API for
the latest X posts above a like threshold and for web pages from a short list of tech news sites.
It dedupes by URL, tags every item with its sub-query, remembers what it has already shown you
(a seen-URL file), and writes ai-news-YYYY-MM-DD.csv plus a markdown board with the top 15 posts
by engagement and the news pages.

Live:     python ai_news_board.py --key-file ~/.desearch_api_key
Offline:  python ai_news_board.py --from-raw samples/sample-raw.json
Key: read only from a key file (--key-file PATH). Never from the environment.
"""
import argparse, asyncio, csv, datetime as dt, json, os, re, sys, time
from urllib.parse import urlsplit

BASE = "https://api.desearch.ai"
DEFAULT_KEY_FILE = "~/.desearch_api_key"
QUERY_PLAN = {  # tag: search text used for both sources
    "model release": "new AI model release",
    "open source llm": "open source LLM",
    "ai funding": "AI startup funding round",
    "ai regulation": "AI regulation",
    "ai agents": "AI agents launch",
}
NEWS_SITES = ["techcrunch.com", "theverge.com", "venturebeat.com", "wired.com", "arstechnica.com"]
AI_TERMS = re.compile(r"\b(ai|a\.i\.|llms?|gpt\w*|models?|openai|anthropic|claude|gemini|llama|mistral|deepseek|agents?|"
                      r"chatbots?|neural|machine learning|genai|generative|artificial intelligence|inference|"
                      r"open[- ]source|regulat\w*|funding|startup)\b", re.I)
MENTION = re.compile(r"(?<![\w/])@\w{1,15}")
FIELDS = ["date", "source", "tag", "title_or_text", "url", "site", "published_utc", "age_hours", "likes", "reposts", "replies",
          "engagement", "new_today", "on_topic"]
TOP_N = 15


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read_key(path):
    p = os.path.expanduser(path)
    if not os.path.isfile(p):
        raise SystemExit(f"key file not found: {p} (put your Desearch API key in it, one line)")
    k = open(p).read().strip()
    if not k:
        raise SystemExit(f"key file is empty: {p}")
    return k


# ---------- live calls ----------
async def x_call(client, tag, query, count, min_likes):
    """GET /twitter through the desearch-py SDK (x_search). Yes/no filters are not passed."""
    at, t0 = now(), time.time()
    params = {"query": query, "sort": "Latest", "count": count, "min_likes": str(min_likes)}
    try:
        res = await client.x_search(query=query, sort="Latest", count=count, min_likes=str(min_likes), include_metadata=True)
        data, meta = res.data, res.metadata
        body = [d.model_dump(mode="json") if hasattr(d, "model_dump") else d for d in (data if isinstance(data, list) else [data])]
        if isinstance(data, dict): body = data
        status = 200
        cost = getattr(meta, "cost_usd", None) if meta else None
        meta_d = meta.model_dump(mode="json") if hasattr(meta, "model_dump") else (vars(meta) if meta else {})
    except Exception as e:
        status = getattr(e, "status", None); body = {"_error": repr(e)[:500]}; cost = None; meta_d = {}
    rec = {"source": "x", "tag": tag, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": cost, "meta": meta_d, "body": body}
    log(rec, len(body) if isinstance(body, list) else 0)
    return rec


def web_call(session, tag, query, count, sites):
    """POST /desearch/ai/search with tools ["web"] and include_domains, over REST (the SDK has no include_domains)."""
    at, t0 = now(), time.time()
    payload = {"prompt": query, "tools": ["web"], "include_domains": sites, "count": count, "streaming": False,
               "result_type": "ONLY_LINKS", "date_filter": "PAST_24_HOURS"}
    try:
        r = session.post(BASE + "/desearch/ai/search", json=payload, timeout=120)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: body = r.json()
        except ValueError: body = {"_text": r.text[:3000]}
    except Exception as e:
        status, hdr, body = None, {}, {"_error": repr(e)[:500]}
    rec = {"source": "web", "tag": tag, "params": payload, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"),
           "meta": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k == "date"}, "body": body}
    log(rec, len(web_items(rec)))
    return rec


def log(rec, n):
    print(f"{rec['at']} {rec['source']:4s} {rec['tag']:16s} {rec['status']} {rec['seconds']:6.2f}s items={n} cost={rec['cost_usd']}",
          file=sys.stderr, flush=True)


def live(args):
    import requests
    from desearch_py import Desearch
    key = read_key(args.key_file)
    raw = {"started": now(), "min_likes": args.min_likes, "sites": args.sites, "calls": []}
    s = requests.Session(); s.headers["Authorization"] = key

    async def xs():
        client = Desearch(api_key=key)
        try:
            return [await x_call(client, t, q, args.count, args.min_likes) for t, q in QUERY_PLAN.items()]
        finally:
            await client.close()
    raw["calls"] += asyncio.run(xs())
    for t, q in QUERY_PLAN.items():
        raw["calls"].append(web_call(s, t, q, args.web_count, args.sites))
    return raw


# ---------- parsing ----------
def web_items(rec):
    b = rec.get("body")
    if isinstance(b, dict):
        for k in ("search", "web_search", "web", "results", "data"):
            v = b.get(k)
            if isinstance(v, list): return v
            if isinstance(v, dict) and isinstance(v.get("organic_results"), list): return v["organic_results"]
    return b if isinstance(b, list) else []


def norm_url(u):
    u = (u or "").strip()
    m = re.match(r"https?://(?:www\.)?(?:x|twitter)\.com/[^/]+/status/(\d+)", u)
    if m: return f"https://x.com/i/status/{m.group(1)}"
    p = urlsplit(u)
    return f"{p.scheme}://{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}" if p.netloc else u


def site_of(u):
    return urlsplit(u).netloc.lower().removeprefix("www.")


def on_site(site, sites):
    return any(site == d or site.endswith("." + d) for d in sites)


def tweet_time(v):
    t = parse_any(v) if v else None
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M") if t else (v or "")


def num(v):
    return v if isinstance(v, int) and v >= 0 else 0


def parse_any(v):
    for f in ("%a %b %d %H:%M:%S %z %Y",):
        try: return dt.datetime.strptime(v, f)
        except (TypeError, ValueError): pass
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def page_date(w, u):
    """Use published_date when the result has one; otherwise many news URLs carry /YYYY/MM/DD/."""
    v = w.get("published_date")
    if v:
        t = parse_any(str(v)[:10])
        if t: return t
    return url_date(u)


def url_date(u):
    m = re.search(r"/(20\d\d)/(\d\d)/(\d\d)/", u or "")
    if m:
        try: return dt.datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=dt.timezone.utc)
        except ValueError: return None
    return None


def build(raw, out_dir, seen_file=None, update_seen=False, max_age_hours=24, page_days=7):
    day = (raw.get("started") or now())[:10]
    ref = parse_any(raw.get("started")) or dt.datetime.now(dt.timezone.utc)
    seen = set()
    if seen_file and os.path.isfile(seen_file):
        seen = {l.strip() for l in open(seen_file) if l.strip()}
    sites = raw.get("sites") or NEWS_SITES
    rows, by_url, stats = [], {}, {"x_returned": 0, "x_below_min_likes": 0, "x_skipped_mentions": 0, "web_returned": 0,
                                   "web_off_list": 0, "x_too_old": 0, "x_link_only": 0, "web_too_old": 0, "web_undated": 0, "duplicates": 0, "calls": 0, "cost_usd": 0.0}
    for rec in raw["calls"]:
        if rec.get("probe"): continue
        stats["calls"] += 1
        try: stats["cost_usd"] += float(rec.get("cost_usd") or 0)
        except ValueError: pass
        if rec["source"] == "x":
            items = rec["body"] if isinstance(rec["body"], list) else []
            stats["x_returned"] += len(items)
            for t in items:
                text = t.get("text") or ""
                likes = num(t.get("like_count"))
                if likes < raw.get("min_likes", 0): stats["x_below_min_likes"] += 1; continue
                t0 = parse_any(t.get("created_at"))
                age = round((ref - t0).total_seconds() / 3600, 1) if t0 else None
                if age is not None and age > max_age_hours: stats["x_too_old"] += 1; continue
                if not re.sub(r"https?://\S+", "", text).strip(): stats["x_link_only"] += 1; continue
                if MENTION.search(text): stats["x_skipped_mentions"] += 1; continue  # keep quotes unedited and handle-free
                url = f"https://x.com/i/status/{t.get('id')}" if t.get("id") else norm_url(t.get("url"))
                rp, rq = num(t.get("retweet_count")), num(t.get("reply_count"))
                row = {"date": day, "source": "X post", "tag": rec["tag"], "title_or_text": text,
                       "url": url, "site": "x.com", "published_utc": tweet_time(t.get("created_at")), "age_hours": age, "likes": likes,
                       "reposts": rp, "replies": rq, "engagement": likes + rp + rq}
                add(row, by_url, rows, stats, seen)
        else:
            items = web_items(rec)
            stats["web_returned"] += len(items)
            for w in items:
                url = norm_url(w.get("link") or w.get("url"))
                st = site_of(url)
                if not on_site(st, sites): stats["web_off_list"] += 1
                d = page_date(w, url)
                age = round((ref - d).total_seconds() / 3600) if d else None
                if d is None: stats["web_undated"] += 1
                elif age > page_days * 24: stats["web_too_old"] += 1; continue
                row = {"date": day, "source": "web page", "tag": rec["tag"], "title_or_text": (w.get("title") or "").strip(),
                       "url": w.get("link") or w.get("url") or "", "site": st, "published_utc": d.strftime("%Y-%m-%d") if d else (w.get("date") or ""), "age_hours": age,
                       "likes": "", "reposts": "", "replies": "", "engagement": ""}
                row["_key"] = url
                add(row, by_url, rows, stats, seen)
    for r in rows:
        r["on_topic"] = bool(AI_TERMS.search(r["title_or_text"]))
    stats["cost_usd"] = round(stats["cost_usd"], 5)
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f"ai-news-{day}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    posts = sorted([r for r in rows if r["source"] == "X post"], key=lambda r: r["engagement"], reverse=True)[:TOP_N]
    pages = sorted([r for r in rows if r["source"] == "web page"], key=lambda r: r["published_utc"] or "0", reverse=True)
    md = [f"# AI News Today Board, {day}", "",
          f"AI posts and pages Desearch returned for this run ({raw.get('started')}), from {len(QUERY_PLAN)} fixed sub-queries. "
          f"X posts are the latest ones with at least {raw.get('min_likes')} likes from the last {max_age_hours} hours; "
          f"pages come from a short list of tech news sites, dated in the last {page_days} days (or undated). "
          "Text is quoted in full as returned (line breaks shown as spaces here; the CSV keeps them). Authors are shown as \"a user\". \"new\" means not in your seen-URL file.", "",
          f"## Top {len(posts)} posts by engagement (likes + reposts + replies)", ""]
    for i, r in enumerate(posts, 1):
        md.append(f"{i}. [{r['tag']}] a user: \"{' '.join(r['title_or_text'].split())}\" ({r['engagement']} engagements, "
                  f"{r['published_utc']} UTC){' new' if r['new_today'] else ''} {r['url']}")
    md += ["", f"## News pages ({len(pages)})", ""]
    for r in pages:
        md.append(f"- [{r['tag']}] {r['title_or_text'] or '(no title)'} ({r['site']}, {r['published_utc'] or 'no date'}){' new' if r['new_today'] else ''} {r['url']}")
    md += ["", "## Run", "", f"- calls: {stats['calls']}",
           f"- X posts returned: {stats['x_returned']}, below the like threshold: {stats['x_below_min_likes']}, "
           f"older than {max_age_hours} h: {stats['x_too_old']}, link only: {stats['x_link_only']}, "
           f"left out because they mention an account: {stats['x_skipped_mentions']}",
           f"- web pages returned: {stats['web_returned']}, outside the site list: {stats['web_off_list']}, "
           f"older than {page_days} days: {stats['web_too_old']}, no date: {stats['web_undated']}",
           f"- duplicates removed: {stats['duplicates']}, items on the board: {len(rows)}, "
           f"new: {sum(r['new_today'] for r in rows)}, on topic by keyword check: {sum(r['on_topic'] for r in rows)}"]
    md_path = os.path.join(out_dir, f"ai-news-{day}.md")
    with open(md_path, "w", encoding="utf-8") as fh: fh.write("\n".join(md) + "\n")
    if seen_file and update_seen:
        with open(seen_file, "a") as fh:
            for r in rows:
                if r["new_today"]: fh.write(r.get("_key", r["url"]) + "\n")
    return rows, stats, csv_path, md_path


def add(row, by_url, rows, stats, seen):
    key = row.get("_key") or row["url"]
    row["_key"] = key
    if key in by_url:
        stats["duplicates"] += 1
        prev = by_url[key]
        if row["tag"] not in prev["tag"].split("; "): prev["tag"] += "; " + row["tag"]
        return
    row["new_today"] = key not in seen
    by_url[key] = row; rows.append(row)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=30, help="X posts per sub-query (1 to 100)")
    ap.add_argument("--min-likes", type=int, default=20, help="minimum likes for X posts")
    ap.add_argument("--web-count", type=int, default=10, help="web results per sub-query (10 to 200)")
    ap.add_argument("--sites", nargs="+", default=NEWS_SITES, help="news sites for the web search")
    ap.add_argument("--max-age-hours", type=int, default=24, help="keep X posts from the last N hours")
    ap.add_argument("--page-days", type=int, default=7, help="keep pages dated within N days (undated pages are kept)")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--from-raw", help="rebuild the board from a saved raw JSON, no API calls")
    ap.add_argument("--raw-out", help="where to save the raw responses (default <out>/raw-<date>.json)")
    ap.add_argument("--seen-file", default="seen-urls.txt", help="URLs already shown; new ones are added after a live run")
    ap.add_argument("--out", default="output", help="output folder")
    a = ap.parse_args(argv)
    if a.from_raw:
        raw = json.load(open(a.from_raw)); update = False
    else:
        a.count = max(1, min(a.count, 100)); a.web_count = max(10, min(a.web_count, 200))
        raw = live(a); update = True
        os.makedirs(a.out, exist_ok=True)
        rp = a.raw_out or os.path.join(a.out, f"raw-{raw['started'][:10]}.json")
        json.dump(raw, open(rp, "w"), indent=1, ensure_ascii=False)
        print(f"raw saved: {rp}", file=sys.stderr)
    rows, stats, c, m = build(raw, a.out, a.seen_file, update_seen=update, max_age_hours=a.max_age_hours, page_days=a.page_days)
    print(f"{len(rows)} items, {stats['calls']} calls, ${stats['cost_usd']} by headers -> {c}, {m}")


if __name__ == "__main__":
    main()
