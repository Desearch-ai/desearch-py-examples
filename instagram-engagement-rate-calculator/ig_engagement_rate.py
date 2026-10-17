"""Instagram Engagement Rate Calculator: engagement rate of one public Instagram account from its recent posts,
with the formula shown and a split by format (image, carousel, video/reel).

Made by Desearch (https://desearch.ai).

Formula, per post:   engagement rate % = (likes + comments) / followers x 100
Account rate:        the mean of the per-post rates (same as total likes + comments / posts / followers x 100).
The median is shown next to it, so one viral post cannot hide a quiet feed.

Live:     python ig_engagement_rate.py --accounts BRAND_ONE [PEER_ONE PEER_TWO] [--count 12]
Offline:  python ig_engagement_rate.py --from-raw samples/sample-raw.json
Key: read only from a key file (--key-file PATH, default below). Never from the environment.
"""
import argparse, csv, datetime as dt, json, os, re, statistics as st, sys, time

BASE = "https://api.desearch.ai"
MAX_COUNT = 20  # Instagram endpoints bill per returned item, so keep each call small
DEFAULT_KEY_FILE = "~/.desearch_api_key"
FRESH_HOURS = 24  # posts younger than this are still collecting likes, so they are left out of the rate
FORMULA = "engagement rate % = (likes + comments) / followers x 100, per post; account rate = mean of the post rates"
POST_FIELDS = ["account", "shortcode", "create_time_utc", "format", "raw_media_type", "likes", "comments", "views",
               "followers", "engagement_rate_pct", "engagement_per_view_pct", "likes_hidden", "likely_pinned",
               "under_24h", "used_in_rate", "caption"]
SUMMARY_FIELDS = ["account", "followers", "posts_returned", "posts_used", "skipped_pinned", "skipped_under_24h",
                  "skipped_hidden_likes", "first_post_utc", "last_post_utc", "avg_likes", "avg_comments",
                  "engagement_rate_pct", "median_engagement_rate_pct", "min_post_rate_pct", "max_post_rate_pct",
                  "best_format", "formula"]
FORMAT_FIELDS = ["account", "format", "posts", "share_of_posts_pct", "avg_likes", "avg_comments", "avg_views",
                 "engagement_rate_pct", "median_engagement_rate_pct"]
FORMAT_MAP = {"image": "image", "photo": "image", "graphimage": "image", "1": "image",
              "carousel": "carousel", "carousel_album": "carousel", "sidecar": "carousel", "graphsidecar": "carousel", "8": "carousel",
              "video": "video/reel", "reel": "video/reel", "reels": "video/reel", "clips": "video/reel", "graphvideo": "video/reel", "2": "video/reel"}


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
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"), "usage_count": hdr.get("x-desearch-usage-count"),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k == "date"}, "body": body}
    n = len(body) if isinstance(body, list) else (1 if status == 200 else 0)
    print(f"{at} {label:28s} {status} {rec['seconds']:6.2f}s items={n} cost={rec['cost_usd']}", file=sys.stderr, flush=True)
    return rec


def posts_of(rec):
    b = rec.get("body")
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("posts", "data", "items", "results"):
            if isinstance(b.get(k), list): return b[k]
    return []


def cursor_of(rec):
    b = rec.get("body")
    if isinstance(b, dict):
        for k in ("cursor", "next_cursor", "nextCursor", "end_cursor"):
            if b.get(k): return str(b[k])
    return None


def parse_time(v):
    """createTime can be a Unix integer, a numeric string or an ISO string."""
    if v is None or v == "": return None
    try: return dt.datetime.fromtimestamp(int(float(v)), dt.timezone.utc)
    except (TypeError, ValueError): pass
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def fmt_of(p):
    raw = str(p.get("mediaType") or "").strip().lower()
    f = FORMAT_MAP.get(raw)
    if f is None:
        f = "carousel" if p.get("children") else (raw or "unknown")
    return f, raw


def count_or_none(v):
    """Hidden likes come back as null or a negative number."""
    return v if isinstance(v, (int, float)) and v >= 0 else None


def pinned_ids(posts):
    """Pinned posts come first but are older than the post after them. Mark the first k (k <= 3) as likely pinned
    when all of them are older than post k."""
    t = [parse_time(p.get("createTime")) for p in posts]
    t = [x.timestamp() if x else 0 for x in t]
    for k in (3, 2, 1):
        if len(t) > k and all(x < t[k] for x in t[:k]):
            return {str(p.get("id") or p.get("shortcode")) for p in posts[:k]}
    return set()


