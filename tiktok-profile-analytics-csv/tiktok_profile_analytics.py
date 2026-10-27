"""TikTok Profile Analytics to CSV: per-post metrics and summary stats for a few public TikTok profiles.

Made by Desearch (https://desearch.ai).

Live:     python tiktok_profile_analytics.py --profiles BRAND_ONE BRAND_TWO [--count 12] [--pages 1]
Offline:  python tiktok_profile_analytics.py --from-raw samples/sample-raw.json
Key: read only from a key file (default ~/.desearch_api_key, or --key-file PATH). Never from the environment.
"""
import argparse, csv, re, datetime as dt, json, os, statistics as st, sys, time

BASE = "https://api.desearch.ai"
MAX_COUNT = 20  # TikTok endpoints bill per returned item, so keep each call small
DEFAULT_KEY_FILE = "~/.desearch_api_key"
POST_FIELDS = ["profile", "post_id", "url", "create_time_utc", "weekday", "hour_utc", "views", "likes",
               "comments", "shares", "saves", "engagement_rate_pct", "likely_pinned", "duration_s", "hashtags", "caption"]
SUMMARY_FIELDS = ["profile", "followers", "total_likes", "video_count", "posts_analyzed", "likely_pinned", "first_post_utc",
                  "last_post_utc", "posts_per_week", "cadence_window_days", "median_gap_days", "avg_views", "median_views",
                  "median_likes", "median_comments", "median_shares", "avg_engagement_rate_pct",
                  "median_engagement_rate_pct", "views_per_follower_pct", "best_weekday", "top_post_url"]


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


def call(session, path, params, label):
    at, t0 = now(), time.time()
    try:
        r = session.get(BASE + path, params=params, timeout=120)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: body = r.json()
        except ValueError: body = {"_text": r.text[:3000]}
    except Exception as e:  # network error: keep going, record it
        status, hdr, body = None, {}, {"_error": repr(e)}
    rec = {"label": label, "path": path, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"),
           "usage_count": hdr.get("x-desearch-usage-count"),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k == "date"}, "body": body}
    n = len(body) if isinstance(body, list) else (1 if status == 200 else 0)
    print(f"{at} {label:30s} {status} {rec['seconds']:6.2f}s items={n} cost={rec['cost_usd']}", file=sys.stderr, flush=True)
    return rec


def next_cursor(rec):
    return rec.get("headers", {}).get("x-desearch-next-cursor") or None


def posts_of(rec):
    b = rec.get("body")
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("posts", "data", "items", "results"):
            if isinstance(b.get(k), list): return b[k]
    return []


def utc(ts):
    try: return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
    except (TypeError, ValueError): return None


def num(v):
    return v if isinstance(v, (int, float)) else 0


def pinned_ids(posts):
    """Pinned videos come first in the list but are older than the feed after them.
    Mark the first k (k <= 3) posts as likely pinned when all of them are older than post k."""
    t = [num(p.get("createTime")) for p in posts]
    for k in (3, 2, 1):
        if len(t) > k and all(x < t[k] for x in t[:k]):
            return {str(p.get("id")) for p in posts[:k]}
    return set()


def post_row(profile, p):
    s = p.get("stats") or {}
    views, likes, com, sh, sv = (num(s.get(k)) for k in ("playCount", "digCount", "commentCount", "shareCount", "collectCount"))
    t = utc(p.get("createTime"))
    er = round(100 * (likes + com + sh) / views, 3) if views else None
    tags = [h if isinstance(h, str) else (h.get("name") or h.get("title") or "") for h in (p.get("hashtags") or [])]
    cap = " ".join(re.sub(r"@[\w.]+", "[account]", p.get("text") or "").split()).replace("\u2014", ", ")
    return {"profile": profile, "post_id": str(p.get("id", "")), "url": p.get("url", ""),
            "create_time_utc": t.strftime("%Y-%m-%d %H:%M") if t else "", "weekday": t.strftime("%a") if t else "",
            "hour_utc": t.hour if t else "", "views": views, "likes": likes, "comments": com, "shares": sh, "saves": sv,
            "engagement_rate_pct": er, "likely_pinned": False, "duration_s": round(num(p.get("videoDuration")) / 1000, 1) if p.get("videoDuration") else "",
            "hashtags": " ".join(t for t in tags if t), "caption": cap[:300]}


