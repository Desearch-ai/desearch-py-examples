"""AI Fact Checker: find sources for and against one claim with the Desearch API.

usage: python3 app.py                      local web app at http://127.0.0.1:8000 (same /api/check as on Vercel)
       python3 app.py --cli "claim" [--wiki] [--json out.json] [--html out.html]
Key: DESEARCH_API_KEY_FILE (path to a key file), --key-file, or DESEARCH_API_KEY. Standard library only.
"""
import argparse, mimetypes, os, pathlib, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from factcheck import core
from factcheck.client import Client, api_key
from factcheck.service import Checker, client_ip, parse_query

PUBLIC = pathlib.Path(__file__).parent / "public"


def make_handler(checker):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, headers, data):
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/check":
                code, headers, text = checker.handle(parse_query(self.path), client_ip(self.headers, self.client_address[0]))
                return self._send(code, headers, text.encode())
            name = "index.html" if path == "/" else path.lstrip("/")
            f = (PUBLIC / name).resolve()
            if PUBLIC.resolve() not in f.parents or not f.is_file():
                return self._send(404, {"Content-Type": "text/plain"}, b"not found")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self._send(200, {"Content-Type": ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype.endswith("json") else "")}, f.read_bytes())

        def log_message(self, fmt, *args):
            pass
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", metavar="CLAIM")
    ap.add_argument("--wiki", action="store_true", help="also search Wikipedia (one more call)")
    ap.add_argument("--json")
    ap.add_argument("--html")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--key-file")
    ap.add_argument("--log-dir", help="save each API call (key redacted) here")
    a = ap.parse_args(argv)
    key = api_key(a.key_file)
    if not key:
        print("Set DESEARCH_API_KEY_FILE or DESEARCH_API_KEY, or pass --key-file", file=sys.stderr)
        return 2
    checker = Checker(client=Client(key, a.log_dir))
    if a.cli is not None:
        try:
            claim = core.clean_claim(a.cli)
        except core.FormError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        st, res, _ = checker.run(claim, a.wiki)
        if st != 200:
            print(f"error: search API returned {st}", file=sys.stderr)
            return 1
        if a.json:
            pathlib.Path(a.json).write_text(core.to_json(res))
        if a.html:
            pathlib.Path(a.html).write_text(core.render_html(res))
        print(f"Claim: {res['claim']}")
        print("No strong sources found." if res["no_strong_sources"] else f"{res['strong']} sources contain most of the claim's key words.")
        for ln in res["summary"]["lines"]:
            print(f"  - {ln['text']}")
        if res["summary"]["hidden"]:
            print(f"  ({res['summary']['hidden']} uncited summary sentence(s) hidden)")
        for s in res["sources"]:
            print(f"{s['rank']:>2}. [{s['label']}] {s['title']}\n    {s['url']}")
        print(f"X posts: {len(res['posts'])} on topic of {res['x_returned']} for query '{res['x_query']}'. Cost ${res['cost_usd']} ({res['calls']} calls)")
        return 0
    os.environ.setdefault("DEMO_LIVE", "1")
    print(f"http://127.0.0.1:{a.port}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(checker)).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
