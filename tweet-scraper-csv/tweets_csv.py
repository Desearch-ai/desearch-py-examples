"""Tweet Scraper to CSV: public X posts Desearch returned for a query, written to a clean CSV.

python tweets_csv.py "home espresso" "espresso machine" --days 7 --sort Latest --count 50 --lang en
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
import core

BASE = "https://api.desearch.ai"
UA = "tweet-scraper-csv/0.1 (+https://desearch.ai)"


def api_key():
    path = os.environ.get("DESEARCH_API_KEY_FILE")
    key = pathlib.Path(path).expanduser().read_text().strip() if path else os.environ.get("DESEARCH_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set DESEARCH_API_KEY_FILE (a file holding your key from console.desearch.ai) or DESEARCH_API_KEY")
    return key


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
            body = None
        items = len(body) if isinstance(body, list) else None
        bill = {k: v for k, v in hd.items() if k.lower().startswith("x-desearch")}
        cost, src = core.cost_of(bill)
        self.total += cost
        rec = {"n": self.n, "tag": tag, "ts": ts, "url": url, "status": st, "latency_s": lat, "items": items,
               "body_type": type(body).__name__, "billing_headers": bill, "cost_usd": cost, "cost_source": src,
               "response_header_names": sorted(hd)}
        self._save(self.out / "raw" / f"{self.n:03d}-{tag}.json",
                   {**rec, "request_headers": {"Authorization": "<redacted>", "User-Agent": UA},
                    "response": body if body is not None else raw})
        with open(self.out / "calls.jsonl", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{ts}] {st} {lat}s {tag} items={items} cost={cost} ({src})", file=sys.stderr)
        return st, body


def search(c, query, tag="search", **params):
    p = {"query": query, **{k: v for k, v in params.items() if v not in (None, "")}}
    st, body = c.get("/twitter", p, tag)
    return st, (body if st == 200 and isinstance(body, list) else [])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("terms", nargs="+", help="search terms, ORed inside parentheses")
    ap.add_argument("--extra", default="", help="extra query text added after the OR group, e.g. -filter:replies")
    ap.add_argument("--days", type=int, default=7, help="start_date = today (UTC) minus this many days")
    ap.add_argument("--end", help="end_date YYYY-MM-DD (UTC)")
    ap.add_argument("--sort", choices=["Top", "Latest"], default="Latest")
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--lang")
    ap.add_argument("--org", nargs="*", default=[], help="org accounts that may be named in the author column")
    ap.add_argument("--raw-authors", action="store_true", help="keep usernames, mentions and full text (private use)")
    ap.add_argument("--out", default="runs")
    a = ap.parse_args(argv)
    start = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=a.days)).isoformat()
    q = core.build_query(a.terms, a.extra)
    out = pathlib.Path(a.out) / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    c = Client(api_key(), out)
    st, posts = search(c, q, sort=a.sort, start_date=start, end_date=a.end, count=a.count, lang=a.lang)
    kept, dropped = core.clean(posts, start, a.end)
    rows = [core.row(p, a.org, public=not a.raw_authors) for p in kept]
    (out / "posts.csv").write_text(core.to_csv(rows))
    snap = {"query": q, "sort": a.sort, "start_date": start, "end_date": a.end, "count": a.count, "lang": a.lang,
            "status": st, "returned": len(posts), "kept": len(kept), "dropped_outside_window": dropped,
            "generated": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"), "calls": c.n,
            "cost_usd_total": round(c.total, 6)}
    (out / "snapshot.json").write_text(json.dumps(snap, indent=1))
    print(json.dumps({"out": str(out), **{k: snap[k] for k in ("returned", "kept", "dropped_outside_window", "cost_usd_total")}}))


if __name__ == "__main__":
    main()
