"""Launch Quote Ledger: who quoted a product launch post on X, and what they said.

Made by Desearch (https://desearch.ai).

Live:     python launch_quote_ledger.py config.json
Offline:  python launch_quote_ledger.py --from-raw evidence/raw-YYYY-MM-DD.json
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, time

BASE = "https://api.desearch.ai"
NEGATED = re.compile(r"\b(not|no|non)[- ]sponsored\b", re.I)
DISCLOSURE = re.compile(r"(#ad\b|#sponsored\b|\bsponsored\b|\bpaid partnership\b|#partner\b|\bpartner(ed|ship)?\b|\bin collaboration with\b|#collab\b|\baffiliate\b|\bgifted\b)", re.I)


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
    n = len(body) if isinstance(body, list) else "-"
    print(f"{at} {label:34s} {status} {rec['seconds']:6.2f}s n={n} cost={rec['cost_usd']}", flush=True)
    return rec


def posts(rec):
    b = rec["body"]
    return b if isinstance(b, list) else (b.get("data") or [] if isinstance(b, dict) and isinstance(b.get("data"), list) else [])


def run_live(cfg):
    import requests
    key = api_key()
    s = requests.Session(); s.headers["Authorization"] = key
    raw = {"run_at": now(), "count": cfg["count"], "launches": [], "probes": []}
    for L in cfg["launches"]:
        url = f"https://x.com/{L['user']}/status/{L['id']}"
        e = {"label": L["label"], "id": L["id"], "user": L["user"], "calls": {}}
        e["calls"]["post"] = call(s, "/twitter/post", {"id": L["id"]}, f"{L['label']} post")
        variants = {
            "url_quote": {"query": f"url:{url}", "is_quote": "true"},
            "handle_quote": {"query": f"@{L['user']}", "is_quote": "true"},
            "handle_quote_blue": {"query": f"@{L['user']}", "is_quote": "true", "blue_verified": "true"},
            "quoted_id_quote": {"query": f"quoted_tweet_id:{L['id']}", "is_quote": "true"},
        }
        for k, p in variants.items():
            p = dict(p, count=cfg["count"], sort="Latest")
            e["calls"][k] = call(s, "/twitter", p, f"{L['label']} {k}")
        raw["launches"].append(e)
    raw["probes"].append(call(s, "/twitter/post", {"id": cfg["bad_id"]}, "probe bad post id"))
    raw["probes"].append(call(s, "/twitter/post", {"id": "not-a-number"}, "probe malformed post id"))
    raw["probes"].append(call(s, "/twitter", {"query": cfg["empty_query"], "is_quote": "true", "count": 20}, "probe empty quote search"))
    save_raw(raw, key)
    return raw, key


def build(raw, outdir, key=""):
    os.makedirs(outdir, exist_ok=True)
    rows, stats = [], []
    for e in raw["launches"]:
        for k, rec in e["calls"].items():
            if k == "post": continue
            ps = posts(rec)
            true_q = [p for p in ps if str(p.get("quoted_status_id") or (p.get("quote") or {}).get("id")) == e["id"]]
            stats.append({"launch": e["label"], "variant": k, "status": rec["status"], "requested": raw["count"],
                          "returned": len(ps), "is_quote_flag": sum(1 for p in ps if p.get("is_quote_tweet")),
                          "quote_this_launch": len(true_q), "blue": sum(1 for p in ps if (p.get("user") or {}).get("is_blue_verified")),
                          "seconds": rec["seconds"], "cost_usd": rec["cost_usd"]})
            for p in true_q:
                m = DISCLOSURE.findall(p.get("text", ""))
                rows.append({"launch": e["label"], "variant": k, "quote_id": p["id"], "quoter": (p.get("user") or {}).get("username"),
                             "quoter_blue": (p.get("user") or {}).get("is_blue_verified"), "created_at": p.get("created_at"),
                             "likes": p.get("like_count"), "views": p.get("view_count"),
                             "disclosure_wording": "|".join(sorted({x[0].lower() for x in m})),
                             "negated": bool(NEGATED.search(p.get("text", ""))), "text": re.sub(r"\s+", " ", p.get("text", ""))})
    seen, ledger = set(), []
    for r in rows:
        if r["quote_id"] in seen: continue
        seen.add(r["quote_id"]); ledger.append(r)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(ledger[0].keys()) if ledger else ["launch"]); w.writeheader(); w.writerows(ledger)
    write_text(os.path.join(outdir, "quotes.csv"), buf.getvalue(), key)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(stats[0].keys())); w.writeheader(); w.writerows(stats)
    write_text(os.path.join(outdir, "variant-stats.csv"), buf.getvalue(), key)
    md = [f"# Launch Quote Ledger ({raw['run_at'][:10]})", "", "Quote posts Desearch found for each launch post. Disclosure column = wording found in public text.", ""]
    for e in raw["launches"]:
        lr = [r for r in ledger if r["launch"] == e["label"]]
        md += [f"## {e['label']}: {len(lr)} quotes", "", "| Quoter | Likes | Wording found in public text | Quote |", "|---|---|---|---|"]
        alias = {}
        for r in lr:
            a = alias.setdefault(r["quoter"], f"Account {chr(65 + len(alias)) if len(alias) < 26 else len(alias)}")
            md.append(f"| {a} | {r['likes']} | {r['disclosure_wording'] or '-'} | {re.sub(r'@\w+', '@account', r['text']).replace('\u2014', ', ')[:140].replace('|', '/')} |")
        md.append("")
    write_text(os.path.join(outdir, "quotes.md"), "\n".join(md), key)
    return ledger, stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("config", nargs="?"); ap.add_argument("--from-raw"); ap.add_argument("--out", default="output")
    a = ap.parse_args()
    if a.from_raw:
        raw = json.load(open(a.from_raw))
        key = os.environ.get("DESEARCH_API_KEY", "").strip()
    else:
        raw, key = run_live(json.load(open(a.config or "config.json")))
    ledger, stats = build(raw, a.out, key)
    for s in stats: print(s)
    print(f"ledger rows: {len(ledger)}")
