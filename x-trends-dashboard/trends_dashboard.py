"""X Trends Dashboard: trends Desearch returned for several places, side by side.

Made by Desearch (https://desearch.ai).

Live:     python trends_dashboard.py config.json [--label run-1] [--no-probes] [--no-samples]
Offline:  python trends_dashboard.py --from-raw evidence/raw-run-1.json [--previous evidence/raw-run-0.json]
"""
import argparse, csv, datetime as dt, html, io, json, os, re, sys, time

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
    p = f"evidence/raw-{raw.get('label', 'run')}.json"
    write_text(p, json.dumps(raw, indent=1, ensure_ascii=False), key)
    print("raw ->", p)


def call(s, path, params, label):
    at, t0 = now(), time.time()
    try:
        r = s.get(BASE + path, params=params, timeout=90)
        status, hdr = r.status_code, {k.lower(): v for k, v in r.headers.items()}
        try: body = r.json()
        except ValueError: body = {"_text": r.text[:20000]}
    except Exception as e:
        status, hdr, body = None, {}, {"_error": repr(e)}
    rec = {"label": label, "path": path, "params": params, "at": at, "seconds": round(time.time() - t0, 2),
           "status": status, "cost_usd": hdr.get("x-desearch-cost-usd"), "usage_count": hdr.get("x-desearch-usage-count"),
           "headers": {k: v for k, v in hdr.items() if k.startswith("x-desearch") or k in ("content-type", "date")}, "body": body}
    print(f"{at} {label:30s} {status} {rec['seconds']:6.2f}s n={len(items(rec))} cost={rec['cost_usd']}", flush=True)
    return rec


def items(rec):
    b = rec["body"]
    if isinstance(b, list): return b
    if isinstance(b, dict):
        for k in ("trends", "data", "results", "tweets"):
            if isinstance(b.get(k), list): return b[k]
    return []


def returned_woeid(rec):
    w = rec["body"].get("woeid") if isinstance(rec["body"], dict) else None
    if isinstance(w, dict): w = w.get("id")
    return w


def clean(t):
    t = re.sub(r"@\w+", "[account]", t or "")
    t = re.sub(r"https?://\S+", "[link]", t)
    return t.replace("\u2014", ", ").replace("\n", " ").strip()


def trend_name(t):
    return (t.get("name") or t.get("query") or "").strip() if isinstance(t, dict) else str(t)


def run_live(cfg, probes, samples):
    import requests
    key = api_key()
    s = requests.Session(); s.headers["Authorization"] = key
    raw = {"run_at": now(), "cfg": cfg, "trends": [], "x": [], "probes": []}
    for w in cfg["places"]:
        raw["trends"].append(call(s, "/twitter/trends", {"woeid": int(w), "count": cfg["count"]}, f"trends {w}"))
    if samples:
        for name, _ in shared_trends(raw)[: cfg["sample_top_shared"]]:
            raw["x"].append(call(s, "/twitter", {"query": name, "sort": "Latest", "count": cfg["x_count"]}, "x " + name[:24]))
    if probes:
        raw["probes"].append(call(s, "/twitter", {"query": cfg["empty_query"], "sort": "Latest", "count": cfg["x_count"]}, "probe x empty result"))
        raw["probes"].append(call(s, "/twitter/trends", {"woeid": 1, "count": cfg["bad_count"]}, "probe trends count=29"))
        raw["probes"].append(call(s, "/twitter/trends", {"woeid": cfg["fallback_woeid"], "count": cfg["count"]}, "probe trends unknown woeid"))
    return raw, key


def table(raw):
    rows = []
    for rec in raw["trends"]:
        w = str(rec["params"]["woeid"]); got = returned_woeid(rec)
        ok = got is not None and str(got) == w
        for i, t in enumerate(items(rec), 1):
            vol = t.get("tweet_volume") if isinstance(t, dict) else None
            rows.append({"snapshot": raw["run_at"], "woeid": w, "place": raw["cfg"]["places"].get(w, w), "woeid_matches": ok,
                         "rank": i, "trend": clean(trend_name(t)), "tweet_volume": vol if vol is not None else ""})
    return rows


def norm(t):
    return t.lower().lstrip("#").replace(" ", "")


def shared_trends(raw):
    by = {}
    for r in table(raw):
        if r["woeid_matches"]: by.setdefault(norm(r["trend"]), [r["trend"], set()])[1].add(r["place"])
    out = [(v[0], sorted(v[1])) for v in by.values() if len(v[1]) >= 2]
    return sorted(out, key=lambda x: -len(x[1]))


