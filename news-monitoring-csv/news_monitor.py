"""News Monitoring to CSV: topics in, one deduped CSV of new news items out.

Made by Desearch (https://desearch.ai).

Live:     python news_monitor.py --topics "open source llm" "ai chip export rules"
Offline:  python news_monitor.py --from-raw samples/raw-sample.json
Key: read from the key file named by --key-file (default ~/.saba/desearch_api_key). Never from the environment.
"""
import argparse, csv, datetime as dt, hashlib, json, os, re, time
from urllib.parse import urlparse, urlunparse

BASE = "https://api.desearch.ai"
FIELDS = ["topic", "kind", "source_domain", "title", "url", "published_date", "snippet", "first_seen"]
EXPECTED_KEY_PREFIX = ""  # sha256[:8] of the builder's own key; set to "" to skip the check


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_key(path, expected):
    key = open(os.path.expanduser(path)).read().strip()
    fp = hashlib.sha256(key.encode()).hexdigest()[:8]
    if expected and fp != expected:
        raise SystemExit(f"key fingerprint {fp} does not match expected {expected}; refusing to call the API")
    print(f"key fingerprint sha256[:8]={fp}")
    return key


def call(s, path, params, label, topic):
    at, t0 = now(), time.time()
    try:
        r = s.get(f"{BASE}{path}", params=params, timeout=120)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: data = r.json()
        except ValueError: data = {"_text": r.text[:3000]}
    except Exception as e:
        status, hdr, data = None, {}, {"_error": repr(e)}
    rec = {"label": label, "topic": topic, "path": path, "params": params, "at": at,
           "seconds": round(time.time() - t0, 2), "status": status,
           "cost_usd": hdr.get("x-desearch-cost-usd"), "usage_count": hdr.get("x-desearch-usage-count"), "body": data}
    print(f"{at} {label:24s} {path:9s} {status} {rec['seconds']:6.2f}s n={len(items(rec))} cost={rec['cost_usd']}", flush=True)
    return rec


def items(rec):
    b = rec.get("body")
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("data", "results", "organic_results", "tweets"):
            if isinstance(b.get(k), list): return b[k]
    return []


def norm_url(u):
    p = urlparse((u or "").strip())
    host = p.netloc.lower().removeprefix("www.").replace("twitter.com", "x.com")
    q = "&".join(x for x in p.query.split("&") if x and not x.lower().startswith(("utm_", "ref=", "s=", "t=")))
    return urlunparse(("https", host, p.path.rstrip("/"), "", q, ""))


def domain(u):
    return urlparse(u or "").netloc.lower().removeprefix("www.")


def clean(t, n=300):
    return " ".join(str(t or "").split())[:n]


def iso(d):
    """X created_at comes as 'Fri Oct 16 11:05:51 +0000 2026'; store it as ISO UTC."""
    try: return dt.datetime.strptime(d, "%a %b %d %H:%M:%S %z %Y").isoformat()
    except (TypeError, ValueError): return d or ""


def to_row(rec, it, seen_at):
    if rec["path"] == "/twitter":
        url = it.get("url") or ""
        return {"topic": rec["topic"], "kind": "post", "source_domain": domain(url) or "x.com", "title": clean(it.get("text"), 140),
                "url": url, "published_date": iso(it.get("created_at")), "snippet": clean(it.get("text")), "first_seen": seen_at}
    url = it.get("link") or it.get("url") or ""
    return {"topic": rec["topic"], "kind": "web", "source_domain": domain(url), "title": clean(it.get("title"), 200), "url": url,
            "published_date": it.get("date") or it.get("published_date") or "", "snippet": clean(it.get("snippet") or it.get("description")),
            "first_seen": seen_at}


def build(raw, out_csv, seen_file):
    seen = set(json.load(open(seen_file))) if seen_file and os.path.exists(seen_file) else set()
    before, rows, total, dup_in_run, dup_seen = len(seen), [], 0, 0, 0
    run_keys = set()
    for rec in raw["calls"]:
        if rec.get("empty_check"): continue
        for it in items(rec):
            total += 1
            row = to_row(rec, it, rec["at"])
            k = norm_url(row["url"])
            if not row["url"]: continue
            if k in run_keys: dup_in_run += 1; continue
            run_keys.add(k)
            if k in seen: dup_seen += 1; continue
            rows.append(row)
    new_file = not os.path.exists(out_csv)
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file: w.writeheader()
        w.writerows(rows)
    if seen_file:
        json.dump(sorted(seen | run_keys), open(seen_file, "w"), indent=0)
    print(f"items returned={total} duplicates within run={dup_in_run} already seen={dup_seen} new appended={len(rows)} "
          f"(seen before={before}) with date={sum(bool(r['published_date']) for r in rows)}")
    print(f"wrote {out_csv}")
    return rows


def run_live(a):
    import requests
    s = requests.Session(); s.headers["Authorization"] = load_key(a.key_file, EXPECTED_KEY_PREFIX)
    raw = {"started": now(), "calls": []}
    since = a.since or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    for t in a.topics:
        if not t.strip(): continue  # a blank query is still billed, so skip it before calling
        raw["calls"].append(call(s, "/web", {"query": t, "start": 0}, "web", t))
        raw["calls"].append(call(s, "/twitter", {"query": t, "sort": "Latest", "start_date": since, "count": a.count}, "x latest", t))
    if a.empty_check:
        rec = call(s, "/web", {"query": a.empty_check, "start": 0}, "empty-result check", a.empty_check)
        rec["empty_check"] = True; raw["calls"].append(rec)
    os.makedirs("output", exist_ok=True)
    json.dump(raw, open(f"output/raw-{a.label}.json", "w"), indent=1, default=str)
    return raw


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Monitor news topics with the Desearch API and append new items to a CSV.")
    ap.add_argument("--topics", nargs="+", help="topics to monitor")
    ap.add_argument("--since", help="start_date for X posts (YYYY-MM-DD), default yesterday")
    ap.add_argument("--count", type=int, default=30, help="X posts per topic")
    ap.add_argument("--empty-check", help="optional made-up topic to see what an empty result returns and costs")
    ap.add_argument("--key-file", default="~/.saba/desearch_api_key")
    ap.add_argument("--csv", default="output/news.csv"); ap.add_argument("--seen", default="output/seen.json")
    ap.add_argument("--label", default="run-1"); ap.add_argument("--from-raw", help="rebuild from a saved raw JSON, no API calls")
    a = ap.parse_args()
    if not a.from_raw and not a.topics: ap.error("--topics or --from-raw is required")
    raw = json.load(open(a.from_raw)) if a.from_raw else run_live(a)
    build(raw, a.csv, a.seen)
