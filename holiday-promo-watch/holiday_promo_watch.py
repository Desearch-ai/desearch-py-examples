#!/usr/bin/env python3
"""Holiday Promo Watch: a dated snapshot of promo wording for a few brands, across their homepage, sale pages,
latest X, Instagram and TikTok posts, and a "<brand> black friday 2026" search. Each run appends rows to
output/promo_timeline.csv, so daily re-runs show which brand moved first, on which channel, with what wording.

Made by Desearch (https://desearch.ai)

Usage:
    export DESEARCH_API_KEY=...                       # your key from console.desearch.ai
    python holiday_promo_watch.py brands.json         # live run (one snapshot), appends to output/promo_timeline.csv
    python holiday_promo_watch.py --from-raw output/raw-2026-10-11.json   # offline rebuild, no API calls, no cost
"""
import argparse, csv, datetime as dt, json, os, re, sys, time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

BASE = "https://api.desearch.ai"
TB = ZoneInfo("Asia/Tbilisi")
HEADERS = ("X-Desearch-Cost-Usd", "X-Desearch-Usage-Count", "X-Desearch-Service", "X-Desearch-Currency")
CHANNELS = ("site_home", "site_sale", "site_bf_page", "x_posts", "instagram", "tiktok", "x_search", "serp_brand")
POST_CHANNELS = ("x_posts", "instagram", "tiktok")

# Promo wording. "strong" terms point at an offer; "weak" terms also show up in navigation and everyday copy.
STRONG = [("black friday", r"black[\s-]*friday"), ("cyber monday", r"cyber[\s-]*monday"), ("bfcm", r"\bbfcm\b"),
          ("cyber week", r"cyber[\s-]*week"), ("early access", r"early[\s-]*access"),
          ("% off", r"\b\d{1,2}\s?%\s?off\b"), ("up to N%", r"\bup to \d{1,2}\s?%"),
          ("code", r"\b(?:use|promo|discount|with)\s+code\b"), ("sitewide", r"\bsite[\s-]?wide\b")]
WEAK = [("sale", r"\bsales?\b"), ("deal", r"\bdeals?\b"), ("discount", r"\bdiscount(?:s|ed)?\b"),
        ("save", r"\bsave\s+(?:up\s+to\s+)?\$?\d+"), ("offer", r"\boffers?\b"), ("markdown", r"\bmarkdowns?\b"),
        ("clearance", r"\bclearance\b"), ("limited time", r"\blimited[\s-]time\b")]
YEAR = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
MENTION = re.compile(r"@[A-Za-z0-9_.]{2,30}")


def now_tb():
    return dt.datetime.now(TB)


def promo_terms(text):
    t = (text or "").lower()
    strong = [n for n, p in STRONG if re.search(p, t)]
    weak = [n for n, p in WEAK if re.search(p, t)]
    return strong, weak


def strength(strong, weak):
    return "strong" if strong else ("weak" if weak else "none")


def scrub(text, own=()):
    """Replace @mentions with @user unless they are one of the brand's own handles."""
    own_l = {o.lower() for o in own if o}
    return MENTION.sub(lambda m: m.group(0) if m.group(0)[1:].lower() in own_l else "@user", text or "")


def to_utc(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v, dt.timezone.utc)
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        try:
            return parsedate_to_datetime(v).astimezone(dt.timezone.utc)  # X: "Thu Mar 27 15:00:54 +0000 2025"
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------- live calls

class Client:
    def __init__(self, key):
        self.s = requests.Session()
        self.s.headers["Authorization"] = key
        self.log = []

    def get(self, channel, brand, path, params, attempt=1):
        t0 = time.time()
        try:
            r = self.s.get(BASE + path, params=params, timeout=180)
            status, hdr = r.status_code, {h: r.headers.get(h) for h in HEADERS}
            try:
                body = r.json()
            except ValueError:
                body = r.text
        except requests.RequestException as e:
            status, hdr, body = None, {h: None for h in HEADERS}, {"error": type(e).__name__}
        lat = round(time.time() - t0, 2)
        items = count_items(path, body)
        cost = hdr.get("X-Desearch-Cost-Usd")
        self.log.append({"ts": now_tb().isoformat(timespec="seconds"), "channel": channel, "brand": brand, "path": path,
                         "params": params, "attempt": attempt, "status": status, "latency_s": lat, "items": items,
                         "usage_count": int(hdr["X-Desearch-Usage-Count"]) if hdr.get("X-Desearch-Usage-Count") else None,
                         "cost_usd": round(float(cost), 6) if cost else None, "headers": hdr})
        print(f"  {channel:<10} {brand:<14} {status} {lat:>6.2f}s items={items} units={hdr.get('X-Desearch-Usage-Count')} "
              f"cost={self.log[-1]['cost_usd']}", flush=True)
        return status, body


