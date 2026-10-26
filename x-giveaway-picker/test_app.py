"""Offline web integration tests; only a loopback server is contacted."""
import io
import http.client
import importlib.util
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer

import pytest

spec = importlib.util.spec_from_file_location('giveaway_app', pathlib.Path(__file__).with_name('app.py'))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def test_client_request_headers(monkeypatch):
    def urlopen(request, timeout):
        assert request.get_header('User-agent') == 'desearch-x-giveaway-picker/1.0'
        assert request.get_header('Authorization') == 'test-secret-key'
        response = io.BytesIO(b'[]')
        response.code = 200
        response.headers = {'X-Test': 'preserved'}
        return response

    monkeypatch.setattr(app.urllib.request, 'urlopen', urlopen)
    assert app.Client('test-secret-key').fetch('/twitter/urls', {'urls': '9000'}) == (
        200, [], {'X-Test': 'preserved'})


def test_client_plain_text_403_cli(monkeypatch, capsys):
    key = 'test-secret-key'

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden',
                                     {'X-Test': 'preserved'}, io.BytesIO(b'error code: 1010'))

    monkeypatch.setattr(app.urllib.request, 'urlopen', urlopen)
    assert app.Client(key).fetch('/twitter/urls', {}) == (403, None, {'X-Test': 'preserved'})
    monkeypatch.setenv('DESEARCH_API_KEY', key)
    monkeypatch.setattr(sys, 'argv', ['app.py', '--cli', '9000'])
    with pytest.raises(SystemExit) as error:
        app.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert output.err == "Desearch refused the request at the edge (HTTP 403). This is not a key problem; check the client's User-Agent and network.\n"
    assert key not in output.out + output.err


@pytest.mark.parametrize('body', [b'not JSON', b'\xff'])
def test_client_non_json_200(monkeypatch, body):
    def urlopen(request, timeout):
        response = io.BytesIO(body)
        response.code = 200
        response.headers = {}
        return response

    monkeypatch.setattr(app.urllib.request, 'urlopen', urlopen)
    with pytest.raises(RuntimeError, match=r'^Desearch returned a non-JSON response \(HTTP 200\)$'):
        app.Client('test-secret-key').fetch('/twitter/urls', {})


@pytest.fixture(autouse=True)
def block_external_connections(monkeypatch):
    connect = socket.socket.connect

    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] != '127.0.0.1':
            raise AssertionError('Only loopback connections are allowed in tests')
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', local_only)


class Clock:
    value = 1792713600

    def __call__(self):
        return self.value


class Client:
    def __init__(self):
        self.calls = []

    def fetch(self, path, params):
        self.calls.append((path, params))
        if path == '/twitter/urls':
            return 200, [{'id': app.core.post_id(params['urls']), 'retweet_count': 2}], {}
        return 200, {'users': [{'id': '900001', 'username': 'entrant_01'}], 'next_cursor': None}, {}


@pytest.fixture
def web():
    client, clock = Client(), Clock()
    limiter = app.core.RateLimiter(clock)
    cache = app.core.CollectionCache(clock=clock)
    handler = app.make_handler(client, limiter=limiter, cache=cache, clock=clock)
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    except PermissionError:
        pytest.skip('This sandbox prohibits even loopback sockets')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(post=None, path='/pick', **fields):
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
        try:
            if post is None:
                connection.request('GET', path)
            else:
                data = dict(post=post, must_repost='on', draw_timestamp='2026-10-23T00:00:00Z')
                data.update(fields)
                connection.request('POST', path, urllib.parse.urlencode(data),
                                   {'Content-Type': 'application/x-www-form-urlencoded', 'X-Forwarded-For': str(post)})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    yield request, client, clock, limiter
    server.shutdown()
    server.server_close()
    thread.join()


def test_limits_cache_and_csv(web):
    request, client, clock, limiter = web
    assert request('9000')[0] == 200
    assert request('9001')[0] == 200
    calls = len(client.calls)
    status, headers, body = request('9002')
    assert status == 429 and int(headers['Retry-After']) == 600
    assert '<style>' in body and 'Rate limit reached: 2 uncached runs' in body
    assert 'name="post"' in body and 'value="9002"' in body
    assert headers['Content-Type'].startswith('text/html')
    assert len(client.calls) == calls
    status, _, body = request('9000')
    assert status == 200 and 'no new API calls' in body
    assert len(client.calls) == calls
    token = re.search(r'/entrants.csv\?token=([a-f0-9]+)', body).group(1)
    status, headers, csv = request(path='/entrants.csv?token=' + token)
    assert status == 200 and headers['Content-Type'].startswith('text/csv')
    assert 'entrant_01' in csv and len(client.calls) == calls
    clock.value += 600
    assert request('9002')[0] == 200


