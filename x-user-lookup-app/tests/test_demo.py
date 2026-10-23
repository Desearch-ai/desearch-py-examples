import io
import json
from pathlib import Path
import urllib.error
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import pytest
from xlookup.client import Client, NoRedirect, amount
from xlookup.guards import DailyCap, RateLimiter, TTLCache
from xlookup.service import Lookup, client_ip, parse_query
from xlookup import state

KEY = 'test-secret-credential'
ROWS = {'profile': {'username': 'example'}, 'posts': []}


def test_hosted_page_guards_bio_before_rendering():
    html = (Path(__file__).resolve().parents[1] / 'public' / 'index.html').read_text()
    assert "if(typeof p.bio === 'string' && p.bio.trim()) line($('profile'),p.bio);" in html


class Response:
    status = 200
    def __init__(self, headers=None, body=None):
        self.headers = headers or {}
        self.body = json.dumps({'tweets': []} if body is None else body).encode()
    def read(self):
        return self.body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def demo(**kwargs):
    return Lookup(client=kwargs.pop('client', Mock(lookup=Mock(return_value=(200, ROWS, .002)))),
                  limiter=kwargs.pop('limiter', RateLimiter()), cap=kwargs.pop('cap', DailyCap()),
                  cache=kwargs.pop('cache', TTLCache()), **kwargs)


def call(service, q='example'):
    status, headers, body = service.handle({'username': q}, '203.0.113.1')
    return status, headers, json.loads(body)


@pytest.mark.parametrize('q', ['', ' ', '@', 'a'*16, 'has space', None, 12])
def test_invalid_queries_before_state(q):
    limiter, cap, cache, client = Mock(), Mock(), Mock(), Mock()
    service = demo(limiter=limiter, cap=cap, cache=cache, client=client)
    assert call(service, q)[0] == 400
    for obj in (limiter, cap, cache, client):
        assert not obj.mock_calls








def test_cache_expiry():
    clock = Mock(return_value=0)
    cache = TTLCache(clock=clock)
    cache.put('q', {'results': []})
    clock.return_value = 899
    assert cache.get('q') is not None
    clock.return_value = 900
    assert cache.get('q') is None




@pytest.mark.parametrize('fallback', [None, '0.009'])
def test_fallback_accounting(monkeypatch, fallback):
    if fallback:
        monkeypatch.setenv('DEMO_FALLBACK_COST_USD', fallback)
    service = demo(client=Client(KEY, Mock(return_value=Response())))
    status, headers, body = call(service)
    cost = float(fallback or '.003')
    assert status == 200
    assert float(headers['X-Desearch-Cost-Usd']) == body['cost_usd_this_request'] == service.cap.spent == cost


def test_limit_429():
    service = demo(limiter=RateLimiter(per_ip=1))
    assert call(service, 'first')[0] == 200
    status, headers, body = call(service, 'second')
    assert status == 429 and body['status'] == 'limited'
    assert headers['X-Desearch-Cost-Usd'] == '0'
    assert service._client.lookup.call_count == 1




@pytest.mark.parametrize('status', [301, 400, 401, 402, 403, 429, 500, 599])
def test_upstream_failures_pause(status):
    service = demo(client=Mock(lookup=Mock(return_value=(status, None, None))))
    code, _, body = call(service)
    assert code == 503 and body['sample'] and body['status'] == 'paused'
    assert service.cap.spent == .003


@pytest.mark.parametrize('error_type', [state.StateUnavailable, RuntimeError])
@pytest.mark.parametrize('target', ['cache.get', 'cap.ok', 'limiter.allow', 'cap.add', 'cache.put'])
def test_redis_errors_fail_closed(target, error_type):
    service = demo()
    name, method = target.split('.')
    obj = Mock(wraps=getattr(service, name))
    setattr(service, name, obj)
    getattr(obj, method).side_effect = error_type('private details')
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused' and body['sample']
    if target in ('cache.get', 'cap.ok', 'limiter.allow', 'cap.add'):
        service._client.lookup.assert_not_called()


