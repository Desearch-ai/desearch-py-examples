#!/usr/bin/env python3
"""Reply Ledger: which of an X account's public replies worked.

Pulls a handle's recent public posts and replies from the Desearch API and writes
a Markdown ledger, a JSON snapshot and a call log with cost.

Endpoints (base https://api.desearch.ai, header Authorization: <key>):
  GET /twitter/user/posts?username=&cursor=        recent timeline, newest first, ~20 per page
  GET /twitter/replies?user=&count=100&query=since:YYYY-MM-DD   tweets and replies by user
  GET /twitter/post?id=                            parent post of top replies (optional)
"""
import argparse, collections, datetime as dt, email.utils, json, os, statistics, sys, time

BASE = "https://api.desearch.ai"
KEY_FILE_ENV = "DESEARCH_API_KEY_FILE"


# ---------------------------------------------------------------- pure logic

def parse_time(s):
    """X created_at ('Wed Oct 01 16:36:07 +0000 2026') -> aware UTC datetime, or None."""
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def username(t):
    return ((t.get("user") or {}).get("username") or "").lower()


def kind(t, handle):
    """original | retweet | self_reply (thread continuation) | reply (to someone else)."""
    if t.get("is_retweet"):
        return "retweet"
    if t.get("in_reply_to_status_id"):
        to = (t.get("in_reply_to_screen_name") or "").lower()
        return "self_reply" if to == handle.lower() else "reply"
    return "original"


def engagement(t):
    """Simple score: likes + 2*replies + retweets + quotes + bookmarks. Views are shown, not scored
    (they are often empty on older posts)."""
    g = lambda k: int(t.get(k) or 0)
    return g("like_count") + 2 * g("reply_count") + g("retweet_count") + g("quote_count") + g("bookmark_count")


def merge(*lists):
    """Dedupe by id, keep first seen."""
    seen, out = set(), []
    for lst in lists:
        for t in lst or []:
            i = str(t.get("id"))
            if i and i not in seen:
                seen.add(i)
                out.append(t)
    return out


def own_only(tweets, handle):
    return [t for t in tweets if username(t) == handle.lower()]


def in_window(tweets, since):
    out = []
    for t in tweets:
        d = parse_time(t.get("created_at"))
        if d and d >= since:
            out.append(t)
    return out


def fill_rates(tweets, fields=("view_count", "bookmark_count", "like_count", "reply_count",
                               "retweet_count", "quote_count", "conversation_id", "created_at")):
    """Per field: present (not null) and non-zero counts."""
    n = len(tweets)
    res = {}
    for f in fields:
        present = sum(1 for t in tweets if t.get(f) not in (None, ""))
        nonzero = sum(1 for t in tweets if t.get(f) not in (None, "", 0))
        res[f] = {"n": n, "present": present, "nonzero": nonzero}
    return res


def top_targets(replies, k=10):
    c = collections.Counter(t.get("in_reply_to_screen_name") or "?" for t in replies)
    eng = collections.defaultdict(list)
    for t in replies:
        eng[t.get("in_reply_to_screen_name") or "?"].append(engagement(t))
    return [{"account": a, "replies": n, "median_engagement": statistics.median(eng[a])}
            for a, n in c.most_common(k)]


def volume_by_day(tweets, handle):
    rows = collections.defaultdict(lambda: collections.Counter())
    for t in tweets:
        d = parse_time(t.get("created_at"))
        if d:
            rows[d.date().isoformat()][kind(t, handle)] += 1
    return dict(sorted(rows.items(), reverse=True))


def summary_stats(tweets, handle):
    by = collections.defaultdict(list)
    for t in tweets:
        by[kind(t, handle)].append(t)
    out = {}
    for k, lst in by.items():
        views = [int(t["view_count"]) for t in lst if t.get("view_count") not in (None, "")]
        out[k] = {"count": len(lst),
                  "median_likes": statistics.median([int(t.get("like_count") or 0) for t in lst]),
                  "median_views": statistics.median(views) if views else None,
                  "views_filled": len(views),
                  "median_bookmarks": statistics.median([int(t.get("bookmark_count") or 0) for t in lst])}
    return out


def notable_threads(tweets, handle, k=5):
    """Own original posts with the most replies where the sample holds no reply from the handle
    in the same conversation. 'Unanswered in this sample', not proof of no reply."""
    answered = {str(t.get("conversation_id")) for t in tweets
                if kind(t, handle) in ("reply", "self_reply") and t.get("conversation_id")}
    cands = [t for t in tweets if kind(t, handle) == "original" and int(t.get("reply_count") or 0) > 0
             and str(t.get("conversation_id") or t.get("id")) not in answered]
    cands.sort(key=lambda t: int(t.get("reply_count") or 0), reverse=True)
    return cands[:k]


def short(text, n=140):
    s = " ".join((text or "").split()).replace("|", "/").replace("\u2014", "-")
    return s if len(s) <= n else s[: n - 3] + "..."