def count_items(path, body):
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        for k in ("tweets", "data"):
            if isinstance(body.get(k), list):
                return len(body[k])
    if isinstance(body, str) and path.endswith("/extract"):
        return 1 if body.strip() else 0
    return None


UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
THIN = 200  # Extract text shorter than this (or empty) gets a direct fetch check


def visible_text(html):
    t = re.sub(r"(?is)<(script|style|noscript|template|svg)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"(?is)<(script|style)\b.*$", " ", t)  # cut-off html: drop an unclosed script at the end
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"&[a-zA-Z#0-9]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def direct_check(url):
    """One plain GET with a normal browser User-Agent and no auth (no Desearch call, no cost).
    Tells a page that needs JavaScript (no visible text in the HTML) from a static page."""
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=30, allow_redirects=True)
        vis = visible_text(r.text)
        return {"status": r.status_code, "final_url": r.url, "html_bytes": len(r.content), "visible_chars": len(vis),
                "visible_sample": vis[:300], "has_visible_text": r.status_code == 200 and len(vis) >= THIN}
    except requests.RequestException as e:
        return {"status": None, "error": type(e).__name__, "has_visible_text": False}


def extract(c, channel, brand, url, html_check=True):
    """Extract with js=false, retried once when no text comes back. Both tries are kept."""
    tries = []
    for attempt in (1, 2):
        status, body = c.get(channel, brand, "/web/extract", {"url": url, "format": "text", "js": "false"}, attempt)
        text = body if isinstance(body, str) else ""
        tries.append({"attempt": attempt, "status": status, "chars": len(text.strip()),
                      "detail": body.get("detail") if isinstance(body, dict) else None})
        if text.strip():
            break
    else:
        text = ""
    out = {"url": url, "text": text, "tries": tries}
    if html_check:
        # format=text keeps the main block; banners, promo strips and the page title live in the html read
        status, body = c.get(channel, brand, "/web/extract", {"url": url, "format": "html", "js": "false"}, 3)
        html = body if isinstance(body, str) else ""
        title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        out["html"] = {"status": status, "chars": len(html), "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else "",
                       "visible": visible_text(html)[:50000]}
    if len(text.strip()) < THIN:
        out["direct"] = direct_check(url)
    return out


def live(cfg, a, key):
    c = Client(key)
    since = a.since
    raw = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "since": since,
           "count": a.count, "brands": cfg["brands"], "results": {}, "generic_serp": None}
    prev = json.load(open(a.reuse_raw)) if a.reuse_raw else None
    if prev:
        raw["reused_from"] = a.reuse_raw
    for b in cfg["brands"]:
        name = b["brand"]
        print(name, flush=True)
        res = raw["results"][name] = {}
        if prev:  # keep the posts and X search of the earlier raw, call only pages and search again
            for ch in ("x_posts", "instagram", "tiktok", "x_search"):
                if ch in prev["results"].get(name, {}):
                    res[ch] = prev["results"][name][ch]
            raw["reused_calls"] = [x for x in prev.get("calls", []) if x["channel"] in ("x_posts", "instagram", "tiktok", "x_search")]
        if b.get("home"):
            res["site_home"] = [extract(c, "site_home", name, b["home"], a.html_check)]
        res["site_sale"] = [extract(c, "site_sale", name, u, a.html_check) for u in b.get("sale_urls", [])]
        if b.get("x") and not prev:
            st, body = c.get("x_posts", name, "/twitter/user/posts", {"username": b["x"]})
            res["x_posts"] = {"status": st, "tweets": body.get("tweets", []) if isinstance(body, dict) else [],
                              "user": (body.get("user") or {}) if isinstance(body, dict) else {}}
        for plat in ("instagram", "tiktok"):
            if b.get(plat) and not prev:
                st, body = c.get(plat, name, f"/desearch/{plat}/profile/{b[plat]}/posts", {"count": a.count})
                res[plat] = {"status": st, "posts": body if isinstance(body, list) else []}
        if a.x_search and b.get("x") and not prev:
            q = f'({name}) ("black friday" OR "cyber monday" OR "early access" OR sale)'
            st, body = c.get("x_search", name, "/twitter",
                             {"query": q, "start_date": since, "sort": "Latest", "count": a.x_count})
            res["x_search"] = {"status": st, "query": q, "tweets": body if isinstance(body, list) else []}
        q = f"{name} black friday {a.season_year}"
        st, body = c.get("serp_brand", name, "/web", {"query": q, "start": 0})
        res["serp_brand"] = {"status": st, "query": q, "results": body.get("data", []) if isinstance(body, dict) else []}
        watch = [r.get("link") for r in res["serp_brand"]["results"]
                 if urlparse(r.get("link") or "").netloc.lower().endswith(b.get("domain", "~"))
                 and re.search(r"black[\s-]*friday|bfcm|cyber", ((r.get("title") or "") + " " + (r.get("link") or "")).lower())
                 and r.get("link") not in b.get("sale_urls", []) and "/blog" not in (r.get("link") or "")]
        res["site_bf_page"] = [extract(c, "site_bf_page", name, u, a.html_check) for u in watch[: a.bf_pages]]
    if a.generic_query:
        st, body = c.get("serp_generic", "-", "/web", {"query": a.generic_query, "start": 0})
        raw["generic_serp"] = {"status": st, "query": a.generic_query,
                               "results": body.get("data", []) if isinstance(body, dict) else []}
    raw["calls"] = c.log
    return raw


