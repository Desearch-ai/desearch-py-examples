"""Web Search API Quickstart: a tiny JSON search service (GET /search?q=) on top of Desearch GET /web.

usage: python3 app.py [--port 8000]                 JSON at /search?q=..., HTML page at /
       python3 app.py --cli "your query" [--pages 1]
Key: DESEARCH_API_KEY, or a file path in DESEARCH_API_KEY_FILE (or --key-file). Standard library only.
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import core

BASE = "https://api.desearch.ai"
UA = "web-search-api-quickstart/0.1 (+made-by-desearch)"


def api_key(key_file=None):
    if key_file:
        return pathlib.Path(key_file).read_text().strip()
    k = os.environ.get("DESEARCH_API_KEY")
    if not k and os.environ.get("DESEARCH_API_KEY_FILE"):
        k = pathlib.Path(os.environ["DESEARCH_API_KEY_FILE"]).read_text().strip()
    if not k:
        sys.exit("Set DESEARCH_API_KEY or DESEARCH_API_KEY_FILE")
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

    def web(self, params, tag="web"):
        self.n += 1
        url = BASE + "/web?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": self.key, "User-Agent": UA})
        ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        t0 = time.perf_counter()
        try:
            r = urllib.request.urlopen(req, timeout=60)
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
        items = len(core.items_of(body))
        rec = {"n": self.n, "tag": tag, "time": ts, "request": {"method": "GET", "url": url,
               "headers": {"Authorization": "<redacted>", "User-Agent": UA}}, "status": st,
               "latency_s": lat, "billing_headers": bill, "items": items}
        if self.log:
            self._write(self.log / "raw" / f"{self.n:03d}-{tag}.json", json.dumps({**rec, "body": body}, indent=1, ensure_ascii=False))
            self._write(self.log / "calls.jsonl", json.dumps(rec) + "\n", "a")
        print(f"[{ts}] {st} {tag} {lat}s items={items} cost={cost}", file=sys.stderr)
        return st, body, rec


class SearchService:
    """Validated query in; results out. Pages walk start=0,20,40; results deduped by URL; cached for 10 minutes."""

    def __init__(self, client, cache=None):
        self.client, self.cache = client, cache or core.TTLCache()

    def search(self, query, pages=1, tag="search"):
        key = core.cache_key(query, pages)
        hit = self.cache.get(key)
        if hit:
            return 200, {**hit, "cached": True, "calls": 0}
        raw_pages, calls, cost, lat = [], 0, 0.0, 0.0
        for i, s in enumerate(core.starts(pages), 1):
            st, body, rec = self.client.web(core.params(query, s), f"{tag}-s{s}")
            calls += 1
            cost += float(rec["billing_headers"].get("x-desearch-cost-usd") or rec["billing_headers"].get("X-Desearch-Cost-Usd") or 0)
            lat += rec["latency_s"]
            if st != 200:
                return st, {"error": body if isinstance(body, str) else body.get("detail", body), "status": st}
            items = core.items_of(body)
            raw_pages.append(items)
            if not items:
                break
        results, per_page, repeats = core.merge(raw_pages)
        out = {"query": query, "pages": pages, "count": len(results), "new_per_page": per_page,
               "repeats_dropped": repeats, "cost_usd": round(cost, 6), "latency_s": round(lat, 2), "results": results}
        self.cache.put(key, out)
        return 200, {**out, "cached": False, "calls": calls}


def make_handler(svc):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            f = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if u.path == "/search":
                try:
                    q, p = core.clean_query(f.get("q")), core.pages_value(f.get("pages"))
                except core.FormError as e:
                    return self._send(400, json.dumps({"error": str(e)}), "application/json")
                st, out = svc.search(q, p)
                return self._send(st, json.dumps(out, ensure_ascii=False), "application/json")
            if u.path == "/":
                if "q" not in f:
                    return self._send(200, core.render_page({}), "text/html; charset=utf-8")
                try:
                    q, p = core.clean_query(f.get("q")), core.pages_value(f.get("pages"))
                except core.FormError as e:
                    return self._send(400, core.render_page(f, error=str(e)), "text/html; charset=utf-8")
                st, out = svc.search(q, p)
                if st != 200:
                    return self._send(502, core.render_page(f, error=f"API returned {st}"), "text/html; charset=utf-8")
                info = {**out, "json_href": "/search?" + urllib.parse.urlencode({"q": q, "pages": p})}
                return self._send(200, core.render_page(f, out["results"], info), "text/html; charset=utf-8")
            self._send(404, json.dumps({"error": "not found"}), "application/json")

        def log_message(self, fmt, *args):
            print("[server] " + fmt % args, file=sys.stderr)
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--cli", metavar="QUERY")
    ap.add_argument("--pages", default="1")
    ap.add_argument("--key-file")
    ap.add_argument("--log-dir")
    a = ap.parse_args(argv)
    if a.cli is not None:
        try:
            q, p = core.clean_query(a.cli), core.pages_value(a.pages)
        except core.FormError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        svc = SearchService(Client(api_key(a.key_file), a.log_dir))
        st, out = svc.search(q, p)
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0 if st == 200 else 1
    svc = SearchService(Client(api_key(a.key_file), a.log_dir))
    print(f"http://127.0.0.1:{a.port}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(svc)).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
