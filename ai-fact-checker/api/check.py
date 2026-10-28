"""Vercel Python function: GET /api/check?claim=...&wiki=1  (DESEARCH_API_KEY is set on the Vercel project)."""
import os, sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factcheck.service import Checker, client_ip, parse_query  # noqa: E402

CHECKER = Checker()   # module-level: the result cache lives with the warm instance; limits and the cap are shared via Redis when configured


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code, headers, text = CHECKER.handle(parse_query(self.path), client_ip(self.headers, self.client_address[0]))
        data = text.encode()
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):   # no request lines in logs (they would contain the claim text)
        pass