def build(raw, outdir, prev=None, key=""):
    os.makedirs(outdir, exist_ok=True)
    rows = table(raw); tag = raw.get("label", "run")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    write_text(os.path.join(outdir, f"trends-{tag}.csv"), buf.getvalue(), key)
    shared = shared_trends(raw)
    places = list(raw["cfg"]["places"].values())
    uniq = {p: [r["trend"] for r in rows if r["place"] == p and r["woeid_matches"]
                and not any(norm(r["trend"]) == norm(s[0]) for s in shared)] for p in places}
    posts = []
    for rec in raw["x"]:
        for p in items(rec)[:3]:
            posts.append({"trend": rec["params"]["query"], "created_at": p.get("created_at", ""), "author": "Account " + chr(65 + len(posts)),
                          "likes": p.get("like_count", ""), "text": clean(p.get("text", ""))[:220]})
    moved = None
    if prev:
        pt = {(r["place"], r["trend"].lower()): r["rank"] for r in table(prev)}
        moved = []
        for r in rows:
            old = pt.get((r["place"], r["trend"].lower()))
            moved.append({**{k: r[k] for k in ("place", "trend", "rank")}, "previous_rank": old or "new"})
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(moved[0].keys())); w.writeheader(); w.writerows(moved)
        write_text(os.path.join(outdir, f"moves-{tag}.csv"), buf.getvalue(), key)
    summary = {"snapshot": raw["run_at"], "places": {p: sum(1 for r in rows if r["place"] == p) for p in places},
               "woeid_mismatch": sorted({r["place"] for r in rows if not r["woeid_matches"]}),
               "tweet_volume_filled": sum(1 for r in rows if r["tweet_volume"] != ""), "trend_rows": len(rows),
               "shared": [{"trend": t, "places": p} for t, p in shared], "unique_counts": {p: len(v) for p, v in uniq.items()},
               "sample_posts": posts}
    write_text(os.path.join(outdir, f"dashboard-{tag}.json"), json.dumps(summary, indent=2, ensure_ascii=False), key)
    e = html.escape
    h = [f"<!doctype html><meta charset='utf-8'><title>X Trends Dashboard</title><style>body{{font-family:sans-serif;max-width:1100px;margin:auto}}"
         "table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #ccc;padding:3px 6px}.s{background:#e8f4ff}</style>",
         f"<h1>X Trends Dashboard</h1><p>Trends Desearch returned at {e(raw['run_at'])} for {len(places)} places. Made by <a href='https://desearch.ai'>Desearch</a>.</p>"]
    if summary["woeid_mismatch"]:
        h.append(f"<p><b>Location not matched, left out of the comparison:</b> {e(', '.join(summary['woeid_mismatch']))}</p>")
    h.append("<h2>Side by side (shared trends highlighted)</h2><table><tr><th>#</th>" + "".join(f"<th>{e(p)}</th>" for p in places) + "</tr>")
    sh = {norm(s[0]) for s in shared}
    grid = {p: [r["trend"] for r in rows if r["place"] == p] for p in places}
    for i in range(max(len(v) for v in grid.values())):
        h.append(f"<tr><td>{i+1}</td>" + "".join(
            (f"<td class='s'>{e(grid[p][i])}</td>" if norm(grid[p][i]) in sh else f"<td>{e(grid[p][i])}</td>") if i < len(grid[p]) else "<td></td>"
            for p in places) + "</tr>")
    h.append("</table><h2>Trends in 2 or more places</h2><ul>" + "".join(f"<li>{e(t)}: {e(', '.join(p))}</li>" for t, p in shared) + "</ul>")
    if posts:
        h.append("<h2>Sample latest posts for top shared trends</h2><ul>" + "".join(
            f"<li><b>{e(p['trend'])}</b> ({e(p['author'])}, {e(str(p['created_at']))}): {e(p['text'])}</li>" for p in posts) + "</ul>")
    if moved:
        new = [m for m in moved if m["previous_rank"] == "new"]
        h.append(f"<h2>Change since previous snapshot</h2><p>{len(new)} of {len(moved)} rows are new.</p><ul>" +
                 "".join(f"<li>{e(m['place'])}: {e(m['trend'])} (rank {m['rank']})</li>" for m in new[:40]) + "</ul>")
    write_text(os.path.join(outdir, f"dashboard-{tag}.html"), "\n".join(h), key)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", default="config.json")
    ap.add_argument("--from-raw"); ap.add_argument("--previous"); ap.add_argument("--label", default=None)
    ap.add_argument("--out", default="output"); ap.add_argument("--no-probes", action="store_true"); ap.add_argument("--no-samples", action="store_true")
    a = ap.parse_args()
    prev = json.load(open(a.previous)) if a.previous else None
    if a.from_raw:
        raw = json.load(open(a.from_raw))
        raw["label"] = a.label or raw.get("label") or "run"
        key = os.environ.get("DESEARCH_API_KEY", "").strip()
    else:
        raw, key = run_live(json.load(open(a.config)), not a.no_probes, not a.no_samples)
        raw["label"] = a.label or "run-1"
        save_raw(raw, key)
    s = build(raw, a.out, prev, key)
    print(json.dumps({k: v for k, v in s.items() if k not in ("sample_posts", "shared")}, indent=1), "\nshared:", len(s["shared"]))
