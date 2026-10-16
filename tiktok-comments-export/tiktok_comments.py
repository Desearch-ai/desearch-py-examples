"""TikTok Comments Export: public comments Desearch returned for a few TikTok videos, as one clean CSV.

Made by Desearch (https://desearch.ai).

Live:     python tiktok_comments.py --videos 7166602323639225606 https://www.tiktok.com/video/7095449168591736070 [--count 8] [--pages 3]
Offline:  python tiktok_comments.py --from-raw path/to/your-saved-raw.json
Key: DESEARCH_API_KEY env var, or a file named by DESEARCH_KEY_FILE.
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, time

BASE = "https://api.desearch.ai"
FIELDS = ["video_id", "video_link", "comment_key", "viewer", "text", "likes", "reply_count",
          "create_time_utc", "tag", "page"]
TAGS = [("question", r"\?|\b(how|what|where|which|why|does|is it|can you)\b"),
        ("complaint", r"\b(bad|worst|broke|rash|burn|scam|hate|didn'?t work|waste|irritat)\w*"),
        ("praise", r"\b(love|great|amazing|best|obsessed|works|thank|perfect|holy grail)\w*")]


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def video_id(v):
    m = re.search(r"(\d{15,25})", v)
    if not m: raise SystemExit(f"not a TikTok video id or link: {v}")
    return m.group(1)


def comments(rec):
    b = rec["body"]
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("comments", "data", "results", "items"):
            if isinstance(b.get(k), list): return b[k]
    return []


def next_cursor(rec, offset):
    b = rec["body"]
    if isinstance(b, dict):
        for k in ("cursor", "next_cursor", "nextCursor"):
            if b.get(k): return str(b[k]), "returned"
    return str(offset), "offset"  # list body has no cursor field: send the running offset (worked in testing)


def call(s, vid, params, label):
    at, t0 = now(), time.time()
    try:
        r = s.get(f"{BASE}/desearch/tiktok/comments/{vid}", params=params, timeout=120)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: data = r.json()
        except ValueError: data = {"_text": r.text[:5000]}
    except Exception as e:
        status, hdr, data = None, {}, {"_error": repr(e)}
    rec = {"label": label, "video_id": vid, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"), "usage_count": hdr.get("x-desearch-usage-count"),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k == "date"}, "body": data}
    print(f"{at} {label:28s} {status} {rec['seconds']:6.2f}s n={len(comments(rec))} cost={rec['cost_usd']}", flush=True)
    return rec


def clean(t):
    t = re.sub(r"@[\w.]+", "[viewer]", t or "")
    t = re.sub(r"https?://\S+", "[link]", t)
    return " ".join(t.split()).replace("\u2014", ", ")


def to_utc(v):
    if isinstance(v, (int, float)): return dt.datetime.fromtimestamp(v, dt.timezone.utc)
    if isinstance(v, str) and v:
        if v.isdigit(): return dt.datetime.fromtimestamp(int(v), dt.timezone.utc)
        try: return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        except ValueError: return None
    return None


def comment_key(c):
    """Comment id if returned; the API returned none in testing, so fall back to a hash of author id + time + text."""
    if c.get("id"): return str(c["id"])
    a = (c.get("author") or {}).get("id") or ""
    return "h" + hashlib.sha256(f"{a}|{c.get('createTime')}|{c.get('text')}".encode()).hexdigest()[:12]


def tag(text):
    low = text.lower()
    return next((n for n, rx in TAGS if re.search(rx, low)), "")


def build(raw, out_prefix):
    viewers, rows, pagelog = {}, {}, []
    for rec in raw["calls"]:
        if rec.get("probe"): continue
        ids = [comment_key(c) for c in comments(rec)]
        prev = {k for k, r in rows.items() if r["video_id"] == rec["video_id"]}
        new = [i for i in ids if i not in prev]
        pagelog.append(f"{rec['video_id']} {rec['label']} cursor_sent={rec['params'].get('cursor')} returned={len(ids)} "
                       f"new={len(set(new))} repeats={len(ids) - len(set(new))}")
        for c in comments(rec):
            cid = comment_key(c)
            if cid in rows: continue
            a = (c.get("author") or {}).get("id") or (c.get("author") or {}).get("username") or cid
            viewers.setdefault(a, f"Viewer {len(viewers) + 1}")
            t, text = to_utc(c.get("createTime")), clean(c.get("text"))
            rc = c.get("replyCount", c.get("reply_count"))
            if rc is None and c.get("replies"): rc = len(c["replies"])  # replies was [] in testing, so left blank
            rows[cid] = {"video_id": rec["video_id"], "video_link": f"https://www.tiktok.com/video/{rec['video_id']}",
                         "comment_key": cid, "viewer": viewers[a], "text": text, "likes": c.get("likes"),
                         "reply_count": rc, "create_time_utc": t.strftime("%Y-%m-%d %H:%M") if t else "",
                         "tag": tag(text), "page": rec["label"].split()[-1]}
    data = list(rows.values())
    with open(out_prefix + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(data)
    lines = [f"# TikTok comments export, run at {raw['started']}", "", f"Unique comments: {len(data)}.", "",
             "## Pages", "", *[f"- {p}" for p in pagelog], "", "## Tags", ""]
    for n in ["question", "complaint", "praise", ""]:
        lines.append(f"- {n or 'untagged'}: {sum(r['tag'] == n for r in data)}")
    lines += ["", "## Top 10 by likes", "", "| # | video | likes | tag | text |", "|---|---|---|---|---|"]
    for i, r in enumerate(sorted(data, key=lambda r: -(r["likes"] or 0))[:10], 1):
        lines.append(f"| {i} | {r['video_id']} | {r['likes']} | {r['tag']} | {r['text'][:70].replace('|', '/')} |")
    open(out_prefix + "-summary.md", "w").write("\n".join(lines) + "\n")
    print("\n".join(pagelog)); print(f"wrote {out_prefix}.csv ({len(data)} rows) and {out_prefix}-summary.md")


def run_live(a):
    import requests
    key = os.environ.get("DESEARCH_API_KEY") or open(os.path.expanduser(os.environ["DESEARCH_KEY_FILE"])).read().strip()
    s = requests.Session(); s.headers["Authorization"] = key
    raw = {"count": a.count, "pages": a.pages, "started": now(), "calls": []}
    for v in a.videos:
        vid, cursor = video_id(v), None
        for i in range(a.pages):
            params = {"count": a.count}
            if cursor: params["cursor"] = cursor
            rec = call(s, vid, params, f"{vid[-6:]} p{i+1}"); raw["calls"].append(rec)
            if not comments(rec): break
            cursor, rec["cursor_kind"] = next_cursor(rec, a.count * (i + 1))
    if a.empty_check:
        rec = call(s, a.empty_check, {"count": 5}, "empty-result check"); rec["probe"] = True; raw["calls"].append(rec)
    os.makedirs("evidence", exist_ok=True)
    json.dump(raw, open(f"evidence/raw-{a.label}.json", "w"), indent=1, default=str)
    return raw


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", nargs="+", help="TikTok video ids or links")
    ap.add_argument("--count", type=int, default=8); ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--empty-check", help="optional made-up video id to see what an empty result costs")
    ap.add_argument("--label", default="run-1"); ap.add_argument("--from-raw")
    a = ap.parse_args()
    if not a.from_raw and not a.videos: ap.error("--videos or --from-raw is required")
    raw = json.load(open(a.from_raw)) if a.from_raw else run_live(a)
    os.makedirs("output", exist_ok=True)
    label = a.label if not a.from_raw else os.path.basename(a.from_raw)[4:-5]
    build(raw, f"output/tiktok-comments-{label}")
