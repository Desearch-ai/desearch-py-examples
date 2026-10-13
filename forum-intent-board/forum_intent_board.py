"""Forum Intent Board: public HN and Reddit threads Desearch returned for your niche keywords,
flagged for buying / help-seeking intent by plain rules (no model call).

Made by Desearch (https://desearch.ai).

Live:      python forum_intent_board.py keywords.json
Offline:   python forum_intent_board.py --from-raw output/raw-YYYY-MM-DD.json
"""
import argparse, asyncio, csv, datetime as dt, json, os, re, sys, time
from urllib.parse import urlparse

MCP_URL = "https://mcp.desearch.ai/mcp"
SOURCES = ("hackernews", "reddit")

# Intent rules: phrase -> weight. Matched case-insensitively on title + snippet.
INTENT_RULES = [
    (r"\blooking for\b", 3), (r"\balternatives? to\b", 3), (r"\bswitch(ing|ed)? from\b", 3),
    (r"\bany (good )?(tool|app|service)s?\b", 3), (r"\brecommend(ation|ations|ed)?\b", 2),
    (r"\bsuggestions?\b", 2), (r"\bwhich (is|one|tool)\b", 2), (r"\bbest\b.*\?", 2),
    (r"\bhow do (i|you)\b", 2), (r"\bis there an?\b", 2), (r"\bwhat do you use\b", 3),
    (r"\bneed (a|an)\b", 2), (r"\bask hn\b", 1), (r"\bshow hn\b", 1), (r"\?", 1),
]
LOGIN_WALL = re.compile(r"^Welcome to Reddit$|^Log in or sign up to personalize your feed", re.I)
INTENT_MIN = 2  # board threshold: one strong phrase, or two weak signals
USER_RE = re.compile(r"(?<![\w/])(?:/?u/|@)[A-Za-z0-9_-]{2,}")


def now_local():
    return dt.datetime.now().astimezone()


def scrub(text, redact):
    text = USER_RE.sub("[user]", text or "").replace("\u2014", " - ")
    for w in redact:
        text = re.sub(rf"(?i)\b{re.escape(w)}\b", "[redacted]", text)
    return re.sub(r"\s+", " ", text).strip()


def intent(text):
    hits, score = [], 0
    for pat, w in INTENT_RULES:
        if re.search(pat, text, re.I):
            hits.append(re.sub(r"\\b|\(|\)|\?|\\|\.\*|\|.*", "", pat).strip() or "?"); score += w
    return score, hits


def on_topic(keyword, text):
    """Rule: at least half of the keyword's content words (len>=4, simple stem) appear in title+snippet."""
    words = [w[:5] for w in re.findall(r"[a-z0-9-]+", keyword.lower()) if len(w) >= 4]
    t = text.lower()
    got = sum(1 for w in words if w in t)
    return got * 2 >= len(words), f"{got}/{len(words)}"


def thread_id(url):
    u = urlparse(url)
    if "ycombinator.com" in u.netloc:
        m = re.search(r"id=(\d+)", u.query); return ("hn", m.group(1)) if m else (None, None)
    if "reddit.com" in u.netloc:
        m = re.search(r"/comments/([a-z0-9]+)", u.path); return ("reddit", m.group(1)) if m else (None, None)
    return (None, None)


# ---------- live calls ----------
async def run_mcp(keywords, args, key):
    import httpx2  # noqa: F401  (installed with mcp)
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client
    calls = []
    client = create_mcp_http_client(headers={"Authorization": f"Bearer {key}"})
    async with client:
        async with streamable_http_client(MCP_URL, http_client=client) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                for kw in keywords:
                    for src in SOURCES:
                        a = {"prompt": kw, "tools": [src], "result_type": args.result_type}
                        if args.date_filter:
                            a["date_filter"] = args.date_filter
                        t0 = time.time(); at = now_local().isoformat(timespec="seconds")
                        try:
                            res = await s.call_tool("ai-search", a)
                            text = res.content[0].text if res.content else ""
                            err = bool(res.is_error)
                        except Exception as e:  # keep going, log it
                            text, err = f"{type(e).__name__}: {e}", True
                        try:
                            body = json.loads(text)
                        except Exception:
                            body = {"_text": text}
                        c = {"keyword": kw, "source": src, "arguments": a, "at": at, "seconds": round(time.time() - t0, 2),
                             "is_error": err, "cost_usd": body.get("cost_usd"), "usage_count": body.get("usage_count"),
                             "results": body.get("search") or [], "extra_keys": sorted(k for k in body if k != "search")}
                        if err or "_text" in body:
                            c["error_text"] = text[:500]
                        calls.append(c)
                        print(f"{at} ai-search {src:10s} {kw!r}: {len(c['results'])} links, cost {c['cost_usd']}", flush=True)
    return calls