@pytest.mark.parametrize('variable', ['VERCEL', 'VERCEL_ENV'])
def test_memory_refused_on_vercel(monkeypatch, variable):
    monkeypatch.setenv(variable, '1')
    monkeypatch.setenv('DEMO_STATE', 'memory')
    service = Lookup(client=Mock())
    assert call(service)[0] == 503
    service._client.lookup.assert_not_called()


def test_missing_redis_fails_closed():
    service = Lookup(client=Mock())
    assert call(service)[0] == 503
    service._client.lookup.assert_not_called()
    assert call(service, '@')[0] == 400


@pytest.mark.parametrize('headers,fallback,expected', [
    ({'X-Vercel-Forwarded-For':' 1.2.3.4, 5.6.7.8', 'X-Forwarded-For':'9.9.9.9'}, '', '1.2.3.4'),
    ({'X-Forwarded-For':' 1.2.3.4, 5.6.7.8'}, '', '1.2.3.4'),
    ({'X-Real-IP':' 1.2.3.4 '}, '', '1.2.3.4'),
    ({'X-Vercel-Forwarded-For':' ', 'X-Forwarded-For':'1.2.3.4'}, '', '1.2.3.4'),
    ({}, ' ::1 ', '::1')])
def test_client_ip(headers, fallback, expected):
    assert client_ip(headers, fallback) == expected








@pytest.mark.parametrize('payload', [b'bad json', b'{}', b'[{"error":"bad"}]'])
def test_redis_malformed(monkeypatch, payload):
    response = Response()
    response.body = payload
    monkeypatch.setattr('urllib.request.urlopen', Mock(return_value=response))
    with pytest.raises(state.StateUnavailable):
        state.RedisREST('https://redis.test', 'token').pipeline([['GET','key']])


def test_redis_cache_and_limiter_commands():
    redis = Mock()
    cache = state.Cache(redis)
    cache.put('example', {'results':ROWS})
    command = redis.pipeline.call_args.args[0][0]
    assert command[0] == 'SET' and command[-2:] == ['EX',900]
    assert command[1].startswith('xlookup:cache:') and 'example' not in command[1]
    redis.pipeline.return_value = [json.dumps({'results':ROWS})]
    assert cache.get('example') == {'results':ROWS}
    redis.pipeline.return_value = [1,1,1,1,1,1]
    limiter = state.Limiter(redis)
    assert limiter.allow('203.0.113.1')
    redis.pipeline.return_value = [6,1,1,1,1,1]
    assert not limiter.allow('203.0.113.1')
    assert state.ip_bucket('2001:db8::1') == state.ip_bucket('2001:db8::2')


def test_redis_aliases_and_failure(monkeypatch):
    monkeypatch.setenv('KV_REST_API_URL', 'https://redis.test/')
    monkeypatch.setenv('KV_REST_API_TOKEN', 'token')
    redis = state.RedisREST()
    assert redis._url == 'https://redis.test' and redis._token == 'token'
    monkeypatch.setattr('urllib.request.urlopen', Mock(side_effect=OSError('private connection details')))
    with pytest.raises(state.StateUnavailable) as error:
        redis.pipeline([['GET','key']])
    assert 'private' not in str(error.value)







import hashlib
import http.client
class FakeRedis:
    """Exercise RedisREST's decoding with Upstash-shaped pipeline responses."""
    def __init__(self, monkeypatch):
        self.values = {}
        self.commands = []
        monkeypatch.setattr('urllib.request.urlopen', self.urlopen)
        self.redis = state.RedisREST('https://redis.test', 'token')

    def urlopen(self, request, **kwargs):
        commands = json.loads(request.data)
        self.commands.extend(commands)
        entries = []
        for command in commands:
            op, key, *args = command
            if op == 'GET':
                result = self.values.get(key)
            elif op in ('INCR', 'INCRBYFLOAT'):
                amount = 1 if op == 'INCR' else float(args[0])
                self.values[key] = float(self.values.get(key, 0)) + amount
                result = self.values[key] if op == 'INCR' else str(self.values[key])
            elif op == 'EXPIRE':
                result = 1
            else:
                raise AssertionError(command)
            entries.append({'result': result})
        return Response(body=entries)


