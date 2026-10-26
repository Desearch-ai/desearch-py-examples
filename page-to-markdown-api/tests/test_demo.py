import io
import json
import socket
import urllib.error
from unittest.mock import Mock

import pytest
from pagemd.client import Client, NoRedirect
from pagemd.guards import DailyCap, RateLimiter, TTLCache
from pagemd.service import Converter, MAX_MARKDOWN, parse_query, client_ip
from pagemd.urlguard import validate_url, URLValidationError


def dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))]


HTML = '<html><head><title>Reading &amp; gardens</title></head><body><h1>Reading</h1><p>' + 'a lovely garden with books ' * 12 + '</p></body></html>'


class FakeClient:
    def __init__(self, status=200, body=HTML, rec=None):
        self.status, self.body = status, body
        self.rec = rec or {'cost': 0, 'cost_known': False}
        self.calls = 0

    def extract(self, url):
        self.calls += 1
        return self.status, self.body, self.rec


def make(client=None, **kwargs):
    kwargs.setdefault('limiter', RateLimiter())
    return Converter(client=client or FakeClient(), resolver=dns, live=kwargs.pop('live', True), **kwargs)


def response(converter, url='https://example.com/article', ip='ip'):
    status, headers, text = converter.handle({'url': url}, ip)
    assert headers['Cache-Control'] == 'no-store'
    return status, json.loads(text)


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'ftp://example.com', 'javascript:alert(1)', '', ' ',
    'https://example.com/' + 'a' * 2048, 'https://user:pass@example.com',
    'http://localhost', 'http://sub.localhost', 'http://a.local', 'http://a.internal',
    'http://127.0.0.1', 'http://0.0.0.0', 'http://10.1.2.3', 'http://192.168.1.1',
    'http://172.16.1.1', 'http://100.64.1.1', 'http://169.254.169.254',
    'http://metadata.google.internal', 'http://[::1]', 'http://[fd00:ec2::254]',
    'http://[::ffff:127.0.0.1]', 'http://::ffff:127.0.0.1', 'http://2130706433',
    'http://0x7f000001', 'http://0177.0.0.1', 'http://8.8.8.8', 'http://127.1',
    'https://example.com/a.pdf', 'https://example.com/a.ZIP?download=1',
    'https://example.com/a.%70ng', 'https://example.com/a.mp3',
    'https://example.com\\@localhost', 'https://example.com:bad',
])
def test_ssrf_rejected_before_api(url):
    client = FakeClient()
    assert response(make(client), url)[0] == 400
    assert client.calls == 0


@pytest.mark.parametrize('address', ['10.0.0.5', '127.0.0.1', '0.0.0.0', '192.168.0.1',
    '172.16.0.1', '100.64.0.1', '169.254.169.254', '224.0.0.1', '240.0.0.1',
    '192.0.2.1', '::1', 'fd00:ec2::254', 'fe80::1', 'ff02::1', '::ffff:127.0.0.1'])
