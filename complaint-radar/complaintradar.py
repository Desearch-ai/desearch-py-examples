#!/usr/bin/env python3
"""Complaint Radar: recent public X posts that pair a brand with complaint words, grouped into themes.

Searches X through the Desearch API one UTC day at a time, drops duplicates, sorts posts into
complaint themes with keyword rules, and writes a Markdown radar, a JSON snapshot and a cost line.

Endpoints (base https://api.desearch.ai, header Authorization: <key>):
  GET /twitter?query=&sort=Latest&start_date=<day>T00:00:00Z&end_date=<next day>T00:00:00Z&count=
      one call per UTC day; if a page comes back full, the next page adds max_id:<oldest id - 1> to the query
  GET /twitter/replies/post?post_id=&count=      optional: a sample of replies under the top posts
"""
import argparse, collections, datetime as dt, email.utils, json, os, re, statistics, sys, time

BASE = "https://api.desearch.ai"

DEFAULT_KEYWORDS = ["not working", "is down", "outage", "broken", "bug", "glitch", "crashing", "refund", "charged",
                    "customer service", "can't log in", "won't load"]

# Theme rules, checked in this order; the first theme with a matching pattern wins.
THEMES = [
    ("outage", [r"\b(?:is|was|went|goes|still) down\b", r"\bdown (?:again|for|right now|today)\b", r"\boutage",
                r"not (?:loading|working|opening|connecting)", r"\bwon'?t (?:load|open|connect|play)",
                r"\bcan'?t (?:connect|load|access)", r"\bservers? (?:are |is )?(?:down|issues?|problems?|errors?)", r"\bis it (?:just )?me\b", r"\bunavailable\b"]),
    ("account", [r"\bcan'?t (?:log|sign) ?in\b", r"\blogged (?:me )?out\b", r"\bpassword\b", r"\bhacked\b",
                 r"\blocked out\b", r"\bbanned\b", r"\bsuspended\b"]),
    ("billing", [r"\brefund", r"\bcharg(?:e|ed|es|ing)\b", r"\bbill(?:ed|ing)\b", r"\bsubscription", r"\bcancel",
                 r"\bpayment", r"\bprice (?:hike|increase)", r"\bpaid\b", r"\bmy money\b"]),
    ("bug", [r"\bbug", r"\bbroken\b", r"\bglitch", r"\berror", r"\bcrash(?:ing|es|ed)\b", r"\bkeeps? crashing\b", r"\bfreez",
             r"\bkeeps? (?:skipping|stopping|closing|pausing)", r"\bstopped working\b", r"\bdoesn'?t work\b", r"\bnot work"]),
    ("support", [r"\bcustomer (?:support|service|care)\b", r"\bsupport (?:team|is|has|never|won'?t|didn'?t)\b",
                 r"\bcontacted support\b", r"\bno (?:reply|response)\b", r"\bticket\b", r"\blive chat\b"]),
    ("feature request", [r"\bplease add\b", r"\bbring back\b", r"\bfeature request\b", r"\bi wish\b",
                         r"\bwhy (?:can'?t|isn'?t|doesn'?t) (?:i|it|you)\b"]),
]
# Phrases that use complaint words in a non-complaint sense; removed before theme matching.
IDIOMS = re.compile(r"\b(?:has |have |just )?broken (?:the|a|another|records?|barrier|heart|hearts)\b|\bbroke the\b|"
                    r"\brecord[- ]broken\b|\bbroken english\b|\bbug ?fix(?:es|ed)?\b|\bbugs? squashed\b", re.I)
COMPILED = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in THEMES]


# ---------------------------------------------------------------- pure logic

def parse_time(s):
    """X created_at ('Thu Oct 08 04:15:08 +0000 2026') or ISO -> aware UTC datetime, or None."""
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError:
            return None


def _term(s):
    s = s.strip()
    return f'"{s}"' if " " in s and not s.startswith('"') else s