def test_shared_daily_cap_utc_commands(monkeypatch):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)  # 2026-01-01 UTC
    key = 'xlookup:spend:2026-01-01'
    assert cap.ok()
    cap.add(.003)
    assert fake.commands == [['GET', key], ['INCRBYFLOAT', key, .003], ['EXPIRE', key, 172800]]
    assert fake.values[key] == .003


@pytest.mark.parametrize('spent', [1, 1.01])
def test_shared_cap_at_or_over_budget_pauses(monkeypatch, spent):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    cap.add(spent)
    service = demo(cap=cap)
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused'
    service._client.lookup.assert_not_called()


@pytest.mark.parametrize('real_cost', [None, .003, 0, .0005, .006])
def test_reservation_before_upstream_and_adjustment(monkeypatch, real_cost):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    key = cap._key()
    service = demo(cap=cap)
    def search(*args):
        assert fake.values[key] == service.fallback_cost
        return 200, ROWS, real_cost
    service._client.lookup.side_effect = search
    assert call(service)[0] == 200
    assert fake.values[key] == pytest.approx(service.fallback_cost if real_cost is None else real_cost)
    additions = [c for c in fake.commands if c[0] == 'INCRBYFLOAT']
    assert len(additions) == (1 if real_cost in (None, .003) else 2)


@pytest.mark.parametrize('target', ['adjustment', 'cache.put'])
@pytest.mark.parametrize('error_type', [state.StateUnavailable, RuntimeError])
def test_paid_spend_survives_state_failure(monkeypatch, target, error_type):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    service = demo(cap=cap)
    if target == 'adjustment':
        original_add = cap.add
        def add(amount):
            if service._client.lookup.called:
                raise error_type('private connection details')
            original_add(amount)
        monkeypatch.setattr(cap, 'add', add)
    else:
        service.cache.put = Mock(side_effect=error_type('private connection details'))
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused'
    assert 'private' not in json.dumps(body)
    service._client.lookup.assert_called_once()
    assert fake.values[cap._key()] == pytest.approx(service.fallback_cost if target == 'adjustment' else .002)


@pytest.mark.parametrize('failure', ['missing', 'oserror', 'incomplete', 'unexpected'])
def test_redis_transport_failures_pause(monkeypatch, failure):
    redis = state.RedisREST('' if failure == 'missing' else 'https://redis.test', 'token')
    error = {'oserror': OSError('private connection details'),
             'incomplete': http.client.IncompleteRead(b'private connection details', 100),
             'unexpected': RuntimeError('private connection details')}.get(failure)
    opener = Mock(side_effect=error)
    monkeypatch.setattr('urllib.request.urlopen', opener)
    with pytest.raises(state.StateUnavailable) as caught:
        redis.pipeline([['GET', 'key']])
    assert str(caught.value) == '' and caught.value.__suppress_context__
    service = demo(cache=state.Cache(redis))
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused'
    assert 'private' not in json.dumps(body)
    service._client.lookup.assert_not_called()
    if failure == 'missing':
        opener.assert_not_called()


def test_shared_limiter_sixth_request_denied(monkeypatch):
    fake = FakeRedis(monkeypatch)
    limiter = state.Limiter(fake.redis, clock=lambda: 1767225600)
    ip = '203.0.113.1'
    assert [limiter.allow(ip) for _ in range(6)] == [True] * 5 + [False]
    hashed = hashlib.sha256(ip.encode()).hexdigest()
    key = f'xlookup:limit:ip:{hashed}:10min:{1767225600 // 600}'
    for offset in range(0, len(fake.commands), 6):
        assert fake.commands[offset:offset + 2] == [['INCR', key], ['EXPIRE', key, 1200]]


@pytest.mark.parametrize('real_cost', [0, .0005])
def test_memory_cap_accepts_negative_adjustments(real_cost):
    service = demo(client=Mock(lookup=Mock(return_value=(200, ROWS, real_cost))))
    assert call(service)[0] == 200
    assert service.cap.spent == pytest.approx(real_cost)