def post_row(account, followers, p, ref_time=None):
    s = p.get("stats") or {}
    likes, com = count_or_none(s.get("likeCount")), count_or_none(s.get("commentCount"))
    views = count_or_none(s.get("viewCount")) or count_or_none(s.get("playCount"))
    t = parse_time(p.get("createTime"))
    f, raw = fmt_of(p)
    hidden = likes is None
    er = round(100 * (likes + (com or 0)) / followers, 4) if followers and not hidden else None
    epv = round(100 * (likes + (com or 0)) / views, 3) if views and not hidden else None
    ref = ref_time or dt.datetime.now(dt.timezone.utc)
    fresh = bool(t and (ref - t).total_seconds() < FRESH_HOURS * 3600)
    cap = " ".join(re.sub(r"@[\w.]+", "[account]", p.get("caption") or "").split()).replace("\u2014", ", ")
    return {"account": account, "shortcode": p.get("shortcode") or str(p.get("id", "")),
            "create_time_utc": t.strftime("%Y-%m-%d %H:%M") if t else "", "format": f, "raw_media_type": raw,
            "likes": likes if likes is not None else "", "comments": com if com is not None else "",
            "views": views if views is not None else "", "followers": followers if followers else "",
            "engagement_rate_pct": er, "engagement_per_view_pct": epv, "likes_hidden": hidden,
            "likely_pinned": False, "under_24h": fresh, "used_in_rate": False, "caption": cap[:200]}


def _mean(v, nd=4): return round(st.mean(v), nd) if v else None
def _median(v, nd=4): return round(st.median(v), nd) if v else None


def summarize(account, followers, rows):
    used = [r for r in rows if r["used_in_rate"]]
    ers = [r["engagement_rate_pct"] for r in used]
    times = sorted(r["create_time_utc"] for r in rows if r["create_time_utc"])
    formats = []
    for f in sorted({r["format"] for r in used}):
        g = [r for r in used if r["format"] == f]
        gv = [r["views"] for r in g if isinstance(r["views"], (int, float))]
        formats.append({"account": account, "format": f, "posts": len(g),
                        "share_of_posts_pct": round(100 * len(g) / len(used), 1),
                        "avg_likes": _mean([r["likes"] for r in g], 1), "avg_comments": _mean([r["comments"] or 0 for r in g], 1),
                        "avg_views": _mean(gv, 1) if gv else "",
                        "engagement_rate_pct": _mean([r["engagement_rate_pct"] for r in g]),
                        "median_engagement_rate_pct": _median([r["engagement_rate_pct"] for r in g])})
    best = max(formats, key=lambda x: x["engagement_rate_pct"]) if formats else None
    summ = {"account": account, "followers": followers, "posts_returned": len(rows), "posts_used": len(used),
            "skipped_pinned": sum(r["likely_pinned"] for r in rows),
            "skipped_under_24h": sum(r["under_24h"] and not r["likely_pinned"] for r in rows),
            "skipped_hidden_likes": sum(r["likes_hidden"] and not r["likely_pinned"] and not r["under_24h"] for r in rows),
            "first_post_utc": times[0][:10] if times else "", "last_post_utc": times[-1][:10] if times else "",
            "avg_likes": _mean([r["likes"] for r in used], 1), "avg_comments": _mean([r["comments"] or 0 for r in used], 1),
            "engagement_rate_pct": _mean(ers), "median_engagement_rate_pct": _median(ers),
            "min_post_rate_pct": min(ers) if ers else None, "max_post_rate_pct": max(ers) if ers else None,
            "best_format": f"{best['format']} ({best['engagement_rate_pct']} %, n={best['posts']})" if best and len(formats) > 1 else "",
            "formula": FORMULA}
    return summ, formats