def test_any_nonpublic_dns_answer_rejected(address):
    def mixed(host, port, **kwargs):
        return dns(host, port) + [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', (address, port))]
    client = FakeClient()
    c = make(client); c.resolver = mixed
    assert response(c)[0] == 400 and client.calls == 0


def test_normalization_and_public_url():
    assert validate_url('HTTPS://Example.COM:443/a///#fragment', dns) == 'https://example.com/a'
    assert validate_url('http://Example.com:80/', dns) == 'http://example.com'
    assert validate_url('https://example.com:443/a?q=1#x', dns) == 'https://example.com/a?q=1'


def test_dns_failure_and_no_answers():
    for resolver in (lambda *a, **k: [], Mock(side_effect=socket.gaierror())):
        with pytest.raises(URLValidationError):
            validate_url('https://example.com', resolver)


def test_paused_even_with_cache(monkeypatch):
    c = make(); assert response(c)[0] == 200
    c.live = False
    status, body = response(c)
    assert status == 503 and body['status'] == 'paused' and body['markdown'] == c.sample['markdown']
    assert c._client.calls == 1
    for _ in range(3):
        assert response(c)[0] == 503
    assert response(c)[0] == 429
    monkeypatch.setenv('DEMO_LIVE', '0')
    assert not Converter(resolver=dns).live


@pytest.mark.parametrize('status', [401, 402, 403, 404, 500, 503, 599])
def test_failures_sample_cost_and_no_retry(status):
    c = make(FakeClient(status, rec={'cost': .8, 'cost_known': True}))
    code, body = response(c)
    assert code == (503 if status in (401, 402, 403) else 404 if status == 404 else 504 if status == 599 else 502)
    assert body['markdown'] == c.sample['markdown'] and body['sample'] == '/sample.json'
    assert c._client.calls == 1
    assert c.cap.spent == (0 if status in (401, 402, 403, 404) else .8)
    if status == 404:
        assert body['error'] == 'Page not found. Check the link and try again.'


@pytest.mark.parametrize('placement', ['rec', 'body', 'nested'])
def test_final_private_url_rejected(placement):
    client = FakeClient()
    if placement == 'rec':
        client.rec['final_url'] = 'http://10.0.0.5'
    elif placement == 'body':
        client.body = {'html': HTML, 'final_url': 'http://10.0.0.5'}
    else:
        client.body = {'data': {'html': HTML, 'redirect_url': 'http://10.0.0.5'}}
    c = make(client)
    assert response(c)[0] == 400 and client.calls == 1
    assert not c.cache.d


def test_title_empty_and_output_cap():
    assert response(make())[1]['title'] == 'Reading & gardens'
    c = make(FakeClient(body='<div id="root"></div>'))
    body = response(c)[1]
    assert body['status'] == 'empty'
    assert body['message'] == 'This page looks empty (JavaScript-heavy). Try another link.'
    assert c._client.calls == 1 and c.cap.spent == .0005
    body = response(make(FakeClient(body='<p>' + 'café ' * 60000 + '</p>')))[1]
    assert body['truncated'] and len(body['markdown'].encode()) <= MAX_MARKDOWN
    assert body['markdown'].endswith('[Output truncated at 200 KB.]')


def test_cache_and_expiry():
    clock = [0]
    c = make(cache=TTLCache(clock=lambda: clock[0]),
             limiter=RateLimiter(clock=lambda: clock[0]))
    assert not response(c, 'HTTPS://EXAMPLE.COM:443/a/#x')[1]['cached']
    clock[0] = 21599
    hit = response(c, 'https://example.com/a')[1]
    assert hit['cached'] and hit['cost_usd_this_request'] == 0 and c._client.calls == 1
    clock[0] = 21600
    assert not response(c, 'https://example.com/a')[1]['cached'] and c._client.calls == 2


def test_limits_and_day_reset():
    clock = [0]
    c = make(FakeClient(500), limiter=RateLimiter(global_window=100, clock=lambda: clock[0]))
    for _ in range(3):
        for i in range(5):
            assert response(c)[0] == 502
        assert response(c)[0] == 429
        clock[0] += 601
    assert response(c)[0] == 429 and c._client.calls == 15
    clock[0] = 86401
    assert response(c)[0] == 502


def test_global_limit():
    c = make(FakeClient(500), limiter=RateLimiter(global_window=2))
    assert response(c, ip='192.0.2.1')[0] == 502
    assert response(c, ip='192.0.2.2')[0] == 502
    assert response(c, ip='192.0.2.3')[0] == 429 and c._client.calls == 2


@pytest.mark.parametrize('headers,body,cost', [
    ({'X-Desearch-Cost-USD': '.002'}, {'html': HTML, 'cost_usd': .003}, .002),
    ({}, {'html': HTML, 'cost_usd': .003}, .003),
    ({}, {'html': HTML}, .0005),
    ({'X-Desearch-Cost-USD': 'NaN'}, {'html': HTML, 'cost_usd': .003}, .003),
])
def test_header_body_fallback_and_daily_cap(headers, body, cost):
    reply = Mock(status=200, headers=headers)
    reply.read.return_value = json.dumps(body).encode()
    reply.__enter__ = Mock(return_value=reply); reply.__exit__ = Mock(return_value=False)
    opener = Mock(return_value=reply)
    c = make(Client('test-placeholder', opener=opener), cap=DailyCap(cost))
    assert response(c)[1]['cost_usd'] == cost
    assert c.cap.spent == cost
    assert response(c)[1]['cached']
    assert response(c, 'https://example.com/another')[0] == 503
    opener.assert_called_once()
    req = opener.call_args.args[0]
    assert req.get_method() == 'GET' and req.full_url.startswith('https://api.desearch.ai/web/extract?url=')
    assert req.get_header('Authorization') == 'test-placeholder'


def test_cap_utc_rollover():
    clock = [0]; cap = DailyCap(.001, clock=lambda: clock[0])
    cap.add(.001); assert not cap.ok()
    clock[0] = 86400; assert cap.ok() and cap.spent == 0


def test_env_and_missing_configuration(monkeypatch):
    monkeypatch.setenv('DEMO_DAILY_CAP_USD', '0')
    assert response(make())[0] == 503
    monkeypatch.setenv('DEMO_DAILY_CAP_USD', '1')
    monkeypatch.setenv('DEMO_FALLBACK_COST_USD', '.001')
    c = make(); assert response(c)[1]['cost_usd'] == .001
    assert response(Converter(resolver=dns, live=True))[0] == 503


@pytest.mark.parametrize('failure', [TimeoutError(), urllib.error.HTTPError('https://api.desearch.ai', 503, '', {}, io.BytesIO(b'{}'))])
def test_http_failure_once(failure):
    opener = Mock(side_effect=failure)
    c = make(Client('test-placeholder', opener=opener))
    assert response(c)[0] == (504 if isinstance(failure, TimeoutError) else 502)
    opener.assert_called_once()


def test_redirect_handler_never_follows():
    assert NoRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost') is None


def test_query_helpers():
    assert parse_query('/api/convert?url=') == {'url': ''}
    assert client_ip({'X-Forwarded-For': 'one, two'}) == 'one'


def test_public_final_url_dns_checked():
    resolver = Mock(side_effect=dns)
    c = make(FakeClient(body={'data': {'html': HTML, 'final_url': 'https://other.example/page'}}))
    c.resolver = resolver
    assert response(c)[0] == 200
    assert [call.args[0] for call in resolver.call_args_list] == ['example.com', 'other.example']


def test_timeout_returning_sample():
    client = Mock()
    client.extract.side_effect = TimeoutError()
    c = make(client)
    status, body = response(c)
    assert status == 504 and body['markdown'] == c.sample['markdown']
    client.extract.assert_called_once()


def test_http_redirect_location_revalidated():
    error = urllib.error.HTTPError('https://api.desearch.ai', 302, '', {'Location': 'http://127.0.0.1'}, io.BytesIO(b''))
    opener = Mock(side_effect=error)
    c = make(Client('test-placeholder', opener=opener))
    assert response(c)[0] == 400
    opener.assert_called_once()


def test_local_and_vercel_handlers_without_sockets(monkeypatch):
    import importlib.util
    from pathlib import Path
    import app
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('demo_convert', root / 'api/convert.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    c = make(live=False)
    monkeypatch.setattr(module, 'CONVERTER', c)
    for handler in (module.handler, app.make_handler(c)):
        h = handler.__new__(handler)
        h.path = '/api/convert?url=https%3A%2F%2Fexample.com'
        h.headers = {}; h.client_address = ('test-ip', 123)
        h.wfile = io.BytesIO(); h.send_response = Mock(); h.send_header = Mock(); h.end_headers = Mock()
        h.do_GET()
        assert h.send_response.call_args.args[0] == 503
        assert json.loads(h.wfile.getvalue())['markdown'] == c.sample['markdown']
    h.path = '/'; h.wfile = io.BytesIO(); h.do_GET()
    assert b'Page to Markdown' in h.wfile.getvalue()


def test_sample_and_ui_contract():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sample = json.loads((root / 'public/sample.json').read_text())
    assert len(sample['markdown'].split()) >= 20
    text = (root / 'public/index.html').read_text()
    assert '<pre' in text and '.textContent = markdown' in text
    assert 'target="_blank" rel="noopener noreferrer"' in text
    assert 'innerHTML' not in text
    assert '\u2014' not in text and 'real-time' not in text