def post_slim(p, handle, own):
    """Collab posts can name the partner account as author and in the URL: keep only the brand's own handle."""
    a = p.get("author") or {}
    mine = (a.get("username") or "").lower() == (handle or "").lower()
    url = p.get("url") or ""
    if not mine:
        m = re.search(r"/(p|reel|video)/([^/?]+)", url)
        url = f"https://www.instagram.com/p/{m.group(2)}/" if m and "instagram" in url else (
            f"https://www.tiktok.com/video/{p.get('id')}" if "tiktok" in url else "")
    return {"id": p.get("id"), "url": url, "createTime": p.get("createTime"),
            "author": {"username": a.get("username") if mine else "(partner account)", "verified": a.get("verified") if mine else None},
            "text": scrub(p.get("caption") or p.get("text"), own)}


def slim(raw):
    """Copy of the raw run that is safe to share: post text keeps only the brand's own @handles."""
    out = json.loads(json.dumps(raw))
    for b in out["brands"]:
        own = [b.get("x"), b.get("instagram"), b.get("tiktok")]
        r = out["results"].get(b["brand"], {})
        if "x_posts" in r:
            r["x_posts"]["tweets"] = [{"id": t.get("id"), "created_at": t.get("created_at"), "url": t.get("url"),
                                       "is_retweet": t.get("is_retweet"), "text": scrub(t.get("text"), own)}
                                      for t in r["x_posts"]["tweets"]]
            u = r["x_posts"].get("user") or {}
            r["x_posts"]["user"] = {k: u.get(k) for k in ("username", "name", "verified", "followers_count")}
        for plat in ("instagram", "tiktok"):
            if plat in r:
                r[plat]["posts"] = [post_slim(p, b.get(plat), own) for p in r[plat]["posts"]]
        if "x_search" in r:  # posts by other accounts: keep only id, date, own-account flag and promo terms
            r["x_search"]["tweets"] = [{"id": t.get("id"), "created_at": t.get("created_at"),
                                        "own_account": ((t.get("user") or {}).get("username") or "").lower() == (b.get("x") or "").lower(),
                                        "terms": sum(promo_terms(t.get("text")), [])} for t in r["x_search"]["tweets"]]
    return out


# ---------------------------------------------------------------- analysis

def redactor(words):
    pats = [re.compile(r"(?<![A-Za-z0-9])" + re.escape(w.strip()) + r"(?![A-Za-z0-9])", re.I) for w in words if w.strip()]

    def red(s):
        for p in pats:
            s = p.sub("[redacted]", s or "")
        return s
    return red


def post_items(channel, block):
    rows = []
    if channel == "x_posts":
        for t in block.get("tweets", []):
            rows.append({"id": t.get("id"), "url": t.get("url"), "created": to_utc(t.get("created_at")), "text": t.get("text") or ""})
    else:
        for p in block.get("posts", []):
            rows.append({"id": p.get("id"), "url": p.get("url"), "created": to_utc(p.get("createTime")),
                         "text": p.get("text") or p.get("caption") or ""})
    return rows


def serp_year(r):
    years = [int(y) for y in YEAR.findall(" ".join([r.get("title") or "", r.get("snippet") or "", r.get("link") or ""]))]
    years = [y for y in years if 2005 <= y <= 2030]
    if not years:
        return "undated", None
    m = max(years)
    return ("2025 or older" if m <= 2025 else "2026"), m