def check_links(urls):
    """GET each thread: HN via the public HN item API (exists, not dead/deleted, posting time);
    Reddit via the thread's public .json (exists, not removed, created time)."""
    import requests
    ua = {"User-Agent": "forum-intent-board/1.0 (link check)"}
    out = {}
    for u in urls:
        kind, tid = thread_id(u)
        r = {"kind": kind, "status": None, "live": False, "created_utc": None, "note": ""}
        try:
            if kind == "hn":
                resp = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{tid}.json", timeout=20)
                r["status"] = resp.status_code; j = resp.json() if resp.ok else None
                if j:
                    r["live"] = not (j.get("dead") or j.get("deleted")); r["created_utc"] = j.get("time")
                    r["note"] = j.get("type", "")
                else:
                    r["note"] = "no item"
            elif kind == "reddit":
                resp = requests.get(f"https://www.reddit.com/comments/{tid}.json?limit=1", headers=ua, timeout=20)
                r["status"] = resp.status_code
                if resp.ok:
                    p = resp.json()[0]["data"]["children"][0]["data"]
                    removed = p.get("removed_by_category")
                    r["live"] = True; r["created_utc"] = p.get("created_utc")
                    r["note"] = f"removed:{removed}" if removed else "ok"
                else:
                    # The HTML page answers 200 with a bot check even for made-up thread ids, so it cannot prove
                    # the thread exists. Record the URL shape check only.
                    r["live"] = None
                    r["note"] = f"unverified (json {resp.status_code}); thread URL well-formed"
            else:
                r["note"] = "not a thread URL"
        except Exception as e:
            r["note"] = f"{type(e).__name__}"
        out[u] = r; time.sleep(0.7 if kind == "reddit" else 0.05)
    return out


