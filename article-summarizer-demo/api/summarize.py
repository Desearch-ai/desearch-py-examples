"""Vercel entrypoint for GET /api/summarize?url=..."""
import os
import sys
from http.server import BaseHTTPRequestHandler
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from articlesum.service import Summarize, client_ip, parse_query

SUMMARIZE = Summarize()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code, headers, text = SUMMARIZE.handle(parse_query(self.path), client_ip(self.headers, self.client_address[0]))
        data = text.encode()
        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_request(self, code="-", size="-"):
        pass

    def log_message(self, fmt, *args):
        pass