def analyse(raw, red):
    run_at = to_utc(raw["fetched_at"]).astimezone(TB)
    run_date = run_at.date().isoformat()
    since = dt.datetime.fromisoformat(raw["since"]).replace(tzinfo=dt.timezone.utc)
    snapshot, signals, timeline, serp_rows = [], [], [], []
    for b in raw["brands"]:
        name, own = b["brand"], [b.get("x"), b.get("instagram"), b.get("tiktok")]
        res = raw["results"].get(name, {})
        # pages
        for channel in ("site_home", "site_sale", "site_bf_page"):
            for pg in res.get(channel, []):
                h = pg.get("html") or {}
                ts, tw = promo_terms(pg["text"])
                hs, hw = promo_terms((h.get("title") or "") + " " + (h.get("visible") or ""))
                strong = ts + [x for x in hs if x not in ts]
                weak = tw + [x for x in hw if x not in tw]
                st = strength(strong, weak) if (pg["text"] or h.get("visible")) else "no text"
                snapshot.append({"brand": name, "channel": channel, "source": pg["url"], "items": 1 if pg["text"] else 0,
                                 "chars": len(pg["text"]), "extract_tries": len(pg["tries"]),
                                 "try1": f'{pg["tries"][0]["status"]}/{pg["tries"][0]["chars"]}',
                                 "try2": (f'{pg["tries"][1]["status"]}/{pg["tries"][1]["chars"]}' if len(pg["tries"]) > 1 else ""),
                                 "signal": st, "terms": "; ".join(strong + weak),
                                 "text_strong": "; ".join(ts), "html_strong_only": "; ".join(x for x in hs if x not in ts),
                                 "html_status": h.get("status", ""), "html_chars": h.get("chars", ""), "html_title": red(h.get("title", "")),
                                 "direct_status": (pg.get("direct") or {}).get("status", ""),
                                 "direct_visible_chars": (pg.get("direct") or {}).get("visible_chars", ""),
                                 "page_kind": page_kind(pg)})
                timeline.append({"run_date": run_date, "run_at_tbilisi": run_at.strftime("%Y-%m-%d %H:%M"), "brand": name,
                                 "channel": channel, "source": pg["url"], "checked": 1 if pg["text"] else 0,
                                 "signal": st, "terms": "; ".join(strong + weak), "signal_items": 1 if strong or weak else 0,
                                 "first_signal_item_utc": "", "first_signal_url": pg["url"] if strong or weak else "",
                                 "newest_item_utc": "", "excerpt": red(excerpt(pg["text"] if (ts or tw) else (h.get("title", "") + " " + h.get("visible", "")), strong + weak))})
                if strong or weak:
                    signals.append({"brand": name, "channel": channel, "created_utc": "", "strength": strength(strong, weak),
                                    "terms": "; ".join(strong + weak), "url": pg["url"],
                                    "excerpt": red(excerpt(pg["text"] if (ts or tw) else (h.get("title", "") + " " + h.get("visible", "")), strong + weak))})
        # posts
        for channel in POST_CHANNELS:
            if channel not in res:
                continue
            items = post_items(channel, res[channel])
            dated = [i for i in items if i["created"]]
            order = [i["created"] for i in dated]
            inversions = sum(1 for x, y in zip(order, order[1:]) if x < y)
            # pinned posts come first on Instagram and TikTok: count leading posts older than a later post
            lead = 0
            while lead < len(order) - 1 and order[lead] < max(order[lead + 1:]):
                lead += 1
            in_season = [i for i in dated if i["created"] >= since]
            hits = []
            for i in dated:
                strong, weak = promo_terms(i["text"])
                if strong or weak:
                    i.update(strong=strong, weak=weak)
                    hits.append(i)
                    signals.append({"brand": name, "channel": channel, "created_utc": i["created"].isoformat(),
                                    "strength": strength(strong, weak), "terms": "; ".join(strong + weak),
                                    "url": i["url"], "excerpt": red(scrub(excerpt(i["text"], strong + weak), own)),
                                    "in_season": i["created"] >= since})
            season_hits = sorted([h for h in hits if h["created"] >= since], key=lambda h: h["created"])
            strong_hits = [h for h in season_hits if h["strong"]]
            first = (strong_hits or season_hits or [None])[0]
            snapshot.append({"brand": name, "channel": channel, "source": handle_for(b, channel),
                             "status": res[channel].get("status"), "items": len(items),
                             "newest_utc": max(order).isoformat() if order else "", "oldest_utc": min(order).isoformat() if order else "",
                             "newest_first": (inversions == 0) if len(order) > 1 else "", "order_breaks": inversions,
                             "leading_out_of_order": lead,
                             "newest_first_after_leading": (all(x >= y for x, y in zip(order[lead:], order[lead + 1:]))) if len(order) > 1 else "",
                             "order_breaks_after_leading": sum(1 for x, y in zip(order[lead:], order[lead + 1:]) if x < y),
                             "in_season": len(in_season), "promo_posts_in_season": len(season_hits),
                             "promo_posts_older": len(hits) - len(season_hits),
                             "signal": strength(first["strong"], first["weak"]) if first else "none",
                             "terms": "; ".join(first["strong"] + first["weak"]) if first else ""})
            timeline.append({"run_date": run_date, "run_at_tbilisi": run_at.strftime("%Y-%m-%d %H:%M"), "brand": name,
                             "channel": channel, "source": handle_for(b, channel), "checked": len(in_season),
                             "signal": strength(first["strong"], first["weak"]) if first else "none",
                             "terms": "; ".join(first["strong"] + first["weak"]) if first else "",
                             "signal_items": len(season_hits),
                             "first_signal_item_utc": first["created"].isoformat() if first else "",
                             "first_signal_url": first["url"] if first else "",
                             "newest_item_utc": max(order).isoformat() if order else "",
                             "excerpt": red(scrub(excerpt(first["text"], first["strong"] + first["weak"]), own)) if first else ""})
        # X search (posts by any account, since the season start)
        if "x_search" in res:
            tw = res["x_search"].get("tweets", [])
            dated = [(to_utc(t.get("created_at")), t) for t in tw]
            own_posts = [t for _, t in dated if t.get("own_account") or ((t.get("user") or {}).get("username") or "").lower() == (b.get("x") or "").lower()]
            earliest = min((d for d, _ in dated if d), default=None)
            snapshot.append({"brand": name, "channel": "x_search", "source": res["x_search"]["query"],
                             "status": res["x_search"].get("status"), "items": len(tw),
                             "newest_utc": max((d for d, _ in dated if d), default=None) and max(d for d, _ in dated if d).isoformat(),
                             "oldest_utc": earliest.isoformat() if earliest else "", "own_account_posts": len(own_posts),
                             "outside_window": sum(1 for d, _ in dated if d and d < since)})
            timeline.append({"run_date": run_date, "run_at_tbilisi": run_at.strftime("%Y-%m-%d %H:%M"), "brand": name,
                             "channel": "x_search", "source": "posts by any account since " + raw["since"], "checked": len(tw),
                             "signal": "strong" if own_posts else ("mentions" if tw else "none"),
                             "terms": "", "signal_items": len(tw), "first_signal_item_utc": earliest.isoformat() if earliest else "",
                             "first_signal_url": f"https://x.com/i/status/{[t for d, t in dated if d == earliest][0].get('id')}" if earliest else "",
                             "newest_item_utc": "", "excerpt": f"{len(own_posts)} from the brand's own account"})
        # brand search
        if "serp_brand" in res:
            rs = res["serp_brand"]["results"]
            counts = {"2025 or older": 0, "2026": 0, "undated": 0}
            current = []
            for rank, r in enumerate(rs, 1):
                cls, yr = serp_year(r)
                counts[cls] += 1
                host = urlparse(r.get("link") or "").netloc.lower()
                own_site = host.endswith(b.get("domain", "~"))
                strong, weak = promo_terms((r.get("title") or "") + " " + (r.get("snippet") or ""))
                serp_rows.append({"run_date": run_date, "brand": name, "query": res["serp_brand"]["query"], "rank": rank,
                                  "year_class": cls, "max_year": yr or "", "own_site": own_site,
                                  "promo_terms": "; ".join(strong + weak), "title": red(r.get("title") or ""),
                                  "link": red_link(r.get("link") or "", red)})
                if own_site and strong:
                    current.append((rank, r, cls))
            snapshot.append({"brand": name, "channel": "serp_brand", "source": res["serp_brand"]["query"],
                             "status": res["serp_brand"].get("status"), "items": len(rs), "serp_2025_or_older": counts["2025 or older"],
                             "serp_2026": counts["2026"], "serp_undated": counts["undated"],
                             "own_site_results": sum(1 for x in serp_rows if x["brand"] == name and x["own_site"] is True),
                             "own_site_promo_results": len(current)})
            timeline.append({"run_date": run_date, "run_at_tbilisi": run_at.strftime("%Y-%m-%d %H:%M"), "brand": name,
                             "channel": "serp_brand", "source": res["serp_brand"]["query"], "checked": len(rs),
                             "signal": ("strong" if any(x[2] == "2026" for x in current) else "weak") if current else "none",
                             "terms": "own-site page with offer wording" + (" naming 2026" if any(x[2] == "2026" for x in current) else "") if current else "",
                             "signal_items": len(current), "first_signal_item_utc": "",
                             "first_signal_url": red_link(current[0][1].get("link") or "", red) if current else "",
                             "newest_item_utc": "", "excerpt": red(current[0][1].get("title") or "") if current else
                             f'{counts["2025 or older"]} of {len(rs)} results name 2025 or older'})
    g = raw.get("generic_serp")
    if g:
        for rank, r in enumerate(g["results"], 1):
            cls, yr = serp_year(r)
            serp_rows.append({"run_date": run_date, "brand": "-", "query": g["query"], "rank": rank, "year_class": cls,
                              "max_year": yr or "", "own_site": "", "promo_terms": "; ".join(sum(promo_terms((r.get("title") or "") + " " + (r.get("snippet") or "")), [])),
                              "title": red(r.get("title") or ""), "link": red_link(r.get("link") or "", red)})
    return run_date, run_at, snapshot, signals, timeline, serp_rows