# ---------- build ----------
def build(raw, outdir, redact, board_size):
    date = raw["run_date"]; rows, seen = [], {}
    window = raw.get("date_filter_days")
    run_ts = dt.datetime.fromisoformat(raw["run_started"]).timestamp()
    for c in raw["calls"]:
        for rank, it in enumerate(c["results"], 1):
            url = it.get("link", ""); title = it.get("title", ""); snip = it.get("snippet", "")
            title_src = "returned"
            if LOGIN_WALL.search(title) or LOGIN_WALL.search(snip):
                slug = re.search(r"/comments/[a-z0-9]+/([^/?#]+)", url)
                if slug:
                    title, title_src = slug.group(1).replace("_", " "), "url_slug"
                snip = "" if LOGIN_WALL.search(snip) else snip
            text = f"{title} {snip}"
            score, hits = intent(text); ok, ratio = on_topic(c["keyword"], text)
            chk = raw.get("link_checks", {}).get(url, {})
            created = chk.get("created_utc")
            age = round((run_ts - created) / 86400, 1) if created else None
            row = {"keyword": c["keyword"], "source": "hn" if c["source"] == "hackernews" else "reddit", "rank": rank,
                   "title": scrub(title, redact), "title_source": title_src, "url": scrub(url, redact) if redact else url,
                   "snippet": scrub(snip, redact)[:240], "published_date_returned": it.get("published_date") or "",
                   "thread_created_utc": dt.datetime.fromtimestamp(created, dt.timezone.utc).strftime("%Y-%m-%d") if created else "",
                   "age_days": age if age is not None else "",
                   "in_date_filter": ("" if age is None or not window else age <= window),
                   "link_live": "" if chk.get("live") is None else chk.get("live"), "link_check": chk.get("note", ""),
                   "intent_score": score, "intent_flag": score >= INTENT_MIN, "intent_terms": "; ".join(hits),
                   "keyword_match": ratio, "on_topic_rule": ok, "fetched_at": c["at"], "duplicate_of": ""}
            if url in seen:
                row["duplicate_of"] = seen[url]
            else:
                seen[url] = f"{c['keyword']}|{row['source']}"
            rows.append(row)
    os.makedirs(outdir, exist_ok=True)
    cols = list(rows[0].keys()) if rows else ["keyword"]
    with open(os.path.join(outdir, "forum_hits.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader(); wr.writerows(rows)
    with open(os.path.join(outdir, f"{date}-calls.csv"), "w", newline="") as f:
        wr = csv.writer(f); wr.writerow(["at", "keyword", "source", "links", "cost_usd", "usage_count", "seconds", "is_error"])
        for c in raw["calls"]:
            wr.writerow([c["at"], c["keyword"], c["source"], len(c["results"]), c["cost_usd"], c["usage_count"], c["seconds"], c["is_error"]])
    cand = [r for r in rows if not r["duplicate_of"] and r["intent_flag"] and r["on_topic_rule"] and r["link_live"] is not False and r["link_check"] != "not a thread URL"]
    cand.sort(key=lambda r: (-r["intent_score"], r["age_days"] if r["age_days"] != "" else 1e9))
    board = cand[:board_size]
    cost = sum(c["cost_usd"] or 0 for c in raw["calls"])
    n = lambda s: sum(1 for r in rows if r["source"] == s)
    L = [f"# Forum Intent Board, {date}", "", "Made by [Desearch](https://desearch.ai).", "",
         f"Niche: {raw.get('niche','')}. Public HN and Reddit threads Desearch returned for {len(raw['keywords'])} keywords "
         f"on this run (HN {n('hn')} rows, Reddit {n('reddit')} rows, {len(seen)} unique links). Rows below have an intent score of {INTENT_MIN} or more, "
         "match the keyword by the on-topic rule and are thread links (HN threads checked live on the run date). Sorted by intent score, then newest thread first.", "",
         "| # | Score | Source | Keyword | Thread | Thread date (UTC) | Intent terms |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(board, 1):
        t = r["title"].replace("|", "/")[:110]
        L.append(f"| {i} | {r['intent_score']} | {r['source']} | {r['keyword']} | [{t}]({r['url']}) | {r['thread_created_utc'] or 'n/a'} | {r['intent_terms']} |")
    L += ["", f"Board rows: {len(board)} of {len(cand)} candidates. Calls: {len(raw['calls'])}, cost reported by the tool: ${cost:.4f}.",
          "HN thread dates come from the public HN item data, checked on the run date; Reddit rows show no date. Open the thread before you reply: many are older discussions that still rank for the keyword."]
    open(os.path.join(outdir, f"{date}-board.md"), "w").write("\n".join(L) + "\n")
    print(f"rows {len(rows)} (hn {n('hn')}, reddit {n('reddit')}), unique {len(seen)}, board {len(board)}, cost ${cost:.4f}")
    return rows, board


def slim(raw, redact):
    """Public raw: titles, links, snippets (scrubbed); no highlights, no author fields."""
    r = json.loads(json.dumps(raw))
    for c in r["calls"]:
        c["results"] = [{"title": scrub(i.get("title", ""), redact), "link": i.get("link", ""),
                         "snippet": scrub(i.get("snippet", ""), redact)[:240], "published_date": i.get("published_date")} for i in c["results"]]
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="?")
    ap.add_argument("--from-raw")
    ap.add_argument("--date-filter", default="PAST_MONTH", help="ai-search date_filter; '' to omit")
    ap.add_argument("--result-type", default="ONLY_LINKS", choices=["ONLY_LINKS", "LINKS_WITH_FINAL_SUMMARY"])
    ap.add_argument("--no-link-check", action="store_true")
    ap.add_argument("--board-size", type=int, default=20)
    ap.add_argument("--redact-file")
    ap.add_argument("--full-raw", help="private path for unmodified responses")
    ap.add_argument("--out", default="output")
    a = ap.parse_args()
    redact = [w.strip() for w in open(a.redact_file) if w.strip() and not w.startswith("#")] if a.redact_file else []
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        cfg = json.load(open(a.keywords)); kws = cfg["keywords"][:8]
        key = os.environ.get("DESEARCH_API_KEY") or sys.exit("set DESEARCH_API_KEY")
        start = now_local()
        days = {"PAST_24_HOURS": 1, "PAST_2_DAYS": 2, "PAST_WEEK": 7, "PAST_2_WEEKS": 14, "PAST_MONTH": 31,
                "PAST_2_MONTHS": 62, "PAST_YEAR": 366, "PAST_2_YEARS": 731}.get(a.date_filter)
        calls = asyncio.run(run_mcp(kws, a, key))
        raw = {"run_date": start.strftime("%Y-%m-%d"), "run_started": start.isoformat(timespec="seconds"), "niche": cfg.get("niche", ""),
               "keywords": kws, "date_filter": a.date_filter, "date_filter_days": days, "result_type": a.result_type, "calls": calls}
        if a.full_raw:
            json.dump(raw, open(a.full_raw, "w"), indent=1)
        if not a.no_link_check:
            urls = sorted({i.get("link") for c in calls for i in c["results"] if i.get("link")})
            print(f"checking {len(urls)} links ...", flush=True)
            raw["link_checks"] = check_links(urls)
            if a.full_raw:
                json.dump(raw, open(a.full_raw, "w"), indent=1)
        raw = slim(raw, redact)
        os.makedirs(a.out, exist_ok=True)
        json.dump(raw, open(os.path.join(a.out, f"raw-{raw['run_date']}.json"), "w"), indent=1)
    build(raw, a.out, redact, a.board_size)


if __name__ == "__main__":
    main()