def test_invalid_input_never_counts(web):
    request, client, _, limiter = web
    for post, fields in [('bad', {}), ('9000', {'winners': '0'}),
                         ('9000', {'draw_timestamp': 'bad'})]:
        assert request(post, **fields)[0] == 400
    assert not client.calls and not limiter.runs
    assert request('9000')[0] == 200
    assert request('9001')[0] == 200


def test_demo_cli():
    env = {key: os.environ[key] for key in os.environ
           if key not in ('DESEARCH_API_KEY', 'DESEARCH_API_KEY_FILE')}
    command = [sys.executable, '-c',
               "import runpy, socket, sys; socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden')); runpy.run_path(sys.argv.pop(1), run_name='__main__')",
               str(pathlib.Path(__file__).with_name('app.py')),
               '--cli', '900001234567890', '--demo-fixtures', '--mode', 'both',
               '--draw-timestamp', '2026-10-23T00:00:00Z']
    first = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    second = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr == ''
    readme = pathlib.Path(__file__).with_name('README.md').read_text()
    sample = readme.split('## Sample output\n', 1)[1].split('```json\n', 1)[1].split('```', 1)[0]
    assert sample == first.stdout
    result = json.loads(first.stdout)
    assert result['seed'] == '900001234567890:2026-10-23T00:00:00Z'
    assert result['winners'][0]['username'] == 'entrant_01'
    assert result['cost_usd'] == 0.0


def test_handler_without_socket():
    # Exercise the HTTP handler even in environments that prohibit loopback sockets.
    client, clock = Client(), Clock()
    limiter = app.core.RateLimiter(clock)
    handler = app.make_handler(client, limiter=limiter, clock=clock)

    class Connection:
        def __init__(self, raw):
            self.input = io.BytesIO(raw)
            self.output = io.BytesIO()

        def makefile(self, *args):
            return self.input

        def sendall(self, data):
            self.output.write(data)

    def request(post=None, path='/pick', **fields):
        if post is None:
            raw = f'GET {path} HTTP/1.0\r\n\r\n'.encode()
        else:
            data = dict(post=post, must_repost='on')
            data.update(fields)
            body = urllib.parse.urlencode(data).encode()
            raw = f'POST /pick HTTP/1.0\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body
        connection = Connection(raw)
        handler(connection, ('127.0.0.1', 1), object())
        return connection.output.getvalue().decode()

    assert '400 Bad Request' in request('bad')
    assert '400 Bad Request' in request('9000', draw_timestamp='bad')
    assert not limiter.runs and not client.calls
    assert '200 OK' in request('9000')
    assert '200 OK' in request('9001')
    calls = len(client.calls)
    refused = request('9002')
    assert '429 Too Many Requests' in refused and 'Retry-After: 600' in refused
    cached = request('9000')
    assert '200 OK' in cached and 'no new API calls' in cached
    token = re.search(r'/entrants.csv\?token=([a-f0-9]+)', cached).group(1)
    assert 'entrant_01' in request(path='/entrants.csv?token=' + token)
    assert len(client.calls) == calls


@pytest.mark.parametrize('status,detail,expected', [
    (401, 'bad', 'refused the API key (HTTP 401)'),
    (403, 'bad', 'refused the API key (HTTP 403)'),
    (402, 'Check credits/balance at console.desearch.ai', 'payment required'),
    (429, 'slow', 'Wait and try again.'),
    (503, 'maintenance', 'server error (HTTP 503): maintenance'),
    (404, 'missing', 'HTTP 404: missing')])
def test_readable_api_errors(status, detail, expected):
    error = app.core.APIError(status, {'detail': detail})
    assert error.status == status and error.detail == detail
    assert expected in str(error)


