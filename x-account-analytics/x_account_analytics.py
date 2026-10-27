"""X Account Analytics: per-post engagement CSV and a markdown summary for the latest posts of one public X account.

Made by Desearch (https://desearch.ai).

Live:     python x_account_analytics.py --username ACCOUNT [--pages 3] [--tz UTC] --key-file ~/.desearch_api_key
Offline:  python x_account_analytics.py --from-raw samples/sample-raw.json
Key: read only from a key file (default ~/.desearch_api_key, or --key-file PATH). Never from the environment.
"""
import argparse, asyncio, csv, datetime as dt, json, os, re, statistics as st, sys, time
from zoneinfo import ZoneInfo

DEFAULT_KEY_FILE = "~/.desearch_api_key"
MAX_PAGES = 10
FORMULA = ("engagements = likes + reposts + replies + quotes + bookmarks; "
           "ER per view % = engagements / views x 100; ER per follower % = engagements / followers x 100")
POST_FIELDS = ["post_id", "created_utc", "created_local", "weekday_local", "hour_local", "type", "media", "pinned",
               "likes", "reposts", "replies", "quotes", "bookmarks", "views", "engagements",
               "er_per_view_pct", "er_per_follower_pct", "in_rates", "excluded_reason", "url", "text"]
SUMMARY_FIELDS = ["username", "followers", "posts_on_profile", "posts_analyzed", "first_post_utc", "last_post_utc",
                  "span_days", "posts_per_day", "originals", "replies", "threads", "quotes", "reposts",
                  "posts_in_rates", "median_engagements", "mean_engagements", "median_er_per_view_pct",
                  "mean_er_per_view_pct", "median_er_per_follower_pct", "mean_er_per_follower_pct",
                  "best_weekday", "best_hour", "time_zone", "excluded"]


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def read_key(path):
    p = os.path.expanduser(path)
    if not os.path.isfile(p):
        raise SystemExit(f"key file not found: {p} (put your Desearch API key in it, one line)")
    with open(p, encoding="utf-8") as f:
        k = f.read().strip()
    if not k:
        raise SystemExit(f"key file is empty: {p}")
    return k


# ---------- live fetch (desearch-py SDK, GET /twitter/user/posts) ----------

async def fetch(username, pages, key):
    import aiohttp
    from desearch_py import Desearch
    raw = {"started": now(), "username": username, "pages_requested": pages, "calls": []}
    cursor, seen_cursors = None, set()
    async with Desearch(api_key=key) as client:
        for page in range(1, pages + 1):
            at, t0 = now(), time.time()
            rec = {"page": page, "cursor_sent": cursor, "at": at}
            try:
                res = await client.x_user_posts(username, cursor=cursor, include_metadata=True)
                body = res.data.model_dump(mode="json", exclude_unset=True)
                meta = res.metadata
                rec.update(status=200, cost_usd=meta.cost_usd, usage_count=meta.usage_count, service=meta.service,
                           body_cost_usd=body.get("cost_usd"), body_usage_count=body.get("usage_count"), body=body)
            except aiohttp.ClientResponseError as e:
                h = e.headers or {}
                rec.update(status=e.status, error=e.message, cost_usd=h.get("X-Desearch-Cost-Usd"),
                           usage_count=h.get("X-Desearch-Usage-Count"), body=None)
            except Exception as e:  # network or validation error: record it and stop
                rec.update(status=None, error=repr(e)[:500], body=None)
            rec["seconds"] = round(time.time() - t0, 2)
            raw["calls"].append(rec)
            n = len((rec.get("body") or {}).get("tweets") or [])
            print(f"{at} page {page} status={rec['status']} {rec['seconds']}s posts={n} cost={rec.get('cost_usd')}",
                  file=sys.stderr, flush=True)
            if rec["status"] != 200 or not n:
                break
            cursor = rec["body"].get("next_cursor")
            if not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
    return raw


# ---------- parsing ----------

def parse_time(s):
    if not s:
        return None
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return dt.datetime.strptime(s.replace("Z", "+00:00"), fmt).astimezone(dt.timezone.utc)
        except ValueError:
            continue
    return None


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def post_type(t, account_id):
    text = t.get("text") or ""
    if t.get("is_retweet") or t.get("retweet") or text.startswith("RT @"):
        return "repost"
    if t.get("in_reply_to_status_id"):
        return "thread" if account_id and str(t.get("in_reply_to_user_id")) == str(account_id) else "reply"
    if t.get("is_quote_tweet") or t.get("quoted_status_id"):
        return "quote"
    return "original"


