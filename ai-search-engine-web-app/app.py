"""AI Search Engine web app on the Desearch Search API (POST /search) plus an optional cited answer.

usage: python3 app.py                       local web app at http://127.0.0.1:8000 (same /api/search and /api/answer as on Vercel)
       python3 app.py --cli "query" [--mode fast|balanced] [--count 10|15|20] [--range day|week|month|year]
                      [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--answer] [--json out.json]
Key: DESEARCH_API_KEY_FILE (path to a key file), --key-file, or DESEARCH_API_KEY. Standard library only.
"""
import argparse, json, mimetypes, os, pathlib, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from searchapp import core
from searchapp.client import Client, api_key
from searchapp.service import Engine, client_ip, parse_query

PUBLIC = pathlib.Path(__file__).parent / "public"


def make_handler(engine):
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
            if path in ("/api/search", "/api/answer"):
                fn = engine.handle_search if path == "/api/search" else engine.handle_answer
                code, headers, text = fn(parse_query(self.path), client_ip(self.headers, self.client_address[0]))
                return self._send(code, headers, text.encode())
            name = "index.html" if path == "/" else path.lstrip("/")
            f = (PUBLIC / name).resolve()
            if PUBLIC.resolve() not in f.parents or not f.is_file():
                return self._send(404, {"Content-Type": "text/plain"}, b"not found")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self._send(200, {"Content-Type": ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype.endswith("json") else "")}, f.read_bytes())

        def log_request(self, code="-", size="-"):
            pass

        def log_message(self, fmt, *args):
            pass
    return H


def print_search(res):
    s = res["stats"]
    window = f" from {res['start_date'] or 'any'} to {res['end_date'] or 'today'}" if res["start_date"] or res["end_date"] else ""
    print(f"Search: {res['query']} ({res['mode']}, {res['count']} results{window})")
    for r in res["results"]:
        print(f"{r['rank']:>2}. {r['title']}\n    {r['domain']} | {r['published_date'] or 'date not given'} | {r['url']}")
        if r["passage"]:
            print(f"    \"{r['passage'][:200]}\"")
    print(f"{s['shown']} results, {s['no_date']} without a date, {s['outside_window']} outside the date window. "
          f"Cost ${res['cost_usd']}, {res['latency_s']} s")


def print_answer(a):
    print(f"\nAnswer for: {a['query']}")
    if a["declined"]:
        print(f"The answer service wrote no summary. It said: \"{a['declined_text']}\"")
    if a["no_strong_sources"]:
        print("No strong sources: fewer than two answer links hold most of the search words.")
    for ln in a["summary"]["lines"]:
        print(f"  - {ln['text']}  " + " ".join(ln["cites"]))
    if a["summary"]["hidden"]:
        print(f"  ({a['summary']['hidden']} sentence(s) without a matching citation hidden)")
    for l in a["links"]:
        print(f"  [{l['n']}] {l['title']} ({l['domain']}, {l['published_date'] or 'date not given'})")
    if a["also_in_search_results"] is not None:
        print(f"  {a['also_in_search_results']} of {len(a['links'])} answer links also appear in the search results.")
    print(f"  Cost ${a['cost_usd']}, {a['latency_s']} s")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", metavar="QUERY")
    ap.add_argument("--mode", default="fast")
    ap.add_argument("--count", default="10")
    ap.add_argument("--range", dest="range_")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--answer", action="store_true", help="also ask for a cited answer (one more call)")
    ap.add_argument("--json")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--key-file")
    ap.add_argument("--log-dir", help="save each API call (key redacted) here")
    a = ap.parse_args(argv)
    key = api_key(a.key_file)
    if not key:
        print("Set DESEARCH_API_KEY_FILE or DESEARCH_API_KEY, or pass --key-file", file=sys.stderr)
        return 2
    os.environ.setdefault("DEMO_STATE", "memory")
    engine = Engine(client=Client(key, a.log_dir, quiet=True))
    if a.cli is None:
        print(f"http://127.0.0.1:{a.port}", file=sys.stderr)
        ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(engine)).serve_forever()
        return 0
    try:
        q = core.clean_query(a.cli)
        mode, count = core.parse_mode(a.mode), core.parse_count(a.count)
        start, end = core.date_window(a.range_, a.start, a.end)
    except core.FormError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    st, res, _ = engine.search(q, mode, count, start, end)
    if st != 200:
        print(f"error: search API returned {st}", file=sys.stderr)
        return 1
    print_search(res)
    out = {"search": res}
    if a.answer:
        st, ans, _ = engine.answer(q, [r["url"] for r in res["results"]])
        if st != 200:
            print(f"error: answer API returned {st}", file=sys.stderr)
            return 1
        print_answer(ans)
        out["answer"] = ans
    if a.json:
        pathlib.Path(a.json).write_text(core.to_json(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