def cost_line(calls):
    usd = sum(c.get("cost_usd") or 0 for c in calls)
    units = sum(c.get("units") or 0 for c in calls)
    return f"{len(calls)} Desearch calls, {units} billed units, ${usd:.5f} (from X-Desearch-Cost-Usd headers)"


def render(handle, since, tweets, calls, parents, generated):
    reps = [t for t in tweets if kind(t, handle) == "reply"]
    L = [f"# Reply Ledger: @{handle}", "",
         f"Generated {generated} (Asia/Tbilisi). Window: posts and replies created on or after {since.date()} (UTC). "
         f"Public posts and replies only.", "",
         f"Items in window: {len(tweets)} ({len(reps)} replies to other accounts).", ""]
    L += ["## Replies vs posts", "", "| Kind | Count | Median likes | Median views (filled) | Median bookmarks |", "|---|---|---|---|---|"]
    for k, s in sorted(summary_stats(tweets, handle).items()):
        mv = "n/a" if s["median_views"] is None else f'{s["median_views"]:g}'
        L.append(f'| {k} | {s["count"]} | {s["median_likes"]:g} | {mv} ({s["views_filled"]}) | {s["median_bookmarks"]:g} |')
    L += ["", "## Who they reply to most", "", "| Account | Replies | Median engagement |", "|---|---|---|"]
    for r in top_targets(reps):
        L.append(f'| @{r["account"]} | {r["replies"]} | {r["median_engagement"]:g} |')
    if not reps:
        L.append("| (no replies to other accounts in the window) | | |")
    L += ["", "## Reply volume by day (UTC)", "", "| Day | Replies | Thread replies | Originals | Reposts |", "|---|---|---|---|---|"]
    for d, c in volume_by_day(tweets, handle).items():
        L.append(f'| {d} | {c["reply"]} | {c["self_reply"]} | {c["original"]} | {c["retweet"]} |')
    L += ["", "## Top replies by engagement", "",
          "Score = likes + 2 x replies + reposts + quotes + bookmarks.", "",
          "| # | Score | Likes | Views | Bookmarks | To | Parent | Reply |", "|---|---|---|---|---|---|---|---|"]
    for i, t in enumerate(sorted(reps, key=engagement, reverse=True)[:10], 1):
        pid = str(t.get("in_reply_to_status_id"))
        p = parents.get(pid)
        ptxt = short(p.get("text"), 60) if p else "(not fetched)"
        purl = f"https://x.com/{t.get('in_reply_to_screen_name')}/status/{pid}"
        L.append(f'| {i} | {engagement(t)} | {t.get("like_count") or 0} | {t.get("view_count") if t.get("view_count") is not None else "n/a"} | '
                 f'{t.get("bookmark_count") or 0} | @{t.get("in_reply_to_screen_name")} | [{ptxt}]({purl}) | [{short(t.get("text"))}]({t.get("url")}) |')
    L += ["", "## Busy threads with no reply from the account in this sample", "",
          "Own posts with the most replies where none of the pulled items is a reply from the account in that conversation.", "",
          "| Replies | Likes | Posted (UTC) | Post |", "|---|---|---|---|"]
    nt = notable_threads(tweets, handle)
    for t in nt:
        L.append(f'| {t.get("reply_count")} | {t.get("like_count")} | {parse_time(t["created_at"]):%Y-%m-%d %H:%M} | [{short(t.get("text"), 90)}]({t.get("url")}) |')
    if not nt:
        L.append("| (none) | | | |")
    L += ["", "## Field fill rates (replies to other accounts)", "", "| Field | Present | Non-zero | Of |", "|---|---|---|---|"]
    for f, r in fill_rates(reps).items():
        L.append(f'| {f} | {r["present"]} | {r["nonzero"]} | {r["n"]} |')
    L += ["", "## Cost", "", cost_line(calls), ""]
    return "\n".join(L)


# ---------------------------------------------------------------- API

def load_key():
    k = os.environ.get("DESEARCH_API_KEY")
    if not k and os.environ.get(KEY_FILE_ENV):
        k = open(os.environ[KEY_FILE_ENV]).read().strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY (or DESEARCH_API_KEY_FILE).")
    return k