def svg_chart(formats, path):
    """Dependency-free bar chart: engagement rate by format, one group per account."""
    if not formats: return
    accts = list(dict.fromkeys(f["account"] for f in formats))
    kinds = ["image", "carousel", "video/reel"] + sorted({f["format"] for f in formats} - {"image", "carousel", "video/reel"})
    colors = ["#4C78A8", "#F58518", "#54A24B", "#B279A2", "#9D755D"]
    top = max(f["engagement_rate_pct"] or 0 for f in formats) or 1
    bw, gap, h, left = 28, 30, 220, 50
    width = left + len(accts) * (len(kinds) * bw + gap) + 160
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h + 70}" font-family="sans-serif" font-size="11">',
           f'<text x="{left}" y="16" font-size="13">Engagement rate % by format, (likes + comments) / followers x 100</text>']
    for i, a in enumerate(accts):
        x0 = left + i * (len(kinds) * bw + gap)
        for j, k in enumerate(kinds):
            m = next((f for f in formats if f["account"] == a and f["format"] == k), None)
            if not m or m["engagement_rate_pct"] is None: continue
            bh = h * m["engagement_rate_pct"] / top
            x, y = x0 + j * bw, 30 + h - bh
            out.append(f'<rect x="{x}" y="{y:.1f}" width="{bw - 4}" height="{bh:.1f}" fill="{colors[j % len(colors)]}"/>')
            out.append(f'<text x="{x}" y="{y - 3:.1f}">{m["engagement_rate_pct"]:.2f}</text>')
        out.append(f'<text x="{x0}" y="{h + 48}">{a}</text>')
    for j, k in enumerate(kinds):
        lx = width - 140
        out.append(f'<rect x="{lx}" y="{30 + j * 18}" width="10" height="10" fill="{colors[j % len(colors)]}"/><text x="{lx + 16}" y="{39 + j * 18}">{k}</text>')
    out.append("</svg>")
    open(path, "w").write("\n".join(out) + "\n")


def build(raw, out_prefix, include_pinned=False, include_fresh=False):
    ref = parse_time(raw.get("started")) or dt.datetime.now(dt.timezone.utc)
    profiles, posts, pagelog, order = {}, {}, [], []
    for rec in raw["calls"]:
        if rec.get("probe"): continue
        name = rec["account"]
        if name not in order: order.append(name)
        if rec["kind"] == "profile":
            profiles[name] = rec["body"] if rec["status"] == 200 and isinstance(rec["body"], dict) else None
            continue
        seen = posts.setdefault(name, {})
        got = posts_of(rec)
        new = [p for p in got if str(p.get("id") or p.get("shortcode")) not in seen]
        pagelog.append(f"{rec['label']}: requested {rec['params'].get('count')}, returned {len(got)}, new {len(new)}")
        pins = pinned_ids(got) if "cursor" not in rec["params"] else set()
        fol = (profiles.get(name) or {}).get("followers")
        for p in new:
            key = str(p.get("id") or p.get("shortcode"))
            row = post_row(name, fol, p, ref)
            row["likely_pinned"] = key in pins
            row["used_in_rate"] = (row["engagement_rate_pct"] is not None and (include_pinned or not row["likely_pinned"])
                                   and (include_fresh or not row["under_24h"]))
            seen[key] = row
    allrows, summ, fmts = [], [], []
    for name in order:
        rows = sorted(posts.get(name, {}).values(), key=lambda r: r["create_time_utc"], reverse=True)
        prof = profiles.get(name)
        if not prof:
            print(f"warning: no profile for '{name}' (not found, private or failed), skipped", file=sys.stderr)
            continue
        if not prof.get("followers"):
            print(f"warning: '{name}' has no follower count, so no rate can be computed", file=sys.stderr)
        allrows += rows
        s, f = summarize(name, prof.get("followers"), rows)
        summ.append(s); fmts += f
    os.makedirs(os.path.dirname(out_prefix) or ".", exist_ok=True)
    for path, fields, data in [(out_prefix + "-posts.csv", POST_FIELDS, allrows), (out_prefix + "-summary.csv", SUMMARY_FIELDS, summ),
                               (out_prefix + "-formats.csv", FORMAT_FIELDS, fmts)]:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(data)
    svg_chart(fmts, out_prefix + "-formats.svg")
    lines = [f"# Instagram engagement rate, run at {raw['started']}", "",
             "**Formula.** Per post: engagement rate % = (likes + comments) / followers x 100. "
             "Account rate = the mean of the post rates. The median is shown next to it.", "",
             f"Based on the latest posts Desearch returned for each account. Left out of the rate: likely pinned posts "
             f"(listed first but older), posts under {FRESH_HOURS} hours old, and posts with hidden likes. "
             "Saves and shares are not in the data, so this is a likes plus comments rate. "
             "Average views are shown only for posts where Desearch returned a view count.", "",
             "| account | followers | posts used / returned | engagement rate % | median % | range % | best format |",
             "|---|---|---|---|---|---|---|"]
    for s in summ:
        lines.append(f"| {s['account']} | {s['followers']} | {s['posts_used']} / {s['posts_returned']} | {s['engagement_rate_pct']} | "
                     f"{s['median_engagement_rate_pct']} | {s['min_post_rate_pct']} to {s['max_post_rate_pct']} | {s['best_format']} |")
    lines += ["", "## By format", "", "| account | format | posts | avg likes | avg comments | avg views | engagement rate % | median % |",
              "|---|---|---|---|---|---|---|---|"]
    for f in fmts:
        lines.append(f"| {f['account']} | {f['format']} | {f['posts']} | {f['avg_likes']} | {f['avg_comments']} | {f['avg_views']} | "
                     f"{f['engagement_rate_pct']} | {f['median_engagement_rate_pct']} |")
    lines += ["", "## Calls", "", *[f"- {p}" for p in pagelog]]
    open(out_prefix + "-summary.md", "w").write("\n".join(lines) + "\n")
    return allrows, summ, fmts


