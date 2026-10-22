import os, sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from newsboard.service import Board, client_ip, parse_query  # noqa: E402

CHECKER = Board()   # module-level: limiter, cap and cache live as long as the warm instance


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