@pytest.mark.parametrize('name', ['example', '@EXAMPLE', 'https://x.com/Example'])
def test_normalized_free_cache(name):
    service = demo()
    assert call(service)[0] == 200
    code, headers, body = call(service, name)
    assert code == 200 and body['cached'] is True
    assert body['cost_usd_this_request'] == 0
    assert headers['X-Desearch-Cost-Usd'] == '0'
    service._client.lookup.assert_called_once_with('example')


@pytest.mark.parametrize('header,body_cost,expected', [('.004', .5, .004), ('0', .5, 0),
    (None, .005, .005), ('NaN', .006, .006), (None, None, None), ('-1', 'inf', None)])
def test_fixed_endpoint_cost_and_shaping(header, body_cost, expected):
    body = {'user': {'name': 'Example', 'username': 'example'}, 'tweets': [
        {'id': '123', 'text': '<script>example</script>', 'like_count': 4}],
        'next_cursor': 'never-follow', 'cost_usd': body_cost, 'private_metadata': KEY}
    opener = Mock(return_value=Response({'X-DeSearch-Cost-Usd': header}, body))
    code, result, cost = Client(KEY, opener).lookup('example')
    assert code == 200 and cost == expected
    assert result['profile']['name'] == 'Example'
    assert result['posts'][0]['likes'] == 4
    assert KEY not in json.dumps(result)
    request = opener.call_args.args[0]
    assert request.get_method() == 'GET'
    assert request.get_header('Authorization') == KEY
    assert urlsplit(request.full_url).scheme == 'https'
    assert urlsplit(request.full_url).netloc == 'api.desearch.ai'
    assert urlsplit(request.full_url).path == '/twitter/user/posts'
    assert parse_qs(urlsplit(request.full_url).query) == {'username': ['example']}
    opener.assert_called_once()


@pytest.mark.parametrize('header,expected', [(None, 0), ('.001', .001)])
def test_404_cost_and_no_cache(header, expected):
    opener = Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.HTTPError('https://api.desearch.ai/twitter/user/posts', 404, 'not found',
            {'X-Desearch-Cost-Usd': header}, io.BytesIO(b'{"cost_usd":99,"error":"private"}'))))
    service = demo(client=Client(KEY, opener))
    code, _, body = call(service)
    assert code == 404 and body['error'] == 'not found'
    assert body['cost_usd_this_request'] == expected
    assert service.cap.spent == pytest.approx(expected)
    assert service.cache.get('example') is None
    assert 'private' not in json.dumps(body)


def test_cap_and_paused_sample():
    service = demo(cap=DailyCap(.002))
    assert call(service)[0] == 200
    assert call(service, 'other')[0] == 503
    assert call(service)[2]['cached'] is True
    paused = demo(live=False)
    code, _, body = call(paused)
    assert code == 503 and body['sample'] and body['profile'] and body['posts']
    paused._client.lookup.assert_not_called()


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_handler_suppresses_request_logs(monkeypatch, capsys, method):
    from api import lookup as api_lookup
    monkeypatch.setattr(api_lookup, 'LOOKUP', demo())
    request = Mock()
    request.makefile.return_value = io.BytesIO(
        f'{method} /api/lookup?username=example HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
    api_lookup.handler(request, ('127.0.0.1', 12345), Mock())
    assert request.sendall.called
    assert capsys.readouterr().err == ''


def test_no_redirect_and_public_copy():
    from pathlib import Path
    assert NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.test') is None
    root = Path(__file__).resolve().parents[1]
    for name in ('README.md', 'DEPLOY.md', 'public/index.html', 'public/sample.json'):
        text = (root / name).read_text()
        assert '\u2014' not in text and '\u2013' not in text
    html = (root / 'public/index.html').read_text()
    assert 'innerHTML' not in html and 'textContent' in html
    assert 'DESEARCH_API_KEY' not in html
    assert parse_query('/api/lookup?username=%40example') == {'username': '@example'}