def live(args):
    import requests
    s = requests.Session(); s.headers["Authorization"] = read_key(args.key_file)
    count = max(1, min(args.count, MAX_COUNT))
    raw = {"started": now(), "count": count, "calls": []}
    for name in args.accounts:
        name = name.lstrip("@").strip()
        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", name):
            print(f"skipping '{name}': not a valid Instagram username (no call made)", file=sys.stderr); continue
        r = call(s, f"/desearch/instagram/profile/{name}", {}, f"{name} profile"); r.update(account=name, kind="profile")
        raw["calls"].append(r)
        if r["status"] != 200 or not isinstance(r["body"], dict):
            print(f"profile '{name}' returned {r['status']}, not fetching posts", file=sys.stderr); continue
        if r["body"].get("private"):
            print(f"'{name}' is private, not fetching posts", file=sys.stderr); continue
        cursor = None
        for page in range(1, args.pages + 1):
            params = {"count": count}
            if cursor: params["cursor"] = cursor
            r = call(s, f"/desearch/instagram/profile/{name}/posts", params, f"{name} posts p{page}")
            r.update(account=name, kind="posts"); raw["calls"].append(r)
            cursor = cursor_of(r)
            if r["status"] != 200 or not posts_of(r) or not cursor: break
    return raw


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accounts", nargs="+", help="one public Instagram username, optionally plus peers (with or without @)")
    ap.add_argument("--count", type=int, default=12, help=f"recent posts per account, capped at {MAX_COUNT}")
    ap.add_argument("--pages", type=int, default=1, help="pages per account, only used when a cursor comes back")
    ap.add_argument("--include-pinned", action="store_true", help="count likely pinned posts in the rate")
    ap.add_argument("--include-fresh", action="store_true", help=f"count posts under {FRESH_HOURS} hours old in the rate")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    ap.add_argument("--from-raw", help="rebuild outputs from a saved raw JSON, no API calls")
    ap.add_argument("--raw-out", default=None, help="where to save raw responses (live mode)")
    ap.add_argument("--out", default="output/ig-engagement")
    a = ap.parse_args(argv)
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        if not a.accounts: ap.error("--accounts or --from-raw is required")
        raw = live(a)
        rp = a.raw_out or f"output/raw-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        os.makedirs(os.path.dirname(rp) or ".", exist_ok=True)
        json.dump(raw, open(rp, "w"), indent=1); print(f"raw saved: {rp}", file=sys.stderr)
        costs = [float(c["cost_usd"]) for c in raw["calls"] if c.get("cost_usd")]
        print(f"calls={len(raw['calls'])} header_cost_usd={sum(costs):.5f}", file=sys.stderr)
    rows, summ, fmts = build(raw, a.out, a.include_pinned, a.include_fresh)
    for s in summ:
        print(f"{s['account']}: engagement rate {s['engagement_rate_pct']} % (median {s['median_engagement_rate_pct']} %) "
              f"over {s['posts_used']} of {s['posts_returned']} posts; best format {s['best_format'] or 'n/a'}")
    print(f"wrote {a.out}-posts.csv ({len(rows)} posts), {a.out}-summary.csv ({len(summ)} accounts), "
          f"{a.out}-formats.csv ({len(fmts)} rows), {a.out}-formats.svg, {a.out}-summary.md")


if __name__ == "__main__":
    main()
