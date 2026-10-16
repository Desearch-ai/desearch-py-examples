"""SERP API Rank Checker: search results Desearch returned for your keywords, and where your domain sits.

usage: python rank_check.py --keywords keywords.txt --domain example.com [--pages 2] [--step 20] [--out runs] [--diff old/summary.json]
Key: DESEARCH_API_KEY, or a file path in DESEARCH_API_KEY_FILE.
"""
import argparse, re, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import core

BASE = "https://api.desearch.ai"
UA = "serp-api-rank-checker/0.1 (+made-by-desearch)"


def api_key():
    k = os.environ.get("DESEARCH_API_KEY")
    if not k and os.environ.get("DESEARCH_API_KEY_FILE"):
        k = pathlib.Path(os.environ["DESEARCH_API_KEY_FILE"]).read_text().strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY or DESEARCH_API_KEY_FILE")
    return k


class Client:
    """Plain HTTP. Logs each call to calls.jsonl and saves each response to raw/ with the key redacted."""

    def __init__(self, key, out):
        self.key, self.out, self.n, self.total = key, pathlib.Path(out), 0, 0.0
        (self.out / "raw").mkdir(parents=True, exist_ok=True)

    def _save(self, path, obj):
        s = json.dumps(obj, indent=1, ensure_ascii=False)
        if self.key in s:
            raise RuntimeError("refusing to write a file that contains the API key")
        path.write_text(s)

    def get(self, path, params, tag):
        self.n += 1
        url = BASE + path + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": self.key, "User-Agent": UA})
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        t0 = time.perf_counter()
        try:
            r = urllib.request.urlopen(req, timeout=120)
            st, hd, raw = r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            st, hd, raw = e.code, dict(e.headers), e.read().decode()
        lat = round(time.perf_counter() - t0, 2)
        try:
            body = json.loads(raw)
        except ValueError:
            body = raw[:2000]
        bill = {k: v for k, v in hd.items() if k.lower().startswith("x-desearch")}
        cost = next((float(v) for k, v in bill.items() if k.lower() == "x-desearch-cost-usd"), 0.0)
        self.total += cost
        rec = {"n": self.n, "tag": tag, "time": ts, "request": {"method": "GET", "url": url,
               "headers": {"Authorization": "<redacted>", "User-Agent": UA}}, "status": st,
               "latency_s": lat, "billing_headers": bill, "items": len(core.items_of(body))}
        self._save(self.out / "raw" / f"{self.n:03d}-{tag}.json", {**rec, "body": body})
        with open(self.out / "calls.jsonl", "a") as f:
            line = json.dumps(rec)
            if self.key in line:
                raise RuntimeError("refusing to log the API key")
            f.write(line + "\n")
        print(f"[{ts}] {st} {tag} {lat}s items={rec['items']} cost={cost}", file=sys.stderr)
        return st, body


def check_keyword(c, kw, domain, pages, step=20):
    got = []
    for p in range(pages):
        start = p * step
        st, body = c.get("/web", {"query": kw, "start": start}, f"{re.sub(r'[^a-z0-9]+', '-', kw.lower()).strip('-')[:30] or 'blank'}-s{start}")
        got.append((start, core.items_of(body) if st < 300 else []))
    rows, stats = core.merge_pages(got)
    return {"keyword": kw, "rows": rows, "page_stats": stats, **core.keyword_summary(kw, domain, rows)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keywords", required=True, help="text file, one keyword per line")
    ap.add_argument("--domain", required=True)
    ap.add_argument("--pages", type=int, default=2, help="pages of 10 per keyword (start 0, 10, ...)")
    ap.add_argument("--step", type=int, default=20, help="start offset between pages (default 20, see README)")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--diff", help="summary.json from an earlier run")
    a = ap.parse_args(argv)
    kws = core.parse_keywords(pathlib.Path(a.keywords).read_text())
    out = pathlib.Path(a.out) / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    c = Client(api_key(), out)
    results = [check_keyword(c, k, a.domain, a.pages, a.step) for k in kws]
    (out / "results.csv").write_text(core.to_csv(results))
    summary = {"domain": a.domain, "pages": a.pages, "step": a.step, "calls": c.n, "header_total_usd": round(c.total, 6),
               "keywords": [{k: r[k] for k in ("keyword", "best_rank", "label", "best_url", "depth", "page_stats")} for r in results]}
    (out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    if a.diff:
        old = {k["keyword"]: k["best_rank"] for k in json.loads(pathlib.Path(a.diff).read_text())["keywords"]}
        summary["diff"] = core.diff_runs(old, {r["keyword"]: r["best_rank"] for r in results})
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    for k in summary["keywords"]:
        print(f"{k['keyword']:<40} {k['label']}")
    for d in summary.get("diff", []):
        print(f"diff {d['keyword']:<35} {d['before']} -> {d['after']} ({d['change']})")
    print(f"{c.n} calls, header total ${c.total:.6f}, output {out}")


if __name__ == "__main__":
    main()
