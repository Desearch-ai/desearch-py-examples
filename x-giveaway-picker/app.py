"""X Giveaway Picker: standard-library HTTP server, CLI and Desearch client."""
import argparse
import html
import json
import os
import pathlib
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import core

BASE = 'https://api.desearch.ai'


def api_key():
    key = os.environ.get('DESEARCH_API_KEY')
    if not key and os.environ.get('DESEARCH_API_KEY_FILE'):
        key = pathlib.Path(os.environ['DESEARCH_API_KEY_FILE']).read_text().strip()
    if not key:
        raise ValueError('Set DESEARCH_API_KEY or DESEARCH_API_KEY_FILE')
    return key


class Client:
    def __init__(self, key):
        self.key, self.total = key, 0.0
        self.lock = threading.Lock()

    def fetch(self, path, params):
        request = urllib.request.Request(BASE + path + '?' + urllib.parse.urlencode(params),
                                         headers={'Authorization': self.key})
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            headers = dict(response.headers)
            for key, value in headers.items():
                if key.lower() == 'x-desearch-cost-usd':
                    try:
                        with self.lock:
                            self.total += float(value)
                    except ValueError:
                        pass
            return response.code, json.loads(response.read().decode()), headers


def render(result=None, error=None):
    escape = lambda value: html.escape(str(value), quote=True)
    page = '''<!doctype html><meta charset="utf-8"><title>X Giveaway Picker</title>
<style>body{font:16px system-ui;max-width:850px;margin:40px auto;padding:16px}input{margin:6px}pre{white-space:pre-wrap}</style>
<h1>X Giveaway Picker</h1><form method="post" action="/pick">
<p><input name="post" placeholder="X post URL or id" required size="50"></p>
<label><input type="checkbox" name="must_repost" checked>Must repost</label>
<label><input type="checkbox" name="must_reply">Must reply</label><p>
<label>Winners <input type="number" name="winners" value="1" min="1" max="10"></label>
<label>Tags <input type="number" name="min_tags" value="0" min="0" max="5"></label></p>
<p><label>Minimum account age in days <input type="number" name="min_account_age_days" min="0"></label>
<label>Minimum followers <input type="number" name="min_followers" min="0"></label></p>
<label>Reply count <input type="number" name="count" value="50" min="1" max="100"></label>
<button>Collect and draw</button></form>'''
    if error:
        page += '<p>' + escape(error) + '</p>'
    if result:
        if result.get('error'):
            page += '<p>' + escape(result['error']) + '</p>'
        else:
            page += '<p>' + escape(result['coverage']) + '</p><p>Seed: ' + escape(result['seed']) + '</p>'
            page += '<p>Winners: ' + escape(', '.join('@' + row['username'] for row in result['winners']) or 'No eligible accounts') + '</p>'
            page += '<p>' + escape(' | '.join(result['notices'])) + '</p>'
            page += '<p>Reported request cost (USD): ' + escape(result['cost_usd']) + '</p>'
            page += '<a href="/entrants.csv?token=' + escape(result['token']) + '">Export entrants CSV</a>'
    return page


def make_handler(client):
    exports = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type='text/html; charset=utf-8'):
            payload = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path == '/':
                return self.send(200, render())
            token = urllib.parse.parse_qs(url.query).get('token', [''])[0]
            with lock:
                csv_text = exports.get(token)
            if url.path == '/entrants.csv' and csv_text is not None:
                return self.send(200, csv_text, 'text/csv; charset=utf-8')
            self.send(404, 'not found', 'text/plain')

        def do_POST(self):
            if self.path != '/pick':
                return self.send(404, 'not found')
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 16384:
                    raise ValueError('Invalid form size')
                form = {key: values[0] for key, values in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
                form['must_repost'] = form.get('must_repost') == 'on'
                form['must_reply'] = form.get('must_reply') == 'on'
                result = core.pick(client.fetch, **form)
                result['token'] = uuid.uuid4().hex
                with lock:
                    if len(exports) >= 100:
                        exports.pop(next(iter(exports)))
                    exports[result['token']] = core.to_csv(result['entrants'])
                self.send(200, render(result))
            except ValueError as error:
                self.send(400, render(error=str(error)))
            except Exception:
                self.send(502, render(error='Collection failed. Please check the API connection and key.'))

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--cli', metavar='POST')
    parser.add_argument('--mode', choices=['repost', 'reply', 'both'], default='repost')
    for name, default in [('winners', '1'), ('min-tags', '0'), ('min-account-age-days', None), ('min-followers', None), ('count', '50')]:
        parser.add_argument('--' + name, default=default)
    parser.add_argument('--draw-timestamp', help='ISO UTC timestamp for reproducible draws')
    parser.add_argument('--csv')
    args = parser.parse_args()
    try:
        rules = dict(winners=args.winners, min_tags=args.min_tags, min_account_age_days=args.min_account_age_days,
                     min_followers=args.min_followers, count=args.count,
                     must_repost=args.mode in ('repost', 'both'), must_reply=args.mode in ('reply', 'both'))
        if args.cli is not None:
            core.validate(args.cli, **rules)
            result = core.pick(Client(api_key()).fetch, args.cli, draw_timestamp=args.draw_timestamp, **rules)
            print(json.dumps(result, indent=2))
            if args.csv:
                pathlib.Path(args.csv).write_text(core.to_csv(result['entrants']))
            return 1 if result.get('error') else 0
        server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(Client(api_key())))
        print(f'http://127.0.0.1:{args.port}', file=sys.stderr)
        server.serve_forever()
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    sys.exit(main())
