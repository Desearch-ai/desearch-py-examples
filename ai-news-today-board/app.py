import argparse, mimetypes, os, pathlib, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from newsboard.service import Board, client_ip, parse_query

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
            if path == "/api/board":
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Board())).serve_forever()


if __name__ == "__main__":
    main()
