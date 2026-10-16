"""Tweet Search Web App: a one-page search UI for public X posts, using Desearch GET /twitter.

usage: python3 app.py [--port 8000]    then open http://127.0.0.1:8000
Key: DESEARCH_API_KEY, or a file path in DESEARCH_API_KEY_FILE. Standard library only.
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import core

BASE = "https://api.desearch.ai"
UA = "tweet-search-web-app/0.1 (+made-by-desearch)"


def api_key():
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

    def search(self, params, tag="search"):
        self.n += 1
        url = BASE + "/twitter?" + urllib.parse.urlencode(params)
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
        posts = core.posts_of(body)
        rec = {"n": self.n, "tag": tag, "time": ts, "request": {"method": "GET", "url": url,
               "headers": {"Authorization": "<redacted>", "User-Agent": UA}}, "status": st,
               "latency_s": lat, "billing_headers": bill, "items": len(posts)}
        if self.log:
            self._write(self.log / "raw" / f"{self.n:03d}-{tag}.json", json.dumps({**rec, "body": body}, indent=1, ensure_ascii=False))
            self._write(self.log / "calls.jsonl", json.dumps(rec) + "\n", "a")
        print(f"[{ts}] {st} {tag} {lat}s items={len(posts)} cost={cost}", file=sys.stderr)
        return st, body, rec


def make_handler(client):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            form = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if u.path == "/":
                return self._send(200, core.render_page(form))
            if u.path not in ("/search", "/search.csv"):
                return self._send(404, "not found", "text/plain")
            try:
                params = core.validate(form)
            except core.FormError as e:  # nothing is sent to the API, nothing is billed
                return self._send(400, core.render_page(form, error=str(e)))
            st, body, rec = client.search(params)
            if st != 200:
                return self._send(502, core.render_page(form, error=f"Search failed (HTTP {st}). Try again."))
            rows = [core.row(p) for p in core.posts_of(body)]
            if u.path == "/search.csv":
                return self._send(200, core.to_csv(rows), "text/csv; charset=utf-8",
                                  {"Content-Disposition": "attachment; filename=tweets.csv"})
            note = f"{len(rows)} of {params['count']} requested posts returned in {rec['latency_s']} s."
            bad = {k: v for k, v in core.check_filters(params, rows).items() if v}
            if bad:
                note += " Rows outside your filters: " + ", ".join(f"{k} {v}" for k, v in bad.items()) + "."
            return self._send(200, core.render_page(form, rows, note=note, csv_href="/search.csv?" + u.query))

        def log_message(self, *a):
            pass
    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--log-dir", help="save each API call (key redacted) here")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Client(api_key(), a.log_dir)))
    print(f"Open http://127.0.0.1:{a.port}")
    srv.serve_forever()