def media_kind(t):
    kinds = []
    for m in (t.get("media") or []):
        k = (m or {}).get("type") or "other"
        k = {"animated_gif": "gif"}.get(k, k)
        if k not in kinds:
            kinds.append(k)
    if not kinds:
        return "none"
    return kinds[0] if len(kinds) == 1 else "mixed"


def pct(a, b):
    return round(100 * a / b, 3) if a is not None and b else None


def post_row(t, followers, account_id, pinned_ids, tz):
    created = parse_time(t.get("created_at"))
    loc = created.astimezone(tz) if created else None
    vals = {"likes": num(t.get("like_count")), "reposts": num(t.get("retweet_count")), "replies": num(t.get("reply_count")),
            "quotes": num(t.get("quote_count")), "bookmarks": num(t.get("bookmark_count"))}
    views = num(t.get("view_count"))
    eng = sum(v for v in vals.values() if v is not None) if any(v is not None for v in vals.values()) else None
    typ = post_type(t, account_id)
    reasons = []
    if typ == "repost":
        reasons.append("repost (counts are not this account's own engagement)")
    if eng is None:
        reasons.append("no engagement counts")
    row = {"post_id": str(t.get("id", "")), "created_utc": created.strftime("%Y-%m-%d %H:%M") if created else "",
           "created_local": loc.strftime("%Y-%m-%d %H:%M") if loc else "", "weekday_local": loc.strftime("%a") if loc else "",
           "hour_local": loc.hour if loc else "", "type": typ, "media": media_kind(t),
           "pinned": str(t.get("id")) in pinned_ids, **vals, "views": views, "engagements": eng,
           "er_per_view_pct": pct(eng, views) if not reasons else None,
           "er_per_follower_pct": pct(eng, followers) if not reasons else None,
           "in_rates": not reasons, "excluded_reason": "; ".join(reasons),
           "url": t.get("url") or "", "text": " ".join((t.get("text") or "").split())[:280]}
    return row


# ---------- analysis ----------

def stats(vals):
    v = [x for x in vals if isinstance(x, (int, float))]
    if not v:
        return None, None, 0
    return round(st.median(v), 3), round(st.mean(v), 3), len(v)


def best_slot(rows, key, min_n=2):
    groups = {}
    for r in rows:
        if r[key] != "" and r["engagements"] is not None:
            groups.setdefault(r[key], []).append(r["engagements"])
    cand = {k: v for k, v in groups.items() if len(v) >= min_n} or groups
    if not cand:
        return "", groups
    k = max(cand, key=lambda g: (st.median(cand[g]), len(cand[g])))
    return f"{k} (median engagements {st.median(cand[k]):g}, n={len(cand[k])})", groups


def build(raw, tz_name="UTC", top=5):
    tz = ZoneInfo(tz_name)
    user, seen, rows, pagelog, order = None, set(), [], [], []
    for c in raw.get("calls", []):
        body = c.get("body") or {}
        tweets = body.get("tweets") or []
        if body.get("user"):
            user = body["user"]
        new = [t for t in tweets if str(t.get("id")) not in seen]
        pagelog.append({"page": c.get("page"), "status": c.get("status"), "cursor_sent": bool(c.get("cursor_sent")),
                        "returned": len(tweets), "new": len(new), "repeats": len(tweets) - len(new),
                        "next_cursor": bool(body.get("next_cursor")), "seconds": c.get("seconds"),
                        "cost_usd": c.get("cost_usd"), "body_cost_usd": c.get("body_cost_usd")})
        for t in new:
            seen.add(str(t.get("id")))
            order.append(t)
    followers = num((user or {}).get("followers_count"))
    account_id = (user or {}).get("id")
    pinned = {str(x) for x in ((user or {}).get("pinned_tweet_ids") or [])}
    rows = [post_row(t, followers, account_id, pinned, tz) for t in order]
    rows.sort(key=lambda r: r["created_utc"], reverse=True)
    return summarize(raw, user, rows, pagelog, tz_name, top)


