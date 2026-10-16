"""Directory Finder: directories Desearch found for a category search, with each submit page read once.

Made by Desearch (https://desearch.ai).

Live:     python directory_finder.py config.json --key-file ~/.desearch_api_key
Offline:  python directory_finder.py --from-raw samples/raw-sample.json
"""
import argparse, csv, datetime as dt, json, os, re, sys, time
from urllib.parse import urlparse

BASE = "https://api.desearch.ai"
DEFAULT_KEY_FILE = "/home/box/.saba/desearch_api_key"
SUBMIT_RE = re.compile(r"submit|add[-_ ]?(your|a|tool|startup|listing|product)|list[-_ ]?your|get[-_ ]?listed|suggest", re.I)


def now_local():
    return dt.datetime.now().astimezone()


def domain(url):
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def call(s, path, params, label):
    at = now_local().isoformat(timespec="seconds"); t0 = time.time()
    try:
        r = s.get(BASE + path, params=params, timeout=90)
        status, headers = r.status_code, dict(r.headers)
        try:
            body = r.json()
        except ValueError:
            body = {"_text": r.text}
    except Exception as e:  # timeout or network error
        status, headers, body = None, {}, {"_error": repr(e)}
    hdr = {k.lower(): v for k, v in headers.items()}
    rec = {"label": label, "path": path, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "headers": hdr, "cost_usd": hdr.get("x-desearch-cost-usd"),
           "usage_count": hdr.get("x-desearch-usage-count"), "body": body}
    print(f"{at} {label:28s} {status} {rec['seconds']:6.2f}s cost={rec['cost_usd']}", flush=True)
    return rec


def results(rec):
    b = rec["body"]
    return (b.get("data") if isinstance(b, dict) else b) or []


def extract_text(rec):
    b = rec["body"]
    if isinstance(b, dict):
        for k in ("_text", "content", "text", "markdown", "data"):
            v = b.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                for k2 in ("content", "text", "markdown"):
                    if isinstance(v.get(k2), str):
                        return v[k2]
    return b if isinstance(b, str) else ""


def shortlist_candidates(searches, limit):
    seen, cands = {}, []
    for rec in searches:
        for i, r in enumerate(results(rec)):
            link = r.get("link") or ""
            d = domain(link)
            if not d or d in seen:
                continue
            seen[d] = 1
            looks_submit = bool(SUBMIT_RE.search(link) or SUBMIT_RE.search(r.get("title") or ""))
            cands.append({"domain": d, "title": r.get("title") or "", "url": link, "looks_like_submit_page": looks_submit,
                          "first_query": rec["params"]["query"], "first_start": rec["params"]["start"], "rank": i + 1})
    pick = [c for c in cands if c["looks_like_submit_page"]][:limit]
    return cands, pick


def quote(text, pat):
    m = re.search(rf"[^.\n]{{0,80}}\b({pat})\b[^.\n]{{0,80}}", text, re.I)
    return re.sub(r"\s+", " ", m.group(0)).strip().replace("\u2014", ", ") if m else ""


