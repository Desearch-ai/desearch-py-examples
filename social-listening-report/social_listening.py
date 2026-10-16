"""Social Listening Report: public posts and web pages Desearch returned for one brand.

Made by Desearch (https://desearch.ai).

Live:     python social_listening.py config.json
Offline:  python social_listening.py --from-raw evidence/raw-YYYY-MM-DD.json
"""
import argparse, collections, csv, datetime as dt, io, json, os, re, sys, time
from urllib.parse import urlparse

BASE = "https://api.desearch.ai"


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def api_key():
    """DESEARCH_API_KEY, else the file named by DESEARCH_API_KEY_FILE. Never printed or saved."""
    key = os.environ.get("DESEARCH_API_KEY", "").strip()
    path = os.environ.get("DESEARCH_API_KEY_FILE")
    if not key and path:
        with open(os.path.expanduser(path)) as f:
            key = f.read().strip()
    if not key:
        sys.exit("Set DESEARCH_API_KEY (or DESEARCH_API_KEY_FILE) to your key from console.desearch.ai")
    return key


def redact(text, key):
    if key and key in text:
        return text.replace(key, "<redacted>")
    return text


def write_text(path, text, key):
    with open(path, "w") as f:
        f.write(redact(text, key))


def save_raw(raw, key):
    os.makedirs("evidence", exist_ok=True)
    p = f"evidence/raw-{raw['run_at'][:10]}.json"
    write_text(p, json.dumps(raw, indent=1), key)
    print("raw ->", p)


