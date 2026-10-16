"""Market Research Brief: web pages and posts Desearch returned for one market.

Made by Desearch (https://desearch.ai).

Live:     python market_brief.py config.json
Offline:  python market_brief.py --from-raw evidence/raw-YYYY-MM-DD.json
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
        except ValueError: body = {"_text": r.text[:60000]}
    except Exception as e:
        status, hdr, body = None, {}, {"_error": repr(e)}
    rec = {"label": label, "path": path, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"), "usage_count": hdr.get("x-desearch-usage-count"),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k in ("content-type", "date")}, "body": body}
    print(f"{at} {label:34s} {status} {rec['seconds']:6.2f}s n={len(items(rec))} len={len(text_of(rec))} cost={rec['cost_usd']}", flush=True)
    return rec


def items(rec):
    b = rec["body"]
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("data", "results", "organic_results"):
            if isinstance(b.get(k), list): return b[k]
    return []


def text_of(rec):
    b = rec["body"]
    if isinstance(b, str): return b
    if isinstance(b, dict):
        for k in ("_text", "content", "text", "markdown", "data"):
            if isinstance(b.get(k), str): return b[k]
    return ""


def clean(t):
    return re.sub(r"@\w+", "@account", t).replace("\u2014", ", ")


def dom(u):
    return urlparse(u).netloc.lower().removeprefix("www.")


def brand_owned(u, cfg):
    d = dom(u)
    return any(b in d for b in cfg["brand_domains"])


def dedupe(raw):
    seen, rows, stats = {}, [], []
    for rec in raw["web"]:
        res, new = items(rec), 0
        for r in res:
            link = (r.get("link") or r.get("url") or "").split("#")[0].rstrip("/")
            if not link or link in seen: continue
            seen[link] = 1; new += 1
            rows.append({"start": rec["params"]["start"], "domain": dom(link), "title": clean(r.get("title") or ""), "url": link,
                         "snippet": clean(re.sub(r"\s+", " ", r.get("snippet") or r.get("description") or ""))})
        stats.append({"start": rec["params"]["start"], "status": rec["status"], "returned": len(res), "new_urls": new,
                      "seconds": rec["seconds"], "cost_usd": rec["cost_usd"]})
    return rows, stats


def run_live(cfg):
    import requests
    key = api_key()
    s = requests.Session(); s.headers["Authorization"] = key
    raw = {"run_at": now(), "cfg": cfg, "web": [], "extract": [], "x": [], "probes": []}
    for st in cfg["web_starts"]:
        raw["web"].append(call(s, "/web", {"query": cfg["web_query"], "start": st}, f"web start={st}"))
    rows, _ = dedupe(raw)
    targets = [r["url"] for r in rows if not brand_owned(r["url"], cfg)][: cfg["max_extract"]]
    for u in targets:
        raw["extract"].append(call(s, "/web/extract", {"url": u, "format": "text", "js": "false"}, "extract " + dom(u)))
    raw["x"].append(call(s, "/twitter", {"query": cfg["x_query"], "sort": "Latest", "count": cfg["x_count"]}, "x latest"))
    raw["probes"].append(call(s, "/web/extract", {"url": cfg["bad_url"], "format": "text", "js": "false"}, "probe extract bad url"))
    raw["probes"].append(call(s, "/web", {"query": cfg["empty_query"], "start": 0}, "probe web empty query"))
    save_raw(raw, key)
    return raw, key


def build(raw, outdir, key=""):
    cfg = raw["cfg"]; os.makedirs(outdir, exist_ok=True)
    rows, stats = dedupe(raw)
    for r in rows: r["brand_owned"] = brand_owned(r["url"], cfg)
    ex = []
    for rec in raw["extract"]:
        t = text_of(rec)
        ex.append({"url": rec["params"]["url"], "status": rec["status"], "chars": len(t.strip()), "empty": len(t.strip()) < 200,
                   "seconds": rec["seconds"], "cost_usd": rec["cost_usd"], "text": t})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    write_text(os.path.join(outdir, "web-pages.csv"), buf.getvalue(), key)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(stats[0].keys())); w.writeheader(); w.writerows(stats)
    write_text(os.path.join(outdir, "web-paging.csv"), buf.getvalue(), key)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[k for k in ex[0] if k != "text"]); w.writeheader()
    w.writerows([{k: v for k, v in e.items() if k != "text"} for e in ex])
    write_text(os.path.join(outdir, "extracts.csv"), buf.getvalue(), key)
    good = [e for e in ex if not e["empty"]]
    corpus = "\n".join(e["text"] for e in good).lower()
    bc = collections.Counter()
    for b in cfg["brands"]:
        n = sum(1 for e in good if re.search(r"\b" + re.escape(b) + r"\b", e["text"].lower()))
        if n: bc[b] = n
    cc = {c: sum(1 for e in good if c in e["text"].lower()) for c in cfg["complaint_words"]}
    prices = [float(p.replace(",", "")) for p in re.findall(r"\$\s?(\d{2,4}(?:,\d{3})?(?:\.\d\d)?)", corpus)]
    prices = [p for p in prices if 30 <= p <= 5000]
    xs = [p for rec in raw["x"] for p in items(rec)]
    xc = {c: sum(1 for p in xs if c in (p.get("text") or "").lower()) for c in cfg["complaint_words"]}
    def q(v, f):
        v = sorted(v); return v[int(f * (len(v) - 1))] if v else None
    md = [f"# Market Research Brief: {cfg['market']} ({raw['run_at'][:10]})", "",
          f"Based on the web pages and posts Desearch returned for `{cfg['web_query']}` ({len(stats)} result pages) "
          f"and text read from {len(good)} third-party pages. This is a sample, not the whole market.", "",
          "## Sources", "",
          f"- Web results: {sum(s['returned'] for s in stats)} returned, {len(rows)} unique URLs after removing repeats",
          f"- Brand-owned or store pages: {sum(r['brand_owned'] for r in rows)} of {len(rows)}",
          f"- Pages read: {len(ex)} requested, {len(good)} with usable text",
          f"- Recent X posts sampled: {len(xs)}", "",
          "## Brands named most often (pages naming the brand)", "", "| Brand | Pages |", "|---|---|"]
    md += [f"| {b} | {n} |" for b, n in bc.most_common(12)]
    md += ["", "## Recurring buyer concerns (pages / posts mentioning the term)", "", "| Term | Pages | Posts |", "|---|---|---|"]
    md += [f"| {c} | {n} | {xc[c]} |" for c, n in sorted(cc.items(), key=lambda x: -x[1]) if n or xc[c]]
    md += ["", "## Price mentions in page text", ""]
    if prices:
        md += [f"- {len(prices)} dollar amounts between $30 and $5,000; median ${q(prices, .5):,.0f}, "
               f"middle half ${q(prices, .25):,.0f} to ${q(prices, .75):,.0f}"]
    md += ["", "## Pages read", ""] + [f"- {e['url']} ({e['chars']} chars{', empty' if e['empty'] else ''})" for e in ex]
    write_text(os.path.join(outdir, "brief.md"), "\n".join(md).replace("\u2014", ", ") + "\n", key)
    return rows, stats, ex, bc, cc, prices


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("config", nargs="?"); ap.add_argument("--from-raw"); ap.add_argument("--out", default="output")
    a = ap.parse_args()
    if a.from_raw:
        raw = json.load(open(a.from_raw))
        key = os.environ.get("DESEARCH_API_KEY", "").strip()
    else:
        raw, key = run_live(json.load(open(a.config or "config.json")))
    rows, stats, ex, bc, cc, prices = build(raw, a.out, key)
    for s in stats: print(s)
    print("unique", len(rows), "brand_owned", sum(r["brand_owned"] for r in rows), "extract empties", sum(e["empty"] for e in ex), "prices", len(prices))
    for p in raw.get("probes") or []: print("probe", p["label"], p["status"], p["cost_usd"], str(p["body"])[:200])