def summarize(raw, user, rows, pagelog, tz_name, top):
    followers = num((user or {}).get("followers_count"))
    times = sorted(r["created_utc"] for r in rows if r["created_utc"])
    span = 0.0
    if len(times) >= 2:
        a, b = (dt.datetime.strptime(x, "%Y-%m-%d %H:%M") for x in (times[0], times[-1]))
        span = (b - a).total_seconds() / 86400
    rated = [r for r in rows if r["in_rates"]]
    no_views = [r for r in rated if r["views"] is None]
    excluded = [r for r in rows if not r["in_rates"]]
    types = {k: sum(r["type"] == k for r in rows) for k in ("original", "reply", "thread", "quote", "repost")}
    med_e, mean_e, _ = stats([r["engagements"] for r in rated])
    med_v, mean_v, n_v = stats([r["er_per_view_pct"] for r in rated])
    med_f, mean_f, n_f = stats([r["er_per_follower_pct"] for r in rated])
    best_day, _ = best_slot(rated, "weekday_local")
    best_hour, _ = best_slot(rated, "hour_local")
    summary = {"username": (user or {}).get("username") or raw.get("username"), "followers": followers,
               "posts_on_profile": (user or {}).get("statuses_count"), "posts_analyzed": len(rows),
               "first_post_utc": times[0] if times else "", "last_post_utc": times[-1] if times else "",
               "span_days": round(span, 2), "posts_per_day": round(len(rows) / max(span, 1.0), 2) if rows else None,
               "originals": types["original"], "replies": types["reply"], "threads": types["thread"],
               "quotes": types["quote"], "reposts": types["repost"], "posts_in_rates": len(rated),
               "median_engagements": med_e, "mean_engagements": mean_e,
               "median_er_per_view_pct": med_v, "mean_er_per_view_pct": mean_v,
               "median_er_per_follower_pct": med_f, "mean_er_per_follower_pct": mean_f,
               "best_weekday": best_day, "best_hour": best_hour, "time_zone": tz_name,
               "excluded": len(excluded)}
    groups = {}
    for dim in ("type", "media"):
        g = {}
        for r in rated:
            g.setdefault(r[dim], []).append(r)
        groups[dim] = {k: {"posts": len(v), "median_engagements": stats([x["engagements"] for x in v])[0],
                           "median_er_per_view_pct": stats([x["er_per_view_pct"] for x in v])[0],
                           "median_er_per_follower_pct": stats([x["er_per_follower_pct"] for x in v])[0]}
                       for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}
    top_eng = sorted(rated, key=lambda r: (r["engagements"] or 0), reverse=True)[:top]
    top_er = sorted([r for r in rated if r["er_per_view_pct"] is not None], key=lambda r: r["er_per_view_pct"], reverse=True)[:top]
    return {"summary": summary, "rows": rows, "pages": pagelog, "groups": groups, "top_eng": top_eng, "top_er": top_er,
            "excluded": excluded, "no_views": no_views, "n_view_rates": n_v, "started": raw.get("started")}


# ---------- output ----------

def fmt(v):
    return "" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def render_md(res):
    s = res["summary"]
    L = [f"# X account analytics: the latest {s['posts_analyzed']} posts", "",
         f"Run at {res['started']}. Data: the latest posts Desearch returned for one account "
         f"({len(res['pages'])} page(s) of `GET /twitter/user/posts`), not the full history.", "",
         f"Formula: {FORMULA}.", "",
         f"Rates use original posts, replies, threads and quotes. Reposts are left out: in testing, a repost row had 0 likes, the original post's repost count and a view count of its own, so its counts are not this account's engagement. "
         f"Posts with no view count stay in the per-follower rate and are left out of the per-view rate. Times are in {s['time_zone']}.", "",
         "## Account", "",
         "| followers | posts on profile | posts analyzed | first post (UTC) | last post (UTC) | posts per day |",
         "|---|---|---|---|---|---|",
         f"| {fmt(s['followers'])} | {fmt(s['posts_on_profile'])} | {s['posts_analyzed']} | {s['first_post_utc']} | {s['last_post_utc']} | {fmt(s['posts_per_day'])} |", "",
         f"Post types: {s['originals']} original, {s['replies']} replies, {s['threads']} thread replies to itself, {s['quotes']} quotes, {s['reposts']} reposts.", "",
         "## Engagement (posts in rates: %d)" % s["posts_in_rates"], "",
         "| metric | median | mean |", "|---|---|---|",
         f"| engagements per post | {fmt(s['median_engagements'])} | {fmt(s['mean_engagements'])} |",
         f"| ER per view % (n={res['n_view_rates']}) | {fmt(s['median_er_per_view_pct'])} | {fmt(s['mean_er_per_view_pct'])} |",
         f"| ER per follower % | {fmt(s['median_er_per_follower_pct'])} | {fmt(s['mean_er_per_follower_pct'])} |", "",
         f"Best weekday ({s['time_zone']}): {s['best_weekday'] or 'n/a'}. Best hour ({s['time_zone']}): {s['best_hour'] or 'n/a'}. "
         "Slots with at least 2 posts are compared by median engagements; with this few posts treat them as hints, not rules.", ""]
    for dim, title in (("type", "By post type"), ("media", "By media")):
        L += [f"## {title}", "", f"| {dim} | posts | median engagements | median ER per view % | median ER per follower % |",
              "|---|---|---|---|---|"]
        for k, g in res["groups"][dim].items():
            L.append(f"| {k} | {g['posts']} | {fmt(g['median_engagements'])} | {fmt(g['median_er_per_view_pct'])} | {fmt(g['median_er_per_follower_pct'])} |")
        L.append("")
    for key, title in (("top_eng", "Top posts by engagements"), ("top_er", "Top posts by ER per view")):
        L += [f"## {title}", "", "| date (UTC) | type | media | engagements | views | ER per view % | link |", "|---|---|---|---|---|---|---|"]
        for r in res[key]:
            L.append(f"| {r['created_utc']} | {r['type']} | {r['media']} | {fmt(r['engagements'])} | {fmt(r['views'])} | {fmt(r['er_per_view_pct'])} | {r['url']} |")
        L.append("")
    L += [f"## Exclusions ({len(res['excluded'])} posts left out of all rates, {len(res['no_views'])} more left out of the per-view rate)", ""]
    for r in res["excluded"]:
        L.append(f"- {r['created_utc']} {r['post_id']}: {r['excluded_reason']}")
    for r in res["no_views"]:
        L.append(f"- {r['created_utc']} {r['post_id']}: no view count (per-view rate only)")
    if not res["excluded"] and not res["no_views"]:
        L.append("- none")
    L += ["", "## Pages", "", "| page | status | cursor sent | returned | new | repeats | next cursor | seconds |", "|---|---|---|---|---|---|---|---|"]
    for p in res["pages"]:
        L.append(f"| {p['page']} | {p['status']} | {'yes' if p['cursor_sent'] else 'no'} | {p['returned']} | {p['new']} | {p['repeats']} | {'yes' if p['next_cursor'] else 'no'} | {fmt(p['seconds'])} |")
    return "\n".join(L) + "\n"


