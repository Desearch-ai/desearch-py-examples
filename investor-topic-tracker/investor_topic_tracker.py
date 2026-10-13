"""Investor Topic Tracker: public posts Desearch returned for each investor handle and one topic.

Made by Desearch (https://desearch.ai).

Live:     python investor_topic_tracker.py investors.json
Offline:  python investor_topic_tracker.py --from-raw evidence/raw-YYYY-MM-DD.json
"""
import argparse, csv, datetime as dt, json, os, re, statistics, sys, time

BASE = "https://api.desearch.ai"
COST_HEADERS = ("X-Desearch-Cost-Usd", "X-Desearch-Usage-Count", "X-Desearch-Service", "X-Desearch-Currency")


def now_local():
    return dt.datetime.now().astimezone()


def parse_created(s):
    for f in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime((s or "").replace("Z", "+0000"), f)
        except ValueError:
            pass
    return None


def fetch(cfg, key, count):
    import requests
    s = requests.Session(); s.headers["Authorization"] = key
    calls = []
    for h in cfg["handles"]:
        params = {"user": h, "query": cfg["query"], "count": count}
        at = now_local().isoformat(timespec="seconds"); t0 = time.time()
        r = s.get(f"{BASE}/twitter/post/user", params=params, timeout=120)
        try:
            body = r.json()
        except ValueError:
            body = {"_text": r.text[:500]}
        posts = body if isinstance(body, list) else (body.get("data") or body.get("tweets") or [])
        hdr = {k: r.headers.get(k) for k in COST_HEADERS}
        calls.append({"handle": h, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
                      "status": r.status_code, "headers": hdr, "posts": posts if isinstance(posts, list) else [],
                      "body_if_not_list": None if isinstance(body, list) else body})
        print(f"{at} {h:18s} {r.status_code} posts={len(calls[-1]['posts'])} cost={hdr['X-Desearch-Cost-Usd']}", flush=True)
    return calls


def topic_match(text, terms):
    t = (text or "").lower()
    return any(re.search(rf"\b{re.escape(x.lower())}", t) for x in terms)


def build(raw, outdir, evid="evidence"):
    date = raw["run_date"]; terms = raw["topic_terms"]
    run_ts = dt.datetime.fromisoformat(raw["run_started"])
    rows, posts_out = [], []
    for c in raw["calls"]:
        ps = []
        for p in c["posts"]:
            u = p.get("user") or {}
            author = (u.get("username") or "").lower()
            ts = parse_created(p.get("created_at"))
            text = p.get("text") or ""
            pid = p.get("id")
            ps.append({"handle": c["handle"], "post_id": pid, "created_utc": ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else "",
                       "_ts": ts, "author_is_handle": author == c["handle"].lower(),
                       "topic_term_in_text": topic_match(text, terms), "likes": p.get("like_count") or 0,
                       "url": f"https://x.com/i/status/{pid}" if pid else "",
                       "text": re.sub(r"\s+", " ", text).replace("\u2014", ", ")[:280]})
        returned_order_sorted = all(a["_ts"] and b["_ts"] and a["_ts"] >= b["_ts"] for a, b in zip(ps, ps[1:]))
        ps.sort(key=lambda r: r["_ts"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
        kept = [p for p in ps if p["author_is_handle"] and p["topic_term_in_text"]]
        latest = kept[0] if kept else None
        rows.append({"handle": c["handle"], "status": c["status"], "count_requested": c["params"]["count"],
                     "posts_returned": len(ps), "posts_with_topic_term": len(kept),
                     "latest_topic_post_utc": latest["created_utc"] if latest else "", "latest_topic_post_url": latest["url"] if latest else "",
                     "last_30_days": bool(latest and (run_ts - latest["_ts"]).days <= 30),
                     "median_likes": statistics.median([p["likes"] for p in kept]) if kept else "",
                     "returned_newest_first": returned_order_sorted,
                     "cost_usd": c["headers"].get("X-Desearch-Cost-Usd"), "usage_count": c["headers"].get("X-Desearch-Usage-Count"),
                     "fetched_at": c["at"]})
        for p in ps:
            p = dict(p); p.pop("_ts"); posts_out.append(p)
    rank = sorted([r for r in rows if r["posts_with_topic_term"]], key=lambda r: (-r["last_30_days"], r["latest_topic_post_utc"] == "", r["latest_topic_post_utc"]), reverse=False)
    rank.sort(key=lambda r: r["latest_topic_post_utc"], reverse=True)
    for i, r in enumerate(rank, 1):
        r["shortlist_label"] = f"Investor {chr(64+i)}"
    for r in rows:
        r.setdefault("shortlist_label", "")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "investors.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    os.makedirs(evid, exist_ok=True)
    with open(os.path.join(evid, "posts.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(posts_out[0]) if posts_out else ["handle"]); w.writeheader(); w.writerows(posts_out)
    cost = sum(float(r["cost_usd"] or 0) for r in rows)
    L = [f"# Investor Topic Tracker, {date}", "", "Made by [Desearch](https://desearch.ai).", "",
         f"Topic: {raw['topic']}. Query sent: `{raw['query']}`. Public posts Desearch returned for this handle and topic, "
         f"{len(rows)} handles, up to {raw['count']} posts each. A post counts here when the handle wrote it and the text contains a topic term "
         f"({', '.join(terms)}). Sorted by the newest such post. This is a reading list, not a view on anyone's plans.", "",
         "| # | Account | Posts with topic term / returned | Newest topic post (UTC) | Last 30 days | Median likes | Link |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank, 1):
        L.append(f"| {i} | Investor {chr(64+i)} | {r['posts_with_topic_term']} / {r['posts_returned']} | {r['latest_topic_post_utc']} | {'yes' if r['last_30_days'] else 'no'} | {r['median_likes']} | {r['latest_topic_post_url']} |")
    none = [r["handle"] for r in rows if not r["posts_with_topic_term"]]
    if none:
        L += ["", f"Accounts with no post containing a topic term: {len(none)} (names in investors.csv)."]
    L += ["", f"Calls: {len(rows)}. Read each post before you use it."]
    open(os.path.join(outdir, "shortlist.md"), "w").write("\n".join(L) + "\n")
    print(f"handles {len(rows)}, posts {len(posts_out)}, cost ${cost:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", default="investors.json")
    ap.add_argument("--from-raw"); ap.add_argument("--count", type=int, default=20); ap.add_argument("--out", default="output")
    a = ap.parse_args()
    if a.from_raw:
        raw = json.load(open(a.from_raw))
    else:
        key = os.environ.get("DESEARCH_API_KEY") or sys.exit("set DESEARCH_API_KEY")
        cfg = json.load(open(a.config)); started = now_local()
        raw = {"run_date": started.date().isoformat(), "run_started": started.isoformat(timespec="seconds"),
               "topic": cfg["topic"], "query": cfg["query"], "topic_terms": cfg["topic_terms"], "count": a.count,
               "calls": fetch(cfg, key, a.count)}
        os.makedirs("evidence", exist_ok=True)
        json.dump(raw, open(os.path.join("evidence", f"raw-{raw['run_date']}.json"), "w"), indent=1)
    build(raw, a.out)


if __name__ == "__main__":
    main()