@pytest.mark.parametrize('error', [urllib.error.URLError('offline'), TimeoutError('timed out')])
def test_network_errors(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(app.urllib.request, 'urlopen', fail)
    with pytest.raises(RuntimeError, match='Could not reach Desearch .*Check your connection'):
        app.Client('fake').fetch('/twitter/urls', {})


@pytest.mark.parametrize('exception,expected', [(FileNotFoundError(), 'Key file not found: fake-path (set by DESEARCH_API_KEY_FILE).'), (PermissionError(), 'Cannot read key file: fake-path')])
def test_key_file_errors_without_reading_keys(monkeypatch, exception, expected):
    monkeypatch.delenv('DESEARCH_API_KEY', raising=False)
    monkeypatch.setenv('DESEARCH_API_KEY_FILE', 'fake-path')
    def fail(*args):
        raise exception
    monkeypatch.setattr(pathlib.Path, 'read_text', fail)
    with pytest.raises(ValueError, match=re.escape(expected)):
        app.api_key()


@pytest.mark.parametrize('tty,answer,flag,code,drawn', [(False, '', False, 3, False), (False, '', True, 0, True), (True, 'yes', False, 0, True), (True, 'n', False, 3, False)])
def test_partial_cli_collects_once(monkeypatch, capsys, tmp_path, tty, answer, flag, code, drawn):
    calls = []
    def fetch(path, params):
        calls.append(path)
        if path == '/twitter/urls':
            return 200, [{'id': '1', 'reply_count': 39}], {}
        return 200, [{'user': {'id': '2', 'username': 'two'}}], {}
    monkeypatch.setattr(app, 'demo_fetch', fetch)
    stdin = io.StringIO(answer)
    monkeypatch.setattr(stdin, 'isatty', lambda: tty)
    monkeypatch.setattr(sys, 'stdin', stdin)
    csv = tmp_path / 'entrants.csv'
    monkeypatch.setattr(sys, 'argv', ['app.py', '--cli', '1', '--mode', 'reply', '--demo-fixtures', '--csv', str(csv)] + (['--accept-partial-replies'] if flag else []))
    assert app.main() == code
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['drawn'] == drawn and len(result['winners']) == int(drawn)
    assert 'Only 1 of 39' in output.err and len(calls) == 2
    assert 'two' in csv.read_text()
    assert ('Draw anyway?' in output.err) == (tty and not flag)


def socketless_request(handler, fields):
    body = urllib.parse.urlencode(fields).encode()
    class Connection:
        def __init__(self):
            self.input = io.BytesIO(f'POST /pick HTTP/1.0\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body)
            self.output = io.BytesIO()
        def makefile(self, *args):
            return self.input
        def sendall(self, data):
            self.output.write(data)
    connection = Connection()
    handler(connection, ('127.0.0.1', 1), object())
    return connection.output.getvalue().decode()


def test_web_partial_confirmation_cache_and_modes():
    class Fake:
        calls = []
        def fetch(self, path, params):
            self.calls.append(path)
            if path == '/twitter/urls':
                return 200, [{'id': '1', 'reply_count': 39}], {}
            if path.endswith('retweeters'):
                return 200, {'users': [{'id': '2'}]}, {}
            return 200, [{'user': {'id': '2'}}], {}
    fake = Fake()
    limiter = app.core.RateLimiter(Clock())
    handler = app.make_handler(fake, limiter=limiter, clock=Clock())
    fields = dict(post='1', must_repost='on', must_reply='on', winners='5', count='20')
    first = socketless_request(handler, fields)
    assert 'Draw anyway' in first and 'Only 1 of 39' in first
    assert 'Winners drawn: 0' in first and 'Export entrants CSV' in first
    assert 'Replies: 1 returned by the API of 39' in first
    explanation = 'Press Draw anyway to draw from the replies that came back. This uses the cached list, so it makes no new API calls and does not use a run.'
    assert explanation in first
    assert first.index(explanation) < first.index('<button>Draw anyway</button>')
    assert 'value="20"' in first
    confirmed = socketless_request(handler, dict(fields, confirm_partial_replies='1'))
    assert 'Draw anyway' not in confirmed and 'instead of 5' in confirmed
    assert len(fake.calls) == 3 and len(limiter.runs['127.0.0.1']) == 1
    repost = socketless_request(handler, dict(post='1', must_repost='on'))
    assert 'Replies:' not in repost
    reply = socketless_request(handler, dict(post='1', must_reply='on', count='20'))
    assert 'Replies: 1 returned by the API of 39 the post shows (1 unique authors).' in reply
    assert len(fake.calls) == 3 and len(limiter.runs['127.0.0.1']) == 1


def test_web_forms_errors_and_styled_limit():
    client, clock = Client(), Clock()
    handler = app.make_handler(client, clock=clock)
    invalid = socketless_request(handler, dict(post='<script>"', must_reply='on', winners='0', min_tags='3', min_account_age_days='10', min_followers='4', count='17', draw_timestamp='bad'))
    assert '400 Bad Request' in invalid and '&lt;script&gt;&quot;' in invalid
    for value in ('0', '3', '10', '4', '17', 'bad'):
        assert f'value="{value}"' in invalid
    assert 'name="must_reply" checked' in invalid
    for post in ('1', '2'):
        socketless_request(handler, dict(post=post, must_repost='on'))
    limited = socketless_request(handler, dict(post='3', must_reply='on', count='17'))
    assert '429 Too Many Requests' in limited and 'Retry-After: 600' in limited
    assert '<style>' in limited and 'text/html' in limited and 'Cached posts can still be re-drawn.' in limited
    assert 'value="17"' in limited


def test_web_readable_api_error():
    class Failure:
        def fetch(self, *args):
            return 503, {'detail': 'maintenance'}, {}
    output = socketless_request(app.make_handler(Failure()), dict(post='1', must_repost='on'))
    assert '502 Bad Gateway' in output and 'server error (HTTP 503): maintenance' in output


def test_cli_help_all_flags(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['app.py', '--help'])
    with pytest.raises(SystemExit) as error:
        app.main()
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert 'Example:' in output
    for flag in ('port', 'cli', 'mode', 'winners', 'min-tags', 'min-account-age-days', 'min-followers', 'count', 'draw-timestamp', 'csv', 'demo-fixtures', 'accept-partial-replies'):
        assert re.search(r'--' + flag + r'.*\S', output)


def test_cli_zero_qualifiers_message(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['app.py', '--cli', '1', '--demo-fixtures', '--min-followers', '999999'])
    assert app.main() == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert 'No accounts met the rules, so no winners were drawn.' in output.err
    assert result['counts']['eligible'] == 0
    assert result['exclusions'] == {'not enough followers or unknown': 1}


def test_success_form_preserves_every_value():
    fields = dict(post='x.com/demo/status/1', must_reply='on', winners='2', min_tags='3', min_account_age_days='10', min_followers='4', count='17', draw_timestamp='2026-10-23T00:00:00Z')
    # An empty reply response with zero reported replies needs no confirmation.
    class Empty:
        def fetch(self, path, params):
            return (200, [{'id': '1', 'reply_count': 0}], {}) if path == '/twitter/urls' else (200, [], {})
    output = socketless_request(app.make_handler(Empty(), clock=Clock()), fields)
    assert '200 OK' in output
    for key, value in fields.items():
        if key != 'must_reply':
            assert f'value="{value}"' in output
    assert 'name="must_reply" checked' in output
    assert 'name="must_repost" checked' not in output


def test_public_copy_has_no_em_dash():
    for filename in ('README.md', 'app.py', 'core.py'):
        assert '\u2014' not in pathlib.Path(__file__).with_name(filename).read_text()


@pytest.mark.parametrize('exclusions,expected', [
    ({'post author': 1, 'must repost': 2, 'reply not returned': 39},
     'Not eligible: reply not returned (39), must repost (2), post author (1).'),
    ({'z <tag>': 2, 'a & b': 2}, 'Not eligible: a &amp; b (2), z &lt;tag&gt; (2).'),
    ({}, '')])
def test_render_readable_exclusions(exclusions, expected):
    result = app.core.pick(Client().fetch, '9000', must_repost=True)
    result.update(token='test', message='Draw message.', exclusions=exclusions)
    page = app.render(result)
    assert '<p>Draw message.' in page
    if expected:
        assert 'Draw message. ' + expected + '</p>' in page
    else:
        assert '<p>Draw message.</p>' in page
        assert 'Not eligible:' not in page
    assert app.html.escape(json.dumps(exclusions)) not in page


@pytest.mark.parametrize('status,body', [(401, None), (401, {}), (403, {}), (403, [])])
def test_key_refusal_messages(status, body):
    assert str(app.core.APIError(status, body)) == (
        f'Desearch refused the API key (HTTP {status}). Check the key at console.desearch.ai.')
