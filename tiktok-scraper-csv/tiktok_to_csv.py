"""TikTok Scraper to CSV: public TikToks Desearch returned for a keyword and a hashtag, as one clean CSV.

Made by Desearch (https://desearch.ai).

Live:     python tiktok_to_csv.py --keyword "skincare routine" --hashtag skincare [--count 20] [--pages 2]
Offline:  python tiktok_to_csv.py --from-raw evidence/raw-run-1.json
Key: DESEARCH_API_KEY env var, or a file named by DESEARCH_KEY_FILE.
"""
import argparse, csv, datetime as dt, json, os, re, statistics, time

BASE = "https://api.desearch.ai"
FIELDS = ["video_id", "link", "source", "creator", "caption", "create_time_utc", "posting_hour_utc",
          "views", "likes", "comments", "shares", "saves", "engagement_rate", "duration_s"]


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def call(s, method, path, label, params=None, body=None):
    at, t0 = now(), time.time()
    try:
        r = s.request(method, BASE + path, params=params, json=body, timeout=120)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: data = r.json()
        except ValueError: data = {"_text": r.text[:5000]}
    except Exception as e:
        status, hdr, data = None, {}, {"_error": repr(e)}
    rec = {"label": label, "method": method, "path": path, "params": params, "body_sent": body, "at": at,
           "seconds": round(time.time() - t0, 2), "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"),
           "usage_count": hdr.get("x-desearch-usage-count"),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k == "date"}, "body": data}
    print(f"{at} {label:24s} {status} {rec['seconds']:6.2f}s n={len(posts(rec))} cost={rec['cost_usd']}", flush=True)
    return rec


def posts(rec):
    b = rec["body"]
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("posts", "data", "results", "items"):
            if isinstance(b.get(k), list): return b[k]
    return []


def to_utc(v):
    if isinstance(v, (int, float)): return dt.datetime.fromtimestamp(v, dt.timezone.utc)
    if isinstance(v, str) and v:
        try: return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError: return None
    return None


def clean(t):
    """Captions keep their words; account names, contact handles and links are masked."""
    t = re.sub(r"@[\w.]+", "[account]", t or "")
    t = re.sub(r"(?i)\b(ig|insta|instagram|yt|snap)\s*:\s*\S+", r"\1: [account]", t)
    t = re.sub(r"https?://\S+", "[link]", t)
    return " ".join(t.split()).replace("\u2014", ", ")


def row(p, source, creators):
    st = p.get("stats") or {}
    a = (p.get("author") or {}).get("id") or (p.get("author") or {}).get("username") or "?"
    creators.setdefault(a, f"Creator {len(creators) + 1}")
    t = to_utc(p.get("createTime"))
    views = st.get("playCount")
    eng = sum(x or 0 for x in (st.get("digCount"), st.get("commentCount"), st.get("shareCount")))
    vid = str(p.get("id") or "")
    return {"video_id": vid, "link": f"https://www.tiktok.com/video/{vid}" if vid else "",
            "source": source, "creator": creators[a],
            "caption": clean(p.get("text")),
            "create_time_utc": t.strftime("%Y-%m-%d %H:%M") if t else "", "posting_hour_utc": t.hour if t else "",
            "views": views, "likes": st.get("digCount"), "comments": st.get("commentCount"),
            "shares": st.get("shareCount"), "saves": st.get("collectCount"),
            "engagement_rate": round(eng / views, 4) if views else "",
            "duration_s": round(p["videoDuration"] / 1000, 1) if isinstance(p.get("videoDuration"), int) else ""}


