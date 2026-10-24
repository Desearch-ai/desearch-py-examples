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
    assert output.err == 'Desearch returned HTTP 403\n'
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
    assert body == 'Rate limit: 2 runs per 10 minutes and 5 per day per IP. Try again in 10 minutes.'
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