class Client:
    def __init__(self, key, raw_dir=None, max_spend=0.5):
        import requests
        self.s = requests.Session()
        self.s.headers["Authorization"] = key
        self.key, self.raw_dir, self.max_spend, self.calls = key, raw_dir, max_spend, []

    def spent(self):
        return sum(c["cost_usd"] or 0 for c in self.calls)

    def get(self, path, params, label):
        if self.spent() >= self.max_spend:
            raise RuntimeError(f"max spend ${self.max_spend} reached")
        when = time.strftime("%Y-%m-%d %H:%M:%S %z")
        t0 = time.perf_counter()
        r = self.s.get(BASE + path, params=params, timeout=180)
        lat = round(time.perf_counter() - t0, 2)
        try:
            body = r.json()
        except ValueError:
            body = {"_raw_text": r.text[:5000]}
        f = lambda h, cast: cast(r.headers[h]) if r.headers.get(h) not in (None, "") else None
        rec = {"n": len(self.calls) + 1, "when": when, "path": path, "params": params, "status": r.status_code,
               "latency_s": lat, "cost_usd": f("X-Desearch-Cost-Usd", float), "units": f("X-Desearch-Usage-Count", int)}
        items = body if isinstance(body, list) else (body.get("tweets") if isinstance(body, dict) else None)
        rec["items"] = len(items) if isinstance(items, list) else (1 if r.status_code == 200 and path == "/twitter/post" else 0)
        self.calls.append(rec)
        print(f"[{when}] {r.status_code} {path} {params} items={rec['items']} units={rec['units']} "
              f"cost=${rec['cost_usd']} {lat}s", file=sys.stderr)
        if self.raw_dir:
            out = json.dumps({"request": {"method": "GET", "url": BASE + path, "params": params,
                                          "headers": {"Authorization": "<redacted>"}},
                              "call": rec, "response": body}, indent=1, ensure_ascii=False)
            assert self.key not in out
            with open(os.path.join(self.raw_dir, f"{rec['n']:03d}-{label}.json"), "w") as fh:
                fh.write(out)
        return r.status_code, body


def fetch(client, handle, since, pages, parents_n):
    timeline, cursor, user = [], None, None
    for p in range(pages):
        params = {"username": handle} | ({"cursor": cursor} if cursor else {})
        st, body = client.get("/twitter/user/posts", params, f"user-posts-p{p + 1}")
        if st == 404 and p == 0:
            return None, [], {}  # handle not found: skip the replies call (it bills 10 units on empty)
        if st != 200 or not isinstance(body, dict):
            break
        user = body.get("user") or user
        tw = body.get("tweets") or []
        timeline += tw
        cursor = body.get("next_cursor")
        oldest = min((parse_time(t.get("created_at")) for t in tw), default=None)
        if not cursor or not tw or (oldest and oldest < since):
            break
    st, body = client.get("/twitter/replies", {"user": handle, "count": 100, "query": f"since:{since.date()}"}, "replies")
    replies = body if st == 200 and isinstance(body, list) else []
    tweets = in_window(own_only(merge(timeline, replies), handle), since)
    parents = {}
    top = sorted([t for t in tweets if kind(t, handle) == "reply"], key=engagement, reverse=True)[:parents_n]
    for t in top:
        pid = str(t.get("in_reply_to_status_id"))
        try:
            st, body = client.get("/twitter/post", {"id": pid}, f"parent-{pid}")
        except RuntimeError:
            break
        if st == 200 and isinstance(body, dict) and body.get("text"):
            parents[pid] = body
    return user, tweets, parents


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("handle", help="X handle without @")
    ap.add_argument("--days", type=int, default=30, help="look-back window in days (default 30)")
    ap.add_argument("--pages", type=int, default=5, help="max timeline pages of ~20 (default 5)")
    ap.add_argument("--parents", type=int, default=5, help="parent posts to look up for the top replies (default 5, 0 = off)")
    ap.add_argument("--max-spend", type=float, default=0.25, help="stop calling once this many USD are spent")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--no-raw", action="store_true")
    a = ap.parse_args(argv)
    handle = a.handle.lstrip("@")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(a.out, f"{stamp}-{handle.lower()}")
    raw = None if a.no_raw else os.path.join(out, "raw")
    os.makedirs(raw or out, exist_ok=True)
    since = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=a.days)
    c = Client(load_key(), raw, a.max_spend)
    user, tweets, parents = fetch(c, handle, since, a.pages, a.parents)
    if not tweets and not user:
        print(f"No public posts or replies found for @{handle} (check the handle).", file=sys.stderr)
    md = render(handle, since, tweets, c.calls, parents, time.strftime("%Y-%m-%d %H:%M"))
    open(os.path.join(out, "ledger.md"), "w").write(md)
    snap = {"handle": handle, "since_utc": since.isoformat(), "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "user": user, "calls": c.calls, "cost_usd": round(c.spent(), 6),
            "items": [{k: t.get(k) for k in ("id", "created_at", "url", "text", "in_reply_to_screen_name",
                                              "in_reply_to_status_id", "conversation_id", "like_count", "reply_count",
                                              "retweet_count", "quote_count", "bookmark_count", "view_count", "is_retweet")}
                      | {"kind": kind(t, handle), "engagement": engagement(t)} for t in tweets],
            "parents": parents}
    open(os.path.join(out, "snapshot.json"), "w").write(json.dumps(snap, indent=1, ensure_ascii=False))
    print(f"wrote {out}/ledger.md ; {cost_line(c.calls)}", file=sys.stderr)
    return out


if __name__ == "__main__":
    main()