def page_kind(pg):
    """Only set for pages where Extract gave no text or thin text and the direct fetch ran."""
    d = pg.get("direct")
    if not d:
        return ""
    if d.get("status") != 200:
        return f"page answers {d.get('status')} to a direct fetch"
    if not d.get("has_visible_text"):
        return "needs JavaScript (no visible text in the HTML)"
    return "static page: HTML has visible text" + ("" if pg["text"].strip() else ", Extract returned none")


def redact_all(obj, red):
    """Apply the redact list to every string in the raw that goes to output/ (titles, snippets, links, page text)."""
    if isinstance(obj, str):
        r = red(obj)
        if r != obj and obj.startswith("http"):
            return "https://redacted.invalid/"  # keep it a valid URL
        return r
    if isinstance(obj, list):
        return [redact_all(x, red) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_all(v, red) for k, v in obj.items()}
    return obj


def red_link(link, red):
    host = urlparse(link).netloc
    return "[redacted link]" if (red(host) != host or host == "redacted.invalid") else link


def handle_for(b, channel):
    return {"x_posts": b.get("x"), "instagram": b.get("instagram"), "tiktok": b.get("tiktok")}.get(channel, "")


def excerpt(text, terms, width=90):
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    low = t.lower()
    pos = -1
    for n, p in STRONG + WEAK:
        if n in terms:
            m = re.search(p, low)
            if m:
                pos = m.start()
                break
    if pos < 0:
        return t[:width * 2]
    s = max(0, pos - width)
    return ("..." if s else "") + t[s:pos + width] + ("..." if pos + width < len(t) else "")