def build(raw, out_prefix):
    creators, rows, seen = {}, {}, {}
    for rec in raw["calls"]:
        if rec.get("probe"): continue
        src = "search" if rec["path"].endswith("/tiktok/search") else "hashtag"
        for p in posts(rec):
            r = row(p, src, creators)
            if not r["video_id"]: continue
            if r["video_id"] in rows:
                if src not in rows[r["video_id"]]["source"]: rows[r["video_id"]]["source"] += "+" + src
                seen[r["video_id"]] += 1
                continue
            rows[r["video_id"]], seen[r["video_id"]] = r, 1
    data = list(rows.values())
    with open(out_prefix + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(data)
    views = [r["views"] for r in data if isinstance(r["views"], int)]
    top = sorted([r for r in data if r["engagement_rate"] != ""], key=lambda r: -r["engagement_rate"])[:10]
    hours = {}
    for r in data:
        if r["posting_hour_utc"] != "": hours[r["posting_hour_utc"]] = hours.get(r["posting_hour_utc"], 0) + 1
    returned = sum(len(posts(c)) for c in raw["calls"] if not c.get("probe"))
    lines = [f"# TikTok export: keyword \"{raw['keyword']}\", hashtag #{raw['hashtag']}", "",
             f"Run at {raw['started']}. Rows returned {returned}, unique videos {len(data)} "
             f"(search {sum('search' in r['source'] for r in data)}, hashtag {sum('hashtag' in r['source'] for r in data)}, both {sum('+' in r['source'] for r in data)}).",
             f"Median views: {statistics.median(views) if views else 'n/a'}.", "",
             "## Top 10 by engagement rate ((likes + comments + shares) / views)", "",
             "| # | video | source | views | rate | caption |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(top, 1):
        lines.append(f"| {i} | {r['link']} | {r['source']} | {r['views']} | {r['engagement_rate']} | {r['caption'][:60].replace('|', '/')} |")
    lines += ["", "## Posting hour spread (UTC)", "", "| hour | videos |", "|---|---|"]
    lines += [f"| {h:02d} | {hours[h]} |" for h in sorted(hours)]
    open(out_prefix + "-summary.md", "w").write("\n".join(lines) + "\n")
    print(f"wrote {out_prefix}.csv ({len(data)} rows) and {out_prefix}-summary.md")


def run_live(a):
    import requests
    key = os.environ.get("DESEARCH_API_KEY") or open(os.path.expanduser(os.environ["DESEARCH_KEY_FILE"])).read().strip()
    s = requests.Session(); s.headers["Authorization"] = key
    raw = {"keyword": a.keyword, "hashtag": a.hashtag, "count": a.count, "started": now(), "calls": []}
    cursor = None
    for i in range(a.pages):
        body = {"query": a.keyword, "count": a.count}
        if cursor: body["cursor"] = cursor
        rec = call(s, "POST", "/desearch/tiktok/search", f"search p{i+1}", body=body); raw["calls"].append(rec)
        cursor = next_cursor(rec, a.count * (i + 1))
        if not posts(rec): break
    cursor = None
    for i in range(a.pages):
        params = {"count": a.count}
        if cursor: params["cursor"] = cursor
        rec = call(s, "GET", f"/desearch/tiktok/hashtag/{a.hashtag}", f"hashtag p{i+1}", params=params); raw["calls"].append(rec)
        cursor = next_cursor(rec, a.count * (i + 1))
        if not posts(rec): break
    if a.empty_check:
        rec = call(s, "GET", f"/desearch/tiktok/hashtag/{a.empty_check}", "empty-result check", params={"count": 5})
        rec["probe"] = True; raw["calls"].append(rec)
    os.makedirs("evidence", exist_ok=True)
    json.dump(raw, open(f"evidence/raw-{a.label}.json", "w"), indent=1, default=str)
    return raw


def next_cursor(rec, offset):
    b = rec["body"]
    if isinstance(b, dict):
        for k in ("cursor", "next_cursor", "nextCursor"):
            if b.get(k): return str(b[k])
    return str(offset)  # no cursor in a list body: try the offset (worked in testing, see report)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword"); ap.add_argument("--hashtag")
    ap.add_argument("--count", type=int, default=20); ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--empty-check", help="optional made-up hashtag to see what an empty result costs")
    ap.add_argument("--label", default="run-1"); ap.add_argument("--from-raw")
    a = ap.parse_args()
    raw = json.load(open(a.from_raw)) if a.from_raw else run_live(a)
    os.makedirs("output", exist_ok=True)
    build(raw, f"output/tiktok-{(raw['hashtag'] or 'export')}-{a.label if not a.from_raw else os.path.basename(a.from_raw)[4:-5]}")