def build_query(brand, aliases=(), keywords=DEFAULT_KEYWORDS, handle=None, exclude=()):
    """'(Brand OR alias) (kw1 OR "two words") -from:handle -noise'. X search operators go in `query`."""
    names = [brand] + [a for a in aliases if a]
    left = _term(names[0]) if len(names) == 1 else "(" + " OR ".join(_term(n) for n in names) + ")"
    q = left
    if keywords:
        q += " (" + " OR ".join(_term(k) for k in keywords) + ")"
    if handle:
        q += " -from:" + handle.lstrip("@")
    for w in exclude or ():
        if w.strip():
            q += " -" + _term(w)
    return q


def day_windows(days, now=None):
    """UTC day windows, oldest first: [(day, start_iso, end_iso)], the last one is today."""
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - dt.timedelta(days=i)
        n = d + dt.timedelta(days=1)
        out.append((d.isoformat(), f"{d.isoformat()}T00:00:00Z", f"{n.isoformat()}T00:00:00Z"))
    return out


def next_page_query(query, items):
    """Query for the next older page: adds max_id:<oldest id - 1>. None if no ids."""
    ids = [int(t["id"]) for t in items if str(t.get("id", "")).isdigit()]
    if not ids:
        return None
    base = re.sub(r"\s*max_id:\d+", "", query)
    return f"{base} max_id:{min(ids) - 1}"