def write_outputs(res, out_prefix):
    os.makedirs(os.path.dirname(out_prefix) or ".", exist_ok=True)
    with open(out_prefix + "-posts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=POST_FIELDS); w.writeheader(); w.writerows(res["rows"])
    with open(out_prefix + "-summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS); w.writeheader(); w.writerow(res["summary"])
    with open(out_prefix + "-summary.md", "w", encoding="utf-8") as f:
        f.write(render_md(res))


def cost_totals(raw):
    hdr = [float(c["cost_usd"]) for c in raw.get("calls", []) if c.get("cost_usd") not in (None, "")]
    body = [float(c["body_cost_usd"]) for c in raw.get("calls", []) if c.get("body_cost_usd") not in (None, "")]
    return sum(hdr), len(hdr), sum(body), len(body)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", help="public X username (with or without @)")
    ap.add_argument("--pages", type=int, default=3, help=f"timeline pages to follow with next_cursor (1 to {MAX_PAGES})")
    ap.add_argument("--tz", default="UTC", help="IANA time zone for weekday and hour, e.g. UTC or Asia/Tbilisi")
    ap.add_argument("--top", type=int, default=5, help="how many top posts to list")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--from-raw", help="rebuild outputs from a saved raw JSON, no API calls")
    ap.add_argument("--raw-out", default=None, help="where to save raw responses (live mode)")
    ap.add_argument("--out", default=None, help="output prefix, default output/<username>")
    a = ap.parse_args(argv)
    try:
        ZoneInfo(a.tz)
    except Exception:
        ap.error(f"unknown time zone: {a.tz}")
    if a.from_raw:
        with open(a.from_raw, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        if not a.username:
            ap.error("--username or --from-raw is required")
        name = a.username.lstrip("@").strip()
        if not re.fullmatch(r"\w{1,15}", name):
            ap.error("an X username is 1 to 15 letters, digits or underscores")
        raw = asyncio.run(fetch(name, max(1, min(a.pages, MAX_PAGES)), read_key(a.key_file)))
        rp = a.raw_out or f"output/raw-{name}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        os.makedirs(os.path.dirname(rp) or ".", exist_ok=True)
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1, ensure_ascii=False)
        h, nh, b, nb = cost_totals(raw)
        print(f"raw saved: {rp}; calls={len(raw['calls'])} header_cost_usd={h:.5f} ({nh} calls) body_cost_usd={b:.5f} ({nb} calls)",
              file=sys.stderr)
    res = build(raw, a.tz, a.top)
    out = a.out or f"output/{res['summary']['username'] or 'account'}"
    write_outputs(res, out)
    if not res["rows"]:
        print("no posts returned; the CSV has headers only", file=sys.stderr)
    print(f"wrote {out}-posts.csv ({len(res['rows'])} posts), {out}-summary.csv, {out}-summary.md")
    return res


if __name__ == "__main__":
    main()