def load_key(path):
    """Read the API key from a file only (never from env). The key is never printed."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        sys.exit(f"API key file not found: {path} (pass --key-file PATH)")
    key = open(path).read().strip()
    if not key:
        sys.exit(f"API key file is empty: {path}")
    return key


def session(key):
    import requests
    s = requests.Session(); s.headers["Authorization"] = key
    return s


def run_extracts(s, cfg, searches, max_extracts):
    _, pick = shortlist_candidates(searches, max_extracts)
    extracts = [call(s, "/web/extract", {"url": c["url"], "format": "text", "js": "false"}, f"extract {c['domain'][:20]}") for c in pick]
    bad = call(s, "/web/extract", {"url": cfg["bad_url"], "format": "text", "js": "false"}, "probe extract bad-url")
    return extracts, bad


def fetch(cfg, key, max_extracts):
    s = session(key)
    searches = []
    for q in cfg["queries"]:
        for st in cfg.get("starts", [0, 10, 20]):
            searches.append(call(s, "/web", {"query": q, "start": st}, f"web start={st}"))
    probes = [call(s, "/web", {"query": cfg["queries"][0], "start": 100}, "probe web start=100"),
              call(s, "/web", {"query": cfg["empty_query"], "start": 0}, "probe web empty-result")]
    extracts, bad = run_extracts(s, cfg, searches, max_extracts)
    probes.append(bad)
    return searches, probes, extracts


BLOCK_RE = re.compile(r"\bDR\b|domain (rating|authority)|authority|backlink|dofollow|seo|traffic|#\d|\d{2,},\d{3}", re.I)


def clean_quote(q):
    return "" if BLOCK_RE.search(q) else q


def build(raw, outdir, kinds=None, evid="evidence"):
    date = raw["run_date"]; kinds = kinds or raw.get("kinds", {})
    cands, pick = shortlist_candidates(raw["searches"], raw["max_extracts"])
    ex = {e["params"]["url"]: e for e in raw["extracts"]}
    rows = []
    for c in cands:
        e = ex.get(c["url"]); text = extract_text(e) if e else ""
        rows.append({**c, "kind": kinds.get(c["domain"], "not classified"), "extract_status": e["status"] if e else "", "page_loaded": (bool(e and e["status"] == 200 and len(text.strip()) > 200)) if e else "",
                     "text_chars": len(text) if e else "",
                     "mentions_free": quote(text, "free|no cost") if e else "",
                     "mentions_paid": quote(text, r"paid|\$\d+|pricing|featured listing") if e else "",
                     "mentions_review": quote(text, "review|approv|moderat|queue") if e else "",
                     "extract_cost_usd": e["cost_usd"] if e else ""})
    os.makedirs(outdir, exist_ok=True); os.makedirs(evid, exist_ok=True)
    with open(os.path.join(evid, "all-domains.csv"), "w", newline="") as f:  # internal: every domain, raw quotes
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    pub = []
    for r in rows:
        if r["kind"] != "directory":
            continue
        r = dict(r)
        for k in ("mentions_free", "mentions_paid", "mentions_review"):
            r[k] = clean_quote(r[k])
        r["title"] = re.sub(r"\s*\(\w+ Sheets\)", "", clean_quote(r["title"])).replace("\u2014", ",")
        pub.append({k: r[k] for k in ("domain", "title", "url", "first_query", "first_start", "extract_status", "page_loaded",
                                      "text_chars", "mentions_free", "mentions_paid", "mentions_review")})
    with open(os.path.join(outdir, "directories.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pub[0])); w.writeheader(); w.writerows(pub)
    live = [r for r in pub if r["page_loaded"] is True]
    L = [f"# Directory Finder: {raw['category']}, {date}", "", "Made by [Desearch](https://desearch.ai).", "",
         f"Directories Desearch found for this search on {date}. Queries: " + "; ".join(f"`{q}`" for q in raw["queries"]) + ".",
         f"Each submit page below was read once on {date} and loaded with text. The yes/no columns only say whether the word appears on the page, not a judgment of the site. Check each page yourself before you submit.", "",
         "Only pages that are a directory's own submit page are listed. Lists of directories and multi-directory submission services were left out.", "",
         "| # | Directory | Submit page | Page mentions free | Page mentions paid | Page mentions review |", "|---|---|---|---|---|---|"]
    def cell(s):
        return (s[:90] + "...") if len(s) > 90 else s
    for i, r in enumerate(live[:20], 1):
        yn = lambda v: "yes" if v else "no"
        L.append(f"| {i} | {r['domain']} | {r['url']} | {yn(r['mentions_free'])} | {yn(r['mentions_paid'])} | {yn(r['mentions_review'])} |")
    notloaded = [r for r in pub if r["page_loaded"] is not True]
    L += ["", f"Unique domains in the search results: {len(rows)}. Pages read: {len(pick)}. Directory submit pages: {len(pub)}, of which {len(live)} loaded with text.",
          f"Directory submit pages that did not load with text this time (open them in a browser): {', '.join(r['domain'] for r in notloaded) or 'none'}.",
          "Quotes from each page are in directories.csv."]
    open(os.path.join(outdir, "shortlist.md"), "w").write("\n".join(L) + "\n")
    allc = [x for r in raw.get("earlier_extract_runs", []) for x in r["extracts"] + r["probes"]] + raw["searches"] + raw["probes"] + raw["extracts"]
    print(f"domains {len(rows)}, extracted {len(pick)}, live {len(live)}, calls {len(allc)}, header cost ${sum(float(c['cost_usd'] or 0) for c in allc):.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", default="config.json")
    ap.add_argument("--from-raw"); ap.add_argument("--reextract"); ap.add_argument("--max-extracts", type=int, default=25); ap.add_argument("--out", default="output")
    ap.add_argument("--key-file", default=DEFAULT_KEY_FILE, help="file holding your Desearch API key")
    a = ap.parse_args()
    if a.reextract:
        # re-read submit pages for saved searches (no new web calls)
        key = load_key(a.key_file)
        raw = json.load(open(a.reextract)); cfg = json.load(open(a.config))
        raw.setdefault("earlier_extract_runs", []).append({"extracts": raw["extracts"], "probes": [p for p in raw["probes"] if p["path"] == "/web/extract"]})
        raw["extracts"], bad = run_extracts(session(key), cfg, raw["searches"], raw["max_extracts"])
        raw["probes"] = [p for p in raw["probes"] if p["path"] != "/web/extract"] + [bad]
        raw["extract_rerun_at"] = now_local().isoformat(timespec="seconds")
        json.dump(raw, open(a.reextract, "w"), indent=1)
    elif a.from_raw:
        raw = json.load(open(a.from_raw))
        if os.path.exists(a.config):
            raw["kinds"] = json.load(open(a.config)).get("kinds", {})
    else:
        key = load_key(a.key_file)
        cfg = json.load(open(a.config)); started = now_local()
        searches, probes, extracts = fetch(cfg, key, a.max_extracts)
        raw = {"run_date": started.date().isoformat(), "run_started": started.isoformat(timespec="seconds"),
               "category": cfg["category"], "kinds": cfg.get("kinds", {}), "queries": cfg["queries"], "max_extracts": a.max_extracts,
               "searches": searches, "probes": probes, "extracts": extracts}
        os.makedirs("evidence", exist_ok=True)
        json.dump(raw, open(os.path.join("evidence", f"raw-{raw['run_date']}.json"), "w"), indent=1)
    build(raw, a.out)


if __name__ == "__main__":
    main()