def call(s, path, params, label):
    at, t0 = now(), time.time()
    try:
        r = s.get(BASE + path, params=params, timeout=90)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: body = r.json()
        except ValueError: body = {"_text": r.text[:2000]}
    except Exception as e:
        status, hdr, body = None, {}, {"_error": repr(e)}
    rec = {"label": label, "path": path, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"), "usage_count": hdr.get("x-desearch-usage-count"),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k in ("content-type", "date")}, "body": body}
    print(f"{at} {label:28s} {status} {rec['seconds']:6.2f}s n={len(items(rec))} cost={rec['cost_usd']}", flush=True)
    return rec


def items(rec):
    b = rec["body"]
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("data", "results", "organic_results"):
            if isinstance(b.get(k), list): return b[k]
    return []


def run_live(cfg):
    import requests
    key = api_key()
    s = requests.Session(); s.headers["Authorization"] = key
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    raw = {"run_at": now(), "cfg": cfg, "since": since, "x": [], "web": [], "probes": []}
    raw["x"].append(call(s, "/twitter", {"query": cfg["x_query"], "sort": "Latest", "count": cfg["x_count"], "start_date": since}, "x latest"))
    raw["x"].append(call(s, "/twitter", {"query": cfg["x_query"], "sort": "Top", "count": 20, "start_date": since}, "x top"))
    for st in cfg["web_starts"]:
        raw["web"].append(call(s, "/web", {"query": cfg["web_query"], "start": st}, f"web start={st}"))
    raw["probes"].append(call(s, "/twitter", {"query": cfg["empty_query"], "sort": "Latest", "count": 20}, "probe x nonsense"))
    raw["probes"].append(call(s, "/web", {"query": cfg["empty_query"], "start": 0}, "probe web nonsense"))
    raw["probes"].append(call(s, "/twitter", {"query": "", "count": 20}, "probe x blank query"))
    raw["probes"].append(call(s, "/web", {"query": "", "start": 0}, "probe web blank query"))
    save_raw(raw, key)
    return raw, key


def num(v):
    try: return int(v or 0)
    except (TypeError, ValueError): return 0


def build(raw, outdir, key=""):
    os.makedirs(outdir, exist_ok=True)
    cfg = raw["cfg"]; on = re.compile("|".join(re.escape(w) for w in cfg["on_topic_words"]), re.I)
    rows, seen = [], set()
    for rec in raw["x"]:
        for p in items(rec):
            if p.get("id") in seen: continue
            seen.add(p.get("id")); u = p.get("user") or {}
            rows.append({"source": "x", "id": p.get("id"), "date": (p.get("created_at") or "")[:10] or "", "created_at": p.get("created_at"),
                         "author": u.get("username"), "likes": num(p.get("like_count")), "reposts": num(p.get("retweet_count")),
                         "replies": num(p.get("reply_count")), "views": num(p.get("view_count")),
                         "on_topic": bool(on.search(p.get("text") or "")), "domain": "x.com", "title": "",
                         "url": p.get("url") or f"https://x.com/i/status/{p.get('id')}", "text": re.sub(r"\s+", " ", p.get("text") or "")})
    web_stats, wseen = [], {}
    for rec in raw["web"]:
        res = items(rec); new = 0
        for i, r in enumerate(res):
            link = r.get("link") or r.get("url") or ""
            if link in wseen: continue
            wseen[link] = 1; new += 1
            blob = f"{r.get('title') or ''} {r.get('snippet') or r.get('description') or ''} {link}"
            rows.append({"source": "web", "id": "", "date": "", "created_at": "", "author": "", "likes": 0, "reposts": 0, "replies": 0, "views": 0,
                         "on_topic": bool(on.search(blob)), "domain": urlparse(link).netloc.removeprefix("www."), "title": r.get("title") or "",
                         "url": link, "text": re.sub(r"\s+", " ", r.get("snippet") or r.get("description") or "")})
        web_stats.append({"start": rec["params"]["start"], "status": rec["status"], "returned": len(res), "new_urls": new,
                          "seconds": rec["seconds"], "cost_usd": rec["cost_usd"]})
    pub_alias = {}
    pub = [dict(r, author=(pub_alias.setdefault(r["author"], f"Account {len(pub_alias) + 1}") if r["author"] else ""),
                text=re.sub(r"@\w+", "@account", r["text"]).replace("\u2014", ", ")) for r in rows]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(pub)
    write_text(os.path.join(outdir, "mentions.csv"), buf.getvalue(), key)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(web_stats[0].keys())); w.writeheader(); w.writerows(web_stats)
    write_text(os.path.join(outdir, "web-pages.csv"), buf.getvalue(), key)
    x = [r for r in rows if r["source"] == "x"]; web = [r for r in rows if r["source"] == "web"]
    byday = collections.Counter(r["created_at"] and dt.datetime.strptime(r["created_at"], "%a %b %d %H:%M:%S %z %Y").date().isoformat()
                                if r["created_at"] and not r["created_at"][:4].isdigit() else (r["created_at"] or "")[:10] for r in x)
    alias = {}
    def A(h): return alias.setdefault(h, f"Account {chr(65 + len(alias))}" if len(alias) < 26 else f"Account {len(alias)}")
    def clean(t): return re.sub(r"@\w+", "@account", t).replace("\u2014", ", ").replace("|", "/")[:140]
    md = [f"# Social Listening Report: {cfg['brand']} ({raw['run_at'][:10]})", "",
          f"Public posts Desearch returned for `{cfg['x_query']}` since {raw['since']}, plus web pages for `{cfg['web_query']}` (3 pages).", "",
          f"- X posts: {len(x)} unique ({sum(r['on_topic'] for r in x)} name the brand in the text)",
          f"- Web pages: {len(web)} unique URLs ({sum(r['on_topic'] for r in web)} on topic)", "",
          "## X posts by day", "", "| Day | Posts |", "|---|---|"] + [f"| {d} | {n} |" for d, n in sorted(byday.items())]
    md += ["", "## Top X posts by engagement (likes + reposts + replies)", "", "| Account | Likes | Reposts | Views | Post |", "|---|---|---|---|---|"]
    for r in sorted(x, key=lambda r: -(r["likes"] + r["reposts"] + r["replies"]))[:10]:
        md.append(f"| {A(r['author'])} | {r['likes']} | {r['reposts']} | {r['views']} | {clean(r['text'])} |")
    md += ["", "## Top web domains", "", "| Domain | Pages | On topic |", "|---|---|---|"]
    dc = collections.Counter(r["domain"] for r in web)
    for d, n in dc.most_common(15):
        md.append(f"| {d} | {n} | {sum(1 for r in web if r['domain'] == d and r['on_topic'])} |")
    write_text(os.path.join(outdir, "report.md"), "\n".join(md) + "\n", key)
    return rows, web_stats, byday


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("config", nargs="?"); ap.add_argument("--from-raw"); ap.add_argument("--out", default="output")
    a = ap.parse_args()
    if a.from_raw:
        raw = json.load(open(a.from_raw))
        key = os.environ.get("DESEARCH_API_KEY", "").strip()
    else:
        raw, key = run_live(json.load(open(a.config or "config.json")))
    rows, ws, byday = build(raw, a.out, key)
    for w in ws: print(w)
    print("by day:", dict(byday)); print("rows:", len(rows))