def norm_text(text):
    """Text used to spot copy-paste duplicates: no mentions, links, punctuation or case."""
    t = re.sub(r"https?://\S+|@\w+", " ", (text or "").lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def dedupe(tweets):
    """Drop repeated ids and repeated texts (keeps the first, which is the newest in a Latest list).
    Returns (kept, dropped_ids, dropped_texts)."""
    seen_id, seen_txt, out = set(), set(), []
    d_id = d_txt = 0
    for t in tweets:
        i = str(t.get("id"))
        if i in seen_id:
            d_id += 1
            continue
        seen_id.add(i)
        n = norm_text(t.get("text"))
        if n and len(n) > 20 and n in seen_txt:
            d_txt += 1
            continue
        seen_txt.add(n)
        out.append(t)
    return out, d_id, d_txt


def keep_post(t, brand_handle=None):
    """Drop reposts and the brand's own posts."""
    if t.get("is_retweet"):
        return False
    if brand_handle and ((t.get("user") or {}).get("username") or "").lower() == brand_handle.lstrip("@").lower():
        return False
    return True


def theme_of(text):
    """(theme, matched pattern text) by the first matching rule, else ('other', '')."""
    text = IDIOMS.sub(" ", text or "")
    for name, pats in COMPILED:
        for p in pats:
            m = p.search(text or "")
            if m:
                return name, m.group(0).lower()
    return "other", ""


def engagement(t):
    g = lambda k: int(t.get(k) or 0)
    return g("like_count") + 2 * g("reply_count") + g("retweet_count") + g("quote_count") + g("bookmark_count")


def volume_by_day(rows):
    """{day: Counter(theme)} using created_at in UTC."""
    out = collections.defaultdict(collections.Counter)
    for r in rows:
        out[r["day"]][r["theme"]] += 1
    return dict(sorted(out.items()))


def fill_rates(tweets, fields=("created_at", "text", "url", "like_count", "reply_count", "retweet_count",
                               "quote_count", "bookmark_count", "view_count", "lang", "conversation_id")):
    n = len(tweets)
    return {f: (sum(1 for t in tweets if t.get(f) not in (None, "")), n) for f in fields}


def to_row(t):
    d = parse_time(t.get("created_at"))
    theme, hit = theme_of(t.get("text"))
    u = t.get("user") or {}
    return {"id": str(t.get("id")), "url": t.get("url"), "author": u.get("username"), "followers": u.get("followers_count"),
            "created_at": d.isoformat() if d else None, "day": d.date().isoformat() if d else "unknown",
            "theme": theme, "matched": hit, "score": engagement(t), "likes": t.get("like_count"),
            "replies": t.get("reply_count"), "reposts": t.get("retweet_count"), "views": t.get("view_count"),
            "lang": t.get("lang"), "is_reply": bool(t.get("in_reply_to_status_id") or t.get("in_reply_to_screen_name")),
            "text": t.get("text") or ""}


def top_complaints(rows, n, with_replies=False):
    """Highest-scoring posts that matched a complaint theme ('other' is left out).
    with_replies: only posts whose reply_count is above 0 (used to pick posts for the replies sample)."""
    rs = [r for r in rows if r["theme"] != "other" and (not with_replies or (r.get("replies") or 0) > 0)]
    return sorted(rs, key=lambda r: (-r["score"], r["id"]))[:n]


def short(s, n=160):
    s = re.sub(r"\s+", " ", s or "").strip().replace("|", "/")
    return s if len(s) <= n else s[: n - 3] + "..."


def render(meta, rows, by_day, calls, fills, top_n=10, replies=None, coverage=None):
    themes = collections.Counter(r["theme"] for r in rows)
    names = [n for n, _ in THEMES] + ["other"]
    L = [f"# Complaint Radar: {meta['brand']}", "",
         f"Generated {meta['generated']} (Asia/Tbilisi). Window: {meta['days']} UTC days, {meta['window'][0]} to {meta['window'][1]}. "
         f"Public posts from X search (`sort=Latest`), reposts{' and @' + meta['handle'] + ' posts' if meta.get('handle') else ''} removed.", "",
         f"Query: `{meta['query']}`" + (f", `lang={meta['lang']}`" if meta.get("lang") else ""), "",
         f"Posts: {len(rows)} after removing {meta['dropped_ids']} repeated ids and {meta['dropped_texts']} repeated texts.", "",
         "## Themes", "", "| Theme | Posts | Share | Median score | Most common match |", "|---|---|---|---|---|"]
    for n in names:
        rs = [r for r in rows if r["theme"] == n]
        if not rs:
            continue
        mc = collections.Counter(r["matched"] for r in rs if r["matched"]).most_common(1)
        L.append(f"| {n} | {len(rs)} | {100 * len(rs) / len(rows):.0f}% | {statistics.median(r['score'] for r in rs):g} | {mc[0][0] if mc else ''} |")
    coverage = coverage or {}
    L += ["", "## Volume by day (UTC)", "", "Each UTC day is searched newest first. When a day hits the page cap, it covers only the latest part of that day (see 'Covered from').", "",
          "| Day | Total | " + " | ".join(names) + " | Pages | Covered from (UTC) |", "|---|---|" + "---|" * len(names) + "---|---|"]
    for d in sorted(set(by_day) | set(coverage)):
        c = by_day.get(d, collections.Counter())
        cv = coverage.get(d, {})
        frm = ((cv.get("oldest") or "")[11:16] + (" (page cap)" if cv.get("capped") else " (whole day)")) if cv.get("oldest") else ""
        L.append(f"| {d} | {sum(c.values())} | " + " | ".join(str(c.get(n, 0)) for n in names) + f" | {cv.get('pages', '')} | {frm} |")
    L += ["", f"## Top {top_n} complaint posts by engagement", "", "Score = likes + 2 x replies + reposts + quotes + bookmarks. Posts in 'other' are counted above but not ranked here.", "",
          "| # | Theme | Score | Likes | Replies | Views | Author | Posted (UTC) | Post |", "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(top_complaints(rows, top_n), 1):
        L.append(f"| {i} | {r['theme']} | {r['score']} | {r['likes']} | {r['replies']} | {r['views'] if r['views'] is not None else ''} | "
                 f"@{r['author']} | {(r['created_at'] or '')[:16].replace('T', ' ')} | [{short(r['text'], 110)}]({r['url']}) |")
    for n in names:
        rs = sorted([r for r in rows if r["theme"] == n], key=lambda r: -r["score"])[:3]
        if rs and n != "other":
            L += ["", f"### {n}: loudest", ""] + [f"- [{short(r['text'])}]({r['url']}) (@{r['author']}, score {r['score']})" for r in rs]
    if replies:
        L += ["", "## A sample of replies under the top posts", ""]
        for pid, rs in replies.items():
            L.append(f"- [Post {pid}](https://x.com/i/status/{pid}): {len(rs)} replies in the sample")
            for t in rs[:3]:
                L.append(f"  - @{(t.get('user') or {}).get('username')}: {short(t.get('text'), 120)}")
    L += ["", "## Field fill rates", "", "| Field | Filled |", "|---|---|"] + [f"| `{k}` | {a}/{n} |" for k, (a, n) in fills.items()]
    ok = [c for c in calls if c["status"] == 200]
    cost = sum(c["cost_usd"] or 0 for c in calls)
    units = sum(c["units"] or 0 for c in calls)
    L += ["", "## Cost", "", f"{len(calls)} Desearch calls ({len(ok)} returned 200), {units} billed units, ${cost:.5f} "
          "(sum of the `X-Desearch-Cost-Usd` response headers)."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- API

def load_key():
    k = os.environ.get("DESEARCH_API_KEY")
    if not k and os.environ.get("DESEARCH_API_KEY_FILE"):
        k = open(os.environ["DESEARCH_API_KEY_FILE"]).read().strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY (or DESEARCH_API_KEY_FILE).")
    return k


class Client:
    def __init__(self, key, raw_dir=None, max_spend=0.10):
        import requests
        self.s = requests.Session()
        self.s.headers["Authorization"] = key
        self.key, self.raw_dir, self.max_spend, self.calls = key, raw_dir, max_spend, []

    def spent(self):
        return sum(c["cost_usd"] or 0 for c in self.calls)

    def get(self, path, params, label):
        if self.spent() >= self.max_spend:
            print(f"spend cap ${self.max_spend} reached, skipping {label}", file=sys.stderr)
            return None
        for attempt in (1, 2):
            when = time.strftime("%Y-%m-%d %H:%M:%S %z")
            t0 = time.perf_counter()
            try:
                r = self.s.get(BASE + path, params=params, timeout=120)
                status, hdr, text = r.status_code, r.headers, r.text
            except Exception as e:  # network error
                status, hdr, text = None, {}, str(e)
            lat = round(time.perf_counter() - t0, 2)
            try:
                body = json.loads(text)
            except ValueError:
                body = {"_raw_text": text[:2000]}
            items = body if isinstance(body, list) else []
            c = {"when": when, "label": label, "path": path, "params": params, "status": status, "latency_s": lat,
                 "items": len(items), "units": int(hdr.get("X-Desearch-Usage-Count") or 0) or None,
                 "cost_usd": float(hdr.get("X-Desearch-Cost-Usd") or 0), "attempt": attempt}
            self.calls.append(c)
            print(f"[{when}] {status} {path} {json.dumps(params)} items={c['items']} units={c['units']} "
                  f"cost=${c['cost_usd']:.5f} {lat}s", file=sys.stderr)
            if self.raw_dir:
                s = json.dumps({"call": c, "request": {"url": BASE + path, "params": params, "headers": {"Authorization": "<redacted>"}},
                                "response": body}, ensure_ascii=False, indent=1)
                assert self.key not in s
                open(os.path.join(self.raw_dir, f"{len(self.calls):03d}-{label}.json"), "w").write(s)
            if status == 200:
                return body
            if status in (429, 500, 502, 503, 504, None) and attempt == 1:
                time.sleep(2)
                continue
            return None


def collect(cl, query, windows, per_page, pages_per_day, lang=None):
    """One search per UTC day window, paging older inside a day with max_id while pages come back full.
    Returns (tweets, coverage) where coverage[day] = {"pages", "fetched", "oldest", "capped"}."""
    allt, cov = [], {}
    for day, start, end in windows:
        q = query
        for page in range(1, pages_per_day + 1):
            p = {"query": q, "sort": "Latest", "start_date": start, "end_date": end, "count": per_page}
            if lang:
                p["lang"] = lang
            body = cl.get("/twitter", p, f"search-{day}-p{page}")
            items = body if isinstance(body, list) else []
            allt += items
            c = cov.setdefault(day, {"pages": 0, "fetched": 0, "oldest": None, "capped": False})
            c["pages"] += 1
            c["fetched"] += len(items)
            ts = [parse_time(t.get("created_at")) for t in items]
            ts = [x for x in ts if x]
            if ts:
                o = min(ts).isoformat()
                c["oldest"] = o if not c["oldest"] else min(o, c["oldest"])
            if len(items) < per_page:
                break
            if page == pages_per_day:
                c["capped"] = True
            q = next_page_query(query, items)
            if not q:
                break
    return allt, cov


def main(argv=None):
    ap = argparse.ArgumentParser(description="Complaint Radar: recent public X complaints about a brand, grouped into themes.")
    ap.add_argument("brand")
    ap.add_argument("--handle", help="brand's own X handle; its posts are excluded")
    ap.add_argument("--alias", action="append", default=[], help="other names for the brand (repeatable)")
    ap.add_argument("--keywords", help="comma-separated complaint words (default: %s)" % ",".join(DEFAULT_KEYWORDS))
    ap.add_argument("--exclude", help="comma-separated words to leave out of the search, e.g. off-topic noise")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--lang")
    ap.add_argument("--per-page", type=int, default=20)
    ap.add_argument("--pages-per-day", type=int, default=3)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--replies", type=int, default=0, help="pull a sample of replies under the top N posts")
    ap.add_argument("--max-spend", type=float, default=0.10)
    ap.add_argument("--out", default="runs")
    ap.add_argument("--no-raw", action="store_true")
    a = ap.parse_args(argv)

    kws = [k.strip() for k in a.keywords.split(",")] if a.keywords else DEFAULT_KEYWORDS
    exc = [w.strip() for w in a.exclude.split(",")] if a.exclude else []
    query = build_query(a.brand, a.alias, kws, a.handle, exc)
    windows = day_windows(a.days)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(a.out, f"{stamp}-{re.sub(r'[^a-z0-9]+', '-', a.brand.lower()).strip('-')}")
    raw = None if a.no_raw else os.path.join(out, "raw")
    os.makedirs(raw or out, exist_ok=True)
    cl = Client(load_key(), raw, a.max_spend)

    tweets, cov = collect(cl, query, windows, a.per_page, a.pages_per_day, a.lang)
    tweets = [t for t in tweets if keep_post(t, a.handle)]
    kept, d_id, d_txt = dedupe(sorted(tweets, key=lambda t: parse_time(t.get("created_at")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True))
    lo = dt.datetime.fromisoformat(windows[0][1].replace("Z", "+00:00"))
    kept = [t for t in kept if (parse_time(t.get("created_at")) or lo) >= lo]
    rows = [to_row(t) for t in kept]

    replies = {}
    for r in top_complaints(rows, a.replies, with_replies=True):
        body = cl.get("/twitter/replies/post", {"post_id": r["id"], "count": 20}, f"replies-{r['id']}")
        replies[r["id"]] = body if isinstance(body, list) else []

    meta = {"brand": a.brand, "handle": a.handle, "query": query, "lang": a.lang, "days": a.days,
            "window": (windows[0][1], windows[-1][2]), "generated": time.strftime("%Y-%m-%d %H:%M"),
            "dropped_ids": d_id, "dropped_texts": d_txt}
    fills = fill_rates(kept)
    md = render(meta, rows, volume_by_day(rows), cl.calls, fills, a.top, replies, cov)
    open(os.path.join(out, "radar.md"), "w").write(md)
    snap = {"meta": meta, "themes": dict(collections.Counter(r["theme"] for r in rows)), "posts": rows,
            "replies_sample": {k: [{"id": t.get("id"), "author": (t.get("user") or {}).get("username"), "text": t.get("text"),
                                    "created_at": t.get("created_at")} for t in v] for k, v in replies.items()},
            "fill_rates": fills, "coverage": cov, "calls": cl.calls,
            "cost": {"calls": len(cl.calls), "units": sum(c["units"] or 0 for c in cl.calls), "usd": round(cl.spent(), 6)}}
    json.dump(snap, open(os.path.join(out, "snapshot.json"), "w"), indent=1, ensure_ascii=False)
    print(f"{len(rows)} posts, {snap['cost']['calls']} calls, {snap['cost']['units']} units, ${snap['cost']['usd']:.5f} -> {out}/radar.md")
    return out


if __name__ == "__main__":
    main()