TIMELINE_COLS = ["run_date", "run_at_tbilisi", "brand", "channel", "source", "checked", "signal", "terms", "signal_items",
                 "first_signal_item_utc", "first_signal_url", "newest_item_utc", "excerpt", "first_seen_run"]


def append_timeline(path, rows):
    """Keep earlier runs, replace rows of the same run_date, and add first_seen_run per brand + channel + source."""
    old = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            old = [r for r in csv.DictReader(f) if r["run_date"] != rows[0]["run_date"]] if rows else list(csv.DictReader(f))
    allrows = old + rows
    first = {}
    for r in sorted(allrows, key=lambda r: r["run_date"]):
        k = (r["brand"], r["channel"], r["source"])
        if r["signal"] in ("strong",) and k not in first:
            first[k] = r["run_date"]
    for r in allrows:
        r["first_seen_run"] = first.get((r["brand"], r["channel"], r["source"]), "")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TIMELINE_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(allrows, key=lambda r: (r["run_date"], r["brand"], CHANNELS.index(r["channel"]) if r["channel"] in CHANNELS else 99)))
    return allrows


def write_csv(path, rows):
    if not rows:
        return
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def chart(raw, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    since = dt.datetime.fromisoformat(raw["since"]).replace(tzinfo=dt.timezone.utc)
    lanes, pts = [], []
    for b in raw["brands"]:
        for ch in POST_CHANNELS:
            block = raw["results"].get(b["brand"], {}).get(ch)
            if not block:
                continue
            lanes.append(f'{b["brand"]} {ch.replace("_posts", "")}')
            for i in post_items(ch, block):
                if i["created"] and i["created"] >= since - dt.timedelta(days=30):
                    s, w = promo_terms(i["text"])
                    pts.append((len(lanes) - 1, i["created"], strength(s, w)))
    fig, ax = plt.subplots(figsize=(9, 0.4 * len(lanes) + 1.5))
    style = {"none": dict(c="lightgrey", marker="o"), "weak": dict(c="orange", marker="o"), "strong": dict(c="red", marker="D")}
    for k, st in style.items():
        p = [x for x in pts if x[2] == k]
        if p:
            ax.scatter([x[1] for x in p], [x[0] for x in p], s=28, label=f"{k} promo wording" if k != "none" else "no promo wording", **st)
    ax.axvline(since, color="black", lw=0.8, ls="--")
    ax.set_yticks(range(len(lanes)), lanes)
    ax.invert_yaxis()
    ax.set_title(f"Posts returned per brand and channel, from 30 days before {raw['since']} (dashed line)")
    ax.legend(loc="lower left", fontsize=7)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def summary(raw, run_date, run_at, snapshot, signals, timeline, serp_rows, calls, path):
    L = [f"# Holiday Promo Watch, {run_date}", "",
         f"Made by [Desearch](https://desearch.ai). Snapshot taken {run_at:%Y-%m-%d %H:%M} Asia/Tbilisi. "
         f"Post channels count posts dated {raw['since']} or later. This lists the public posts and pages Desearch "
         "returned on the run date; it is not a list of every promotion.", "",
         "## First promo signal per brand and channel (this run)", "",
         "| brand | homepage | sale page(s) | Black Friday page(s) | X posts | Instagram | TikTok | brand search (own-site results) |", "|---|---|---|---|---|---|---|---|"]
    def cell(brand, ch):
        rows = [r for r in timeline if r["brand"] == brand and r["channel"] == ch]
        if not rows:
            return "n/a"
        out = []
        for r in rows:
            if r["signal"] in ("strong", "weak"):
                d = r["first_signal_item_utc"][:10]
                out.append(f'{r["signal"]}: {r["terms"]}' + (f" ({d})" if d else ""))
            elif r["signal"] == "no text":
                out.append("no text")
            else:
                out.append("none")
        return "<br>".join(out)
    for b in raw["brands"]:
        n = b["brand"]
        L.append(f"| {n} | {cell(n, 'site_home')} | {cell(n, 'site_sale')} | {cell(n, 'site_bf_page')} | {cell(n, 'x_posts')} | {cell(n, 'instagram')} | "
                 f"{cell(n, 'tiktok')} | {cell(n, 'serp_brand')} |")
    L += ["", "Strong = offer wording (black friday, cyber monday, early access, N% off, code, sitewide). "
          "Weak = words such as sale, deal or offer, which also appear in menus and everyday copy.", "",
          "## Who moved first", ""]
    firsts = sorted([r for r in timeline if r["signal"] == "strong" and r["first_signal_item_utc"] and r["channel"] in POST_CHANNELS],
                    key=lambda r: r["first_signal_item_utc"])
    if firsts:
        L += [f'- {r["first_signal_item_utc"][:10]}: {r["brand"]} on {r["channel"]} ("{r["terms"]}")' for r in firsts]
    else:
        L += [f"No post with strong promo wording dated {raw['since']} or later in this run. Today is the baseline."]
    L += ["", "## Channels", "", "| brand | channel | items | newest (UTC) | pinned or out of order at top | newest first after those | in season |", "|---|---|---|---|---|---|---|"]
    for s in snapshot:
        if s["channel"] in POST_CHANNELS:
            L.append(f'| {s["brand"]} | {s["channel"]} | {s["items"]} | {s["newest_utc"][:10]} | {s["leading_out_of_order"]} | {s["newest_first_after_leading"]} | {s["in_season"]} |')
    gen = [r for r in serp_rows if r["brand"] == "-"]
    br = [r for r in serp_rows if r["brand"] != "-"]
    def yrs(rows):
        return (sum(r["year_class"] == "2025 or older" for r in rows), sum(r["year_class"] == "2026" for r in rows),
                sum(r["year_class"] == "undated" for r in rows))
    L += ["", "## Search results by year named", ""]
    if br:
        o, n, u = yrs(br)
        L.append(f"- Brand queries: {len(br)} results; {o} name 2025 or older, {n} name 2026, {u} name no year.")
    if gen:
        o, n, u = yrs(gen)
        L.append(f'- "{gen[0]["query"]}": {len(gen)} results; {o} name 2025 or older, {n} name 2026, {u} name no year.')
    if calls:
        cost = sum(c["cost_usd"] or 0 for c in calls)
        L += ["", "## Cost", "", f"{len(calls)} calls, ${cost:.4f} (sum of the X-Desearch-Cost-Usd headers)."]
        if raw.get("reused_calls"):
            rc = raw["reused_calls"]
            L.append(f"Posts and X search were reused from an earlier run today ({len(rc)} calls, ${sum(x['cost_usd'] or 0 for x in rc):.4f}), not called again.")
    open(path, "w").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Holiday Promo Watch (Desearch API)")
    ap.add_argument("brands", nargs="?", help="brands JSON (see brands.json)")
    ap.add_argument("--from-raw", help="rebuild outputs from a saved raw JSON, no API calls")
    ap.add_argument("--since", default="2026-10-01", help="season start: post channels count posts from this UTC date")
    ap.add_argument("--until", default="2026-11-30", help="last day to run; later live runs exit without calling the API")
    ap.add_argument("--count", type=int, default=30, help="posts requested per Instagram / TikTok profile (1 to 100)")
    ap.add_argument("--x-count", type=int, default=20, help="posts requested per brand X search (1 to 100)")
    ap.add_argument("--no-x-search", dest="x_search", action="store_false", help="skip the per-brand X search")
    ap.add_argument("--season-year", default="2026")
    ap.add_argument("--no-html-check", dest="html_check", action="store_false",
                    help="skip the extra format=html read per page (it finds banners and titles the text read leaves out)")
    ap.add_argument("--reuse-raw", help="full raw of an earlier run today: reuse its posts, call only pages and search again")
    ap.add_argument("--bf-pages", type=int, default=2, help="own-site Black Friday pages from the brand search to read per brand")
    ap.add_argument("--generic-query", default="black friday 2026", help="one extra search for the season itself ('' to skip)")
    ap.add_argument("--redact-file", help="words to replace with [redacted] in saved titles, excerpts and links")
    ap.add_argument("--full-raw", help="also save every response unchanged to this private path")
    ap.add_argument("--out", default="output")
    a = ap.parse_args()
    words = [w.strip() for w in open(a.redact_file)] if a.redact_file else []
    red = redactor(words)
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        if not a.brands:
            ap.error("give a brands JSON file (see brands.json) or --from-raw")
        if now_tb().date().isoformat() > a.until:
            sys.exit(f"Past --until {a.until}: nothing to do.")
        if not 1 <= a.count <= 100 or not 1 <= a.x_count <= 100:
            ap.error("--count and --x-count must be 1..100")
        key = os.environ.get("DESEARCH_API_KEY") or sys.exit("Set DESEARCH_API_KEY (create a key at console.desearch.ai).")
        raw = live(json.load(open(a.brands)), a, key)
        if a.full_raw:
            os.makedirs(os.path.dirname(a.full_raw) or ".", exist_ok=True)
            json.dump(raw, open(a.full_raw, "w"), ensure_ascii=False)
            print("full raw saved:", a.full_raw)
        raw = slim(raw)
        if words:
            raw = redact_all(raw, red)
    os.makedirs(a.out, exist_ok=True)
    run_date, run_at, snapshot, signals, timeline, serp_rows = analyse(raw, red)
    base = f"{a.out}/{run_date}"
    if not a.from_raw:
        json.dump(raw, open(f"{a.out}/raw-{run_date}.json", "w"), ensure_ascii=False, indent=1)
    calls = raw.get("calls", [])
    write_csv(f"{base}-snapshot.csv", snapshot)
    write_csv(f"{base}-signals.csv", signals)
    write_csv(f"{base}-serp.csv", serp_rows)
    write_csv(f"{base}-costs.csv", [{k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in c.items()} for c in calls])
    append_timeline(f"{a.out}/promo_timeline.csv", timeline)
    chart(raw, f"{base}-posts-chart.png")
    summary(raw, run_date, run_at, snapshot, signals, timeline, serp_rows, calls, f"{base}-summary.md")
    print(f"wrote {a.out}/promo_timeline.csv (appended), {base}-summary.md, -snapshot.csv, -signals.csv, -serp.csv, -costs.csv, -posts-chart.png")


if __name__ == "__main__":
    main()
