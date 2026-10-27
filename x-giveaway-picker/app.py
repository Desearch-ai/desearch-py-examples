"""X Giveaway Picker: standard-library HTTP server, CLI and Desearch client."""
import argparse
import datetime as dt
import html
import importlib.util
import json
import math
import os
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

spec = importlib.util.spec_from_file_location("giveaway_core", pathlib.Path(__file__).with_name("core.py"))
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

BASE = 'https://api.desearch.ai'


def api_key():
    key = os.environ.get('DESEARCH_API_KEY')
    if not key and os.environ.get('DESEARCH_API_KEY_FILE'):
        path = os.environ['DESEARCH_API_KEY_FILE']
        try:
            key = pathlib.Path(path).read_text().strip()
        except FileNotFoundError:
            raise ValueError(f'Key file not found: {path} (set by DESEARCH_API_KEY_FILE).') from None
        except (OSError, UnicodeError):
            raise ValueError(f'Cannot read key file: {path}') from None
    if not key:
        raise ValueError('Set DESEARCH_API_KEY or DESEARCH_API_KEY_FILE')
    return key


class Client:
    def __init__(self, key):
        self.key, self.total = key, 0.0
        self.lock = threading.Lock()

    def fetch(self, path, params):
        request = urllib.request.Request(BASE + path + '?' + urllib.parse.urlencode(params),
                                         headers={'Authorization': self.key,
                                                  'User-Agent': 'desearch-x-giveaway-picker/1.0'})
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        except (urllib.error.URLError, TimeoutError) as error:
            reason = getattr(error, 'reason', error)
            raise RuntimeError(f'Could not reach Desearch ({reason}). Check your connection and try again.') from None
        with response:
            headers = dict(response.headers)
            for key, value in headers.items():
                if key.lower() == 'x-desearch-cost-usd':
                    try:
                        with self.lock:
                            self.total += float(value)
                    except ValueError:
                        pass
            try:
                data = response.read()
            except (urllib.error.URLError, TimeoutError) as error:
                reason = getattr(error, 'reason', error)
                raise RuntimeError(f'Could not reach Desearch ({reason}). Check your connection and try again.') from None
            try:
                body = json.loads(data.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                if response.code == 200:
                    raise RuntimeError('Desearch returned a non-JSON response (HTTP 200)') from None
                body = None
            return response.code, body, headers


def render(result=None, error=None, values=None):
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
<p><label>Draw timestamp (ISO UTC, optional, to repeat a draw) <input name="draw_timestamp"></label></p>
<button>Collect and draw</button></form>'''
    defaults = dict(post='', must_repost=True, must_reply=False, winners='1', min_tags='0',
                    min_account_age_days='', min_followers='', count='50', draw_timestamp='')
    if values is not None:
        defaults.update(values)
    def fill(match):
        tag = match.group(0)
        name = re.search(r'name="([^"]+)"', tag).group(1)
        tag = re.sub(r' value="[^"]*"| checked', '', tag)
        if name in ('must_repost', 'must_reply'):
            return tag[:-1] + (' checked>' if defaults[name] else '>')
        return tag[:-1] + ' value="' + escape(defaults.get(name, '')) + '">'
    page = re.sub(r'<input\b[^>]*>', fill, page)
    if error:
        page += '<p>' + escape(error) + '</p>'
    if result:
        if result.get('error'):
            page += '<p>' + escape(result['error']) + '</p>'
        else:
            page += '<p>' + escape(result.get('partial_reply_warning', '')) + '</p>'
            if result.get('draw_pending_confirmation'):
                page += '<form method="post" action="/pick">'
                for name, value in defaults.items():
                    if name in ('must_repost', 'must_reply'):
                        if not value:
                            continue
                        value = 'on'
                    page += '<input type="hidden" name="' + escape(name) + '" value="' + escape(value) + '">'
                page += '<input type="hidden" name="confirm_partial_replies" value="1"><p>Press Draw anyway to draw from the replies that came back. This uses the cached list, so it makes no new API calls and does not use a run.</p><button>Draw anyway</button></form>'
            rules, counts = result['rules'], result['counts']
            if rules['must_reply']:
                rc = result['reply_coverage']
                page += f"<p>Replies: {rc['returned']} returned by the API of {rc['reported']} the post shows ({rc['unique_authors']} unique {core.plural(rc['unique_authors'], 'author')}).</p>"
            rule_labels = [('entry_mode', 'Entry mode'), ('winners', 'Winners requested'),
                           ('min_tags', 'Minimum tags'), ('min_account_age_days', 'Minimum account age days'),
                           ('min_followers', 'Minimum followers'), ('count', 'Reply count'),
                           ('draw_timestamp', 'Draw timestamp')]
            page += '<p>Rules: ' + escape('; '.join(f'{label}: {rules[key] if rules[key] is not None else "off"}' for key, label in rule_labels)) + '</p>'
            page += '<p>' + escape(f"Accounts collected: {counts['entrants']}; Accounts qualified: {counts['eligible']}; Winners requested: {counts['winners_requested']}; Winners drawn: {counts['winners_drawn']}") + '</p>'
            summary = result['message']
            if result['exclusions']:
                reasons = sorted(result['exclusions'].items(), key=lambda item: (-item[1], item[0]))
                total = sum(result['exclusions'].values())
                exclusions = f"Not eligible: {total} {core.plural(total, 'account')} (counted once, by the first rule each failed): " + ', '.join(f'{name} ({count})' for name, count in reasons) + '.'
                summary = ' '.join(part for part in (summary, exclusions) if part)
            if summary:
                page += '<p>' + escape(summary) + '</p>'
            page += '<p>' + escape(result['coverage']) + '</p><p>Seed: ' + escape(result['seed']) + '</p>'
            winner_text = ', '.join('@' + row['username'] for row in result['winners']) or ('Draw pending confirmation' if result['draw_pending_confirmation'] else 'No eligible accounts')
            page += '<p>Winners: ' + escape(winner_text) + '</p>'
            page += '<p>' + escape(' | '.join(result['notices'])) + '</p>'
            page += '<p>Reported request cost (USD): ' + escape(result['cost_usd']) + '</p>'
            page += '<a href="/entrants.csv?token=' + escape(result['token']) + '">Export entrants CSV</a>'
    return page


def make_handler(client, *, limiter=None, cache=None, clock=None):
    clock = clock or time.time
    limiter = limiter if limiter is not None else core.RateLimiter(clock=clock)
    cache = cache if cache is not None else core.CollectionCache(clock=clock)
    exports = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type='text/html; charset=utf-8', retry_after=None):
            payload = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            if retry_after is not None:
                self.send_header('Retry-After', str(retry_after))
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
            values = {}
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 16384:
                    raise ValueError('Invalid form size')
                form = {key: values[0] for key, values in urllib.parse.parse_qs(self.rfile.read(length).decode(), keep_blank_values=True).items()}
                form['must_repost'] = form.get('must_repost') == 'on'
                form['must_reply'] = form.get('must_reply') == 'on'
                values = dict(form)
                allowed_fields = {'post', 'winners', 'min_tags', 'min_account_age_days',
                                  'min_followers', 'must_repost', 'must_reply', 'count', 'draw_timestamp', 'confirm_partial_replies'}
                if 'post' not in form or set(form) - allowed_fields:
                    raise ValueError('Invalid form fields')
                confirmed = form.pop('confirm_partial_replies', '') == '1'
                stamp = form.pop('draw_timestamp', None) or None
                options = core.validate(**form)
                now = dt.datetime.fromtimestamp(clock(), dt.timezone.utc)
                core.draw_time(stamp, now)
                # Part snapshots also determine whether this run consumes a rate-limit slot.
                parts = cache.snapshot(options)
                cached = all(v is not None for v in parts.values())
                if not cached:
                    allowed, retry = limiter.allow(self.client_address[0])
                    if not allowed:
                        message = f"Rate limit reached: 2 uncached runs per 10 minutes and 5 per day per IP. Try again in about {math.ceil(retry / 60)} {core.plural(math.ceil(retry / 60), 'minute')}. Cached posts can still be re-drawn."
                        return self.send(429, render(error=message, values=values), retry_after=retry)
                collection = cache.collect(client.fetch, options, parts, now)
                warning = core.partial_reply_warning(collection, options)
                result = core.decide(collection, options, now=now, draw_timestamp=stamp,
                                     perform_draw=not warning or confirmed)
                result['token'] = uuid.uuid4().hex
                with lock:
                    if len(exports) >= 100:
                        exports.pop(next(iter(exports)))
                    exports[result['token']] = core.to_csv(result['entrants'])
                self.send(200, render(result, values=values))
            except ValueError as error:
                self.send(400, render(error=str(error), values=values))
            except Exception as error:
                self.send(502, render(error=str(error), values=values))

        def log_message(self, *args):
            pass
    return Handler


def demo_fetch(path, params):
    filenames = {'/twitter/urls': 'post.json', '/twitter/post/retweeters': 'retweeters.json',
                 '/twitter/replies/post': 'replies.json'}
    body = json.loads((pathlib.Path(__file__).parent / 'samples' / filenames[path]).read_text())
    return 200, body, {}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='Example: python3 app.py --cli 123 --mode repost --winners 2')
    parser.add_argument('--port', type=int, default=8000, help='Local web server port (default: 8000)')
    parser.add_argument('--cli', metavar='POST', help='Collect and draw once for a post URL or id')
    parser.add_argument('--mode', choices=['repost', 'reply', 'both'], default='repost', help='Require reposts, replies, or both')
    for name, default in [('winners', '1'), ('min-tags', '0'), ('min-account-age-days', None), ('min-followers', None), ('count', '50')]:
        parser.add_argument('--' + name, default=default, help={'winners': 'Number of winners, 1 to 10', 'min-tags': 'Minimum distinct tags in one reply, 0 to 5', 'min-account-age-days': 'Minimum account age in days', 'min-followers': 'Minimum follower count', 'count': 'Number of replies requested, 1 to 100'}[name])
    parser.add_argument('--draw-timestamp', help='ISO UTC timestamp for reproducible draws')
    parser.add_argument('--csv', help='Write entrants CSV to this path')
    parser.add_argument('--accept-partial-replies', action='store_true', help='Draw even when fewer replies return than reported')
    parser.add_argument('--demo-fixtures', action='store_true', help='Use offline sample responses with --cli')
    args = parser.parse_args()
    try:
        rules = dict(winners=args.winners, min_tags=args.min_tags, min_account_age_days=args.min_account_age_days,
                     min_followers=args.min_followers, count=args.count,
                     must_repost=args.mode in ('repost', 'both'), must_reply=args.mode in ('reply', 'both'))
        if args.cli is not None:
            core.validate(args.cli, **rules)
            core.draw_time(args.draw_timestamp, dt.datetime.now(dt.timezone.utc))
            fetch = demo_fetch if args.demo_fixtures else Client(api_key()).fetch
            options = core.validate(args.cli, **rules)
            now = dt.datetime.now(dt.timezone.utc)
            collection = core.collect(fetch, options, now=now)
            warning = core.partial_reply_warning(collection, options)
            accepted = True
            if warning:
                print(warning, file=sys.stderr)
                accepted = args.accept_partial_replies
                if not accepted and sys.stdin.isatty():
                    print('Draw anyway? [y/N]', file=sys.stderr, end=' ', flush=True)
                    accepted = sys.stdin.readline().strip().lower() in ('y', 'yes')
                elif not accepted:
                    print('Re-run with --accept-partial-replies to draw anyway.', file=sys.stderr)
            result = core.decide(collection, options, now=now, draw_timestamp=args.draw_timestamp, perform_draw=accepted)
            for notice in result['notices']:
                if notice.startswith(('The post has no replies', 'reply collection failed')):
                    print(notice, file=sys.stderr)
            if result.get('message'):
                print(result['message'], file=sys.stderr)
            print(json.dumps(result, indent=2))
            if args.csv:
                pathlib.Path(args.csv).write_text(core.to_csv(result['entrants']))
            return 1 if result.get('error') else 3 if not accepted else 0
        if args.demo_fixtures:
            raise ValueError('--demo-fixtures requires --cli')
        server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(Client(api_key())))
        print(f'http://127.0.0.1:{args.port}', file=sys.stderr)
        server.serve_forever()
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    sys.exit(main())