def summarize(profile, prof, rows):
    def med(k):
        v = [r[k] for r in rows if isinstance(r[k], (int, float))]
        return round(st.median(v), 3) if v else None
    feed = [r for r in rows if not r["likely_pinned"]] or rows  # cadence ignores pinned videos
    times = sorted(dt.datetime.strptime(r["create_time_utc"], "%Y-%m-%d %H:%M") for r in feed if r["create_time_utc"])
    ppw = gap = None; span = 0
    if len(times) >= 2:
        span = (times[-1] - times[0]).total_seconds() / 86400
        ppw = round(len(times) * 7 / max(span, 7), 2)  # window floored at 7 days so a burst does not read as hundreds/week
        gap = round(st.median([(b - a).total_seconds() / 86400 for a, b in zip(times, times[1:])]), 2)
    ers = [r["engagement_rate_pct"] for r in rows if r["engagement_rate_pct"] is not None]
    by_day = {}
    for r in rows:
        if r["weekday"]: by_day.setdefault(r["weekday"], []).append(r["views"])
    best = max(by_day, key=lambda d: st.median(by_day[d])) if by_day else ""
    if best: best = f"{best} (median views {int(st.median(by_day[best]))}, n={len(by_day[best])})"
    views = [r["views"] for r in rows]
    fol = (prof or {}).get("followers")
    top = max(rows, key=lambda r: r["views"])["url"] if rows else ""
    return {"profile": profile, "followers": fol, "total_likes": (prof or {}).get("heart"),
            "video_count": (prof or {}).get("videoCount"), "posts_analyzed": len(rows), "likely_pinned": sum(bool(r["likely_pinned"]) for r in rows),
            "first_post_utc": times[0].strftime("%Y-%m-%d") if times else "",
            "last_post_utc": times[-1].strftime("%Y-%m-%d") if times else "",
            "posts_per_week": ppw, "cadence_window_days": round(span, 1), "median_gap_days": gap,
            "avg_views": round(st.mean(views)) if views else None, "median_views": med("views"),
            "median_likes": med("likes"), "median_comments": med("comments"), "median_shares": med("shares"),
            "avg_engagement_rate_pct": round(st.mean(ers), 3) if ers else None,
            "median_engagement_rate_pct": round(st.median(ers), 3) if ers else None,
            "views_per_follower_pct": round(100 * st.median(views) / fol, 2) if fol and views else None,
            "best_weekday": best, "top_post_url": top}


