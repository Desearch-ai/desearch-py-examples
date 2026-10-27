"""Vercel Python function: GET /api/answer (DESEARCH_API_KEY is set on the Vercel project, server-side only)."""
import os, sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from searchapp.service import Engine, client_ip, parse_query  # noqa: E402

ENGINE = Engine()   # shared state lives in Redis


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code, headers, text = ENGINE.handle_answer(parse_query(self.path), client_ip(self.headers, self.client_address[0]))
        data = text.encode()
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_request(self, code="-", size="-"):
        pass

    def log_message(self, fmt, *args):   # no request lines in logs (they would contain the search text)
        pass
