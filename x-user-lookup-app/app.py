"""X User Lookup App: a profile card and recent posts for one public X username, using Desearch GET /twitter/user/posts.

usage: python3 app.py [--port 8000]          web UI at http://127.0.0.1:8000
       python3 app.py --cli USERNAME [--pages 3] [--csv out.csv]
Key: DESEARCH_API_KEY, or a file path in DESEARCH_API_KEY_FILE. Standard library only.
"""
import argparse, datetime as dt, json, os, pathlib, sys, time, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import core

BASE = "https://api.desearch.ai"
UA = "x-user-lookup-app/0.1 (+made-by-desearch)"


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

    def user_posts(self, params, tag="posts"):
        self.n += 1
        url = BASE + "/twitter/user/posts?" + urllib.parse.urlencode(params)
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
        items = len(core.tweets_of(body))
        rec = {"n": self.n, "tag": tag, "time": ts, "request": {"method": "GET", "url": url,
               "headers": {"Authorization": "<redacted>", "User-Agent": UA}}, "status": st,
               "latency_s": lat, "billing_headers": bill, "items": items}
        if self.log:
            self._write(self.log / "raw" / f"{self.n:03d}-{tag}.json", json.dumps({**rec, "body": body}, indent=1, ensure_ascii=False))
            self._write(self.log / "calls.jsonl", json.dumps(rec) + "\n", "a")
        print(f"[{ts}] {st} {tag} {lat}s items={items} cost={cost}", file=sys.stderr)
        return st, body, rec


def lookup(client, username, max_pages=core.MAX_PAGES, tag="lookup"):
    """Validated username in; returns (status, profile, rows, stats, info). Follows next_cursor up to max_pages."""
    pages, cursors, first, st = [], set(), None, None
    cursor = None
    for i in range(1, max_pages + 1):
        st, body, _ = client.user_posts(core.params(username, cursor), f"{tag}-p{i}")
        if st != 200:
            break
        first = first if first is not None else body
        pages.append(core.tweets_of(body))
        cursor = core.should_follow(body, cursors, i, max_pages)
        if not cursor:
            break
        cursors.add(cursor)
    rows, repeats = core.merge(pages)
    prof = core.profile(first, username) if first is not None else None
    info = {"status": st, "pages": len(pages), "per_page": [len(p) for p in pages], "repeats": repeats,
            "out_of_order": core.out_of_order(rows)}
    return st, prof, rows, core.stats(rows), info


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
            if u.path not in ("/lookup", "/lookup.csv"):
                return self._send(404, "not found", "text/plain")
            try:
                name, pages = core.clean_username(form.get("username")), core.pages_value(form.get("pages"))
            except core.FormError as e:
                return self._send(400, core.render_page(form, error=str(e)))
            st, prof, rows, s, info = lookup(client, name, pages)
            if st == 404:
                return self._send(404, core.render_page(form, error="No public X account found for that username."))
            if st != 200:
                return self._send(502, core.render_page(form, error=f"Desearch returned HTTP {st} for this username."))
            if u.path.endswith(".csv"):
                return self._send(200, core.to_csv(rows), "text/csv; charset=utf-8",
                                  {"Content-Disposition": f"attachment; filename={name}-posts.csv"})
            note = f"{info['pages']} page(s), posts per page {info['per_page']}, {info['repeats']} repeated across pages."
            if prof and not prof["found"]:
                note += " No profile came back for this username."
            return self._send(200, core.render_page(form, prof, rows, s, note=note,
                                                    csv_href="/lookup.csv?" + urllib.parse.urlencode({"username": name, "pages": pages})))

        def log_message(self, *a):
            pass
    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--cli", metavar="USERNAME")
    ap.add_argument("--pages", default=str(core.MAX_PAGES))
    ap.add_argument("--csv")
    ap.add_argument("--log-dir")
    a = ap.parse_args()
    if a.cli is not None:
        try:
            name, pages = core.clean_username(a.cli), core.pages_value(a.pages)
        except core.FormError as e:
            sys.exit(f"error: {e}")
        client = Client(api_key(), a.log_dir)
        st, prof, rows, s, info = lookup(client, name, pages)
        print(json.dumps({"profile": prof, "stats": s, "info": info, "cost_usd": round(client.total, 6)}, indent=1, ensure_ascii=False))
        if a.csv:
            pathlib.Path(a.csv).write_text(core.to_csv(rows))
        return 0 if st == 200 else 1
    client = Client(api_key(), a.log_dir)
    print(f"http://127.0.0.1:{a.port}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(client)).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