def build(raw, out_prefix):
    profiles, posts, pagelog = {}, {}, []
    for rec in raw["calls"]:
        if rec.get("probe"): continue
        name = rec["profile"]
        if rec["kind"] == "profile":
            profiles[name] = rec["body"] if rec["status"] == 200 and isinstance(rec["body"], dict) else None
            continue
        seen = posts.setdefault(name, {})
        got = posts_of(rec)
        new = [p for p in got if str(p.get("id")) not in seen]
        pagelog.append(f"{name} {rec['label']} cursor_sent={'yes' if 'cursor' in rec['params'] else 'no'} returned={len(got)} new={len(new)} repeats={len(got) - len(new)}")
        pins = pinned_ids(got) if "cursor" not in rec["params"] else set()
        for p in new:
            row = post_row(name, p); row["likely_pinned"] = str(p.get("id")) in pins
            seen[str(p.get("id"))] = row
    allrows, summ = [], []
    for name in dict.fromkeys(list(profiles) + list(posts)):
        rows = sorted(posts.get(name, {}).values(), key=lambda r: r["create_time_utc"], reverse=True)
        if not rows and not profiles.get(name):
            print(f"warning: no data for '{name}' (profile not found or empty), skipped", file=sys.stderr)
            continue
        allrows += rows
        summ.append(summarize(name, profiles.get(name), rows))
    os.makedirs(os.path.dirname(out_prefix) or ".", exist_ok=True)
    for path, fields, data in [(out_prefix + "-posts.csv", POST_FIELDS, allrows), (out_prefix + "-summary.csv", SUMMARY_FIELDS, summ)]:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(data)
    lines = [f"# TikTok profile analytics, run at {raw['started']}", "",
             "Engagement rate = (likes + comments + shares) / views, per post. Cadence uses the posts Desearch returned.", "",
             "Posts/week and median gap skip videos that look pinned (older posts listed first).", "",
             "| profile | followers | posts | posts/week | median views | median ER % | best weekday |", "|---|---|---|---|---|---|---|"]
    for s in summ:
        lines.append(f"| {s['profile']} | {s['followers']} | {s['posts_analyzed']} | {s['posts_per_week']} | {s['median_views']} | {s['median_engagement_rate_pct']} | {s['best_weekday']} |")
    lines += ["", "## Pages", "", *[f"- {p}" for p in pagelog]]
    open(out_prefix + "-summary.md", "w").write("\n".join(lines) + "\n")
    return allrows, summ, pagelog


def live(args):
    import requests
    s = requests.Session(); s.headers["Authorization"] = read_key(args.key_file)
    count = max(1, min(args.count, MAX_COUNT))
    raw = {"started": now(), "count": count, "calls": []}
    for name in args.profiles:
        name = name.lstrip("@").strip()
        if not name: continue
        r = call(s, f"/desearch/tiktok/profile/{name}", {}, f"{name} profile"); r.update(profile=name, kind="profile")
        raw["calls"].append(r)
        if r["status"] != 200:
            print(f"profile '{name}' returned {r['status']}, not fetching posts", file=sys.stderr); continue
        cursor = None
        for page in range(1, args.pages + 1):
            params = {"count": count}
            if cursor is not None: params["cursor"] = cursor
            r = call(s, f"/desearch/tiktok/profile/{name}/posts", params, f"{name} posts p{page}")
            r.update(profile=name, kind="posts"); raw["calls"].append(r)
            got = posts_of(r)
            if r["status"] != 200 or not got: break
            cursor = next_cursor(r)
            if cursor is None: break
    return raw


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", nargs="+", help="public TikTok usernames (with or without @)")
    ap.add_argument("--count", type=int, default=12, help=f"posts per call, capped at {MAX_COUNT}")
    ap.add_argument("--pages", type=int, default=1, help="pages per profile (each page bills per item)")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--from-raw", help="rebuild CSVs from a saved raw JSON, no API calls")
    ap.add_argument("--raw-out", default=None, help="where to save raw responses (live mode)")
    ap.add_argument("--out", default="output/tiktok-profiles")
    a = ap.parse_args(argv)
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        if not a.profiles: ap.error("--profiles or --from-raw is required")
        raw = live(a)
        rp = a.raw_out or f"output/raw-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        os.makedirs(os.path.dirname(rp) or ".", exist_ok=True)
        json.dump(raw, open(rp, "w"), indent=1); print(f"raw saved: {rp}", file=sys.stderr)
        costs = [float(c["cost_usd"]) for c in raw["calls"] if c.get("cost_usd")]
        print(f"calls={len(raw['calls'])} header_cost_usd={sum(costs):.5f}", file=sys.stderr)
    rows, summ, _ = build(raw, a.out)
    if not rows:
        print("no posts returned for any profile; CSVs have headers only", file=sys.stderr)
    print(f"wrote {a.out}-posts.csv ({len(rows)} posts), {a.out}-summary.csv ({len(summ)} profiles), {a.out}-summary.md")


if __name__ == "__main__":
    main()
