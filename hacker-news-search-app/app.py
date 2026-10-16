"""Hacker News Search App: search HN discussions with Desearch POST /desearch/ai/search (tools=["hackernews"]).

usage: python3 app.py --cli "topic" [--count 10] [--date PAST_YEAR] [--csv out.csv] [--json out.json]
       python3 app.py [--port 8000]       HTML page at /, JSON at /search?q=, CSV at /search.csv?q=
Key: DESEARCH_API_KEY_FILE (path to a key file), --key-file, or DESEARCH_API_KEY. Standard library only.
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import core

BASE = "https://api.desearch.ai"
UA = "hacker-news-search-app/0.1 (+made-by-desearch)"


def api_key(key_file=None):
    path = key_file or os.environ.get("DESEARCH_API_KEY_FILE")
    k = pathlib.Path(path).read_text().strip() if path else os.environ.get("DESEARCH_API_KEY", "").strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY_FILE or DESEARCH_API_KEY, or pass --key-file")
    return k


class Client:
    """Plain HTTP. If `log_dir` is set, each call is saved to raw/ and calls.jsonl with the key redacted."""

    def __init__(self, key, log_dir=None):
        self.key, self.n, self.total = key, 0, 0.0
        self.log = pathlib.Path(log_dir) if log_dir else None
        if self.log:
            (self.log / "raw").mkdir(parents=True, exist_ok=True)

    def _write(self, path, text, mode="w"):
        if self.key in text:
            raise RuntimeError("refusing to write a file that contains the API key")
        with open(path, mode) as f:
            f.write(text)

    def search(self, payload, tag="search"):
        self.n += 1
        url = BASE + "/desearch/ai/search"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": self.key, "Content-Type": "application/json", "User-Agent": UA})
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
        bill = {k.lower(): v for k, v in hd.items() if k.lower().startswith("x-desearch")}
        cost = float(bill.get("x-desearch-cost-usd") or 0)
        self.total += cost
        n_items = len(core.raw_items(body))
        rec = {"n": self.n, "tag": tag, "time": ts, "request": {"method": "POST", "url": url, "body": payload,
               "headers": {"Authorization": "<redacted>", "User-Agent": UA}}, "status": st, "latency_s": lat,
               "billing_headers": bill, "body_cost_usd": body.get("cost_usd") if isinstance(body, dict) else None,
               "items": n_items, "cost": cost}
        if self.log:
            self._write(self.log / "raw" / f"{self.n:03d}-{tag}.json", json.dumps({**rec, "body": body}, indent=1, ensure_ascii=False))
            self._write(self.log / "calls.jsonl", json.dumps(rec) + "\n", "a")
        print(f"[{ts}] {st} {tag} {lat}s items={n_items} cost={cost}", file=sys.stderr)
        return st, body, rec


class HNSearch:
    """Validated input in; HN items out (item links only, deduped by id). Cached in memory for 10 minutes."""

    def __init__(self, client, ttl=600, clock=time.monotonic):
        self.client, self.ttl, self.clock, self.cache = client, ttl, clock, {}

    def search(self, query, count=10, date_filter="", tag="search"):
        key = (query.lower(), count, date_filter)
        hit = self.cache.get(key)
        if hit and self.clock() - hit[0] < self.ttl:
            return 200, {**hit[1], "cached": True}
        st, body, rec = self.client.search(core.body(query, count, date_filter), tag)
        if st != 200 or not isinstance(body, dict):
            return st, {"error": body.get("detail", body) if isinstance(body, dict) else body, "status": st}
        results, stats = core.filter_items(core.raw_items(body))
        out = {"q": query, "count": count, "date": date_filter, **stats, "cost_usd": rec["cost"],
               "latency_s": rec["latency_s"], "results": results}
        self.cache[key] = (self.clock(), out)
        return 200, {**out, "cached": False}


def parse(f):
    return core.clean_query(f.get("q")), core.count_value(f.get("count")), core.date_value(f.get("date"))


def make_handler(svc):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, text, ctype):
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            f = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            page = u.path == "/"
            if page and "q" not in f:
                return self._send(200, core.render_page({}), "text/html; charset=utf-8")
            if u.path not in ("/", "/search", "/search.csv"):
                return self._send(404, '{"error": "not found"}', "application/json")
            try:
                q, c, d = parse(f)
            except core.FormError as e:
                if page:
                    return self._send(400, core.render_page(f, error=str(e)), "text/html; charset=utf-8")
                return self._send(400, json.dumps({"error": str(e)}), "application/json")
            st, out = svc.search(q, c, d)
            if st != 200:
                if page:
                    return self._send(502, core.render_page(f, error=f"API returned {st}"), "text/html; charset=utf-8")
                return self._send(502, json.dumps(out, ensure_ascii=False), "application/json")
            if u.path == "/search.csv":
                return self._send(200, core.to_csv(out["results"]), "text/csv; charset=utf-8")
            if u.path == "/search":
                return self._send(200, core.to_json(out), "application/json")
            return self._send(200, core.render_page(f, out["results"], out), "text/html; charset=utf-8")

        def log_message(self, fmt, *args):
            print("[server] " + fmt % args, file=sys.stderr)
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", metavar="TOPIC")
    ap.add_argument("--count", default="10")
    ap.add_argument("--date", default="")
    ap.add_argument("--csv")
    ap.add_argument("--json")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--key-file")
    ap.add_argument("--log-dir")
    a = ap.parse_args(argv)
    if a.cli is not None:
        try:
            q, c, d = parse({"q": a.cli, "count": a.count, "date": a.date})
        except core.FormError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        st, out = HNSearch(Client(api_key(a.key_file), a.log_dir)).search(q, c, d)
        if st != 200:
            print(json.dumps(out, ensure_ascii=False), file=sys.stderr)
            return 1
        if a.csv:
            pathlib.Path(a.csv).write_text(core.to_csv(out["results"]))
        if a.json:
            pathlib.Path(a.json).write_text(core.to_json(out))
        print(f"{out['kept']} HN items of {out['returned']} links, cost ${out['cost_usd']}")
        for r in out["results"]:
            print(f"{r['rank']:>2}. {r['title']}\n    {r['url']}")
        return 0
    svc = HNSearch(Client(api_key(a.key_file), a.log_dir))
    print(f"http://127.0.0.1:{a.port}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(svc)).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
