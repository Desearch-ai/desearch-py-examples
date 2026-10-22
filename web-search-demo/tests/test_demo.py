import io
import json
import urllib.error
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import pytest
from websearch.client import Client, NoRedirect, PER_PAGE
from websearch.guards import DailyCap, RateLimiter, TTLCache
from websearch.service import Search, client_ip, parse_query
from websearch import state

KEY = 'test-secret-credential'
ROWS = [{'title': 'Bittensor', 'link': 'https://bittensor.com/', 'snippet': 'A network of subnets.'}]


class Response:
    status = 200
    def __init__(self, headers=None, body=None):
        self.headers = headers or {}
        self.body = json.dumps({'data': ROWS} if body is None else body).encode()
    def read(self):
        return self.body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def demo(**kwargs):
    return Search(client=kwargs.pop('client', Mock(search=Mock(return_value=(200, ROWS, .002)))),
                  limiter=kwargs.pop('limiter', RateLimiter()), cap=kwargs.pop('cap', DailyCap()),
                  cache=kwargs.pop('cache', TTLCache()), **kwargs)


def call(service, q='bittensor subnet', page='1'):
    status, headers, body = service.handle({'q': q, 'page': page}, '203.0.113.1')
    return status, headers, json.loads(body)


@pytest.mark.parametrize('q', ['', ' ', 'x', 'a'*201, ' a ', None, 12])
def test_invalid_queries_before_state(q):
    limiter, cap, cache, client = Mock(), Mock(), Mock(), Mock()
    service = demo(limiter=limiter, cap=cap, cache=cache, client=client)
    assert call(service, q)[0] == 400
    for obj in (limiter, cap, cache, client):
        assert not obj.mock_calls


@pytest.mark.parametrize('page', ['0', '3', '', '1.0', '-1', None, 2])
def test_invalid_page_before_limiter(page):
    limiter = Mock()
    assert call(demo(limiter=limiter), page=page)[0] == 400
    limiter.allow.assert_not_called()


@pytest.mark.parametrize('q', ['ab', 'a'*200, '  ab  '])
@pytest.mark.parametrize('page', ['1', '2'])
def test_valid_bounds(q, page):
    service = demo()
    assert call(service, q, page)[0] == 200
    service._client.search.assert_called_once_with(q.strip(), int(page))


def test_cache_normalization_page_and_free_hits():
    limiter = Mock(allow=Mock(return_value=True))
    service = demo(limiter=limiter)
    assert call(service, '  Bittensor   Subnet  ')[2]['cached'] is False
    status, headers, body = call(service, 'bittensor subnet')
    assert status == 200 and body['cached'] is True
    assert body['cost_usd_this_request'] == 0 and headers['X-Desearch-Cost-Usd'] == '0'
    assert limiter.allow.call_count == service._client.search.call_count == 1
    assert call(service, page='2')[2]['cached'] is False
    assert limiter.allow.call_count == service._client.search.call_count == 2


def test_cache_expiry():
    clock = Mock(return_value=0)
    cache = TTLCache(clock=clock)
    cache.put('q', {'results': []})
    clock.return_value = 599
    assert cache.get('q') is not None
    clock.return_value = 600
    assert cache.get('q') is None


@pytest.mark.parametrize('value,expected', [('0.004', .004), ('0', 0), ('NaN', None),
    ('inf', None), ('-1', None), ('bad', None), (None, None)])
def test_header_cost_and_one_request(value, expected):
    opener = Mock(return_value=Response({'X-DeSearch-Cost-Usd': value}, {'data': ROWS, 'cost_usd': 99}))
    client = Client(KEY, opener)
    assert client.search('bittensor & subnet', 2) == (200, ROWS, expected)
    request = opener.call_args.args[0]
    assert request.get_method() == 'GET'
    assert request.get_header('Authorization') == KEY
    assert request.full_url.startswith('https://api.desearch.ai/web?')
    assert parse_qs(urlsplit(request.full_url).query) == {'query':['bittensor & subnet'], 'start':[str(PER_PAGE)]}
    opener.assert_called_once()


@pytest.mark.parametrize('fallback', [None, '0.009'])
def test_fallback_accounting(monkeypatch, fallback):
    if fallback:
        monkeypatch.setenv('DEMO_FALLBACK_COST_USD', fallback)
    service = demo(client=Client(KEY, Mock(return_value=Response())))
    status, headers, body = call(service)
    cost = float(fallback or '.001')
    assert status == 200
    assert float(headers['X-Desearch-Cost-Usd']) == body['cost_usd_this_request'] == service.cap.spent == cost


def test_limit_429():
    service = demo(limiter=RateLimiter(per_ip=1))
    assert call(service, 'first query')[0] == 200
    status, headers, body = call(service, 'second query')
    assert status == 429 and body['status'] == 'limited'
    assert headers['X-Desearch-Cost-Usd'] == '0'
    assert service._client.search.call_count == 1


def test_daily_cap_paused_with_sample():
    service = demo(cap=DailyCap(.002))
    assert call(service)[0] == 200
    status, _, body = call(service, 'other query')
    assert status == 503 and body['sample'] is True and body['status'] == 'paused'
    assert body['results'] and 'EXAMPLE' in body['label']
    assert service._client.search.call_count == 1
    assert call(service)[0] == 200  # cache stays free after cap


@pytest.mark.parametrize('status', [301, 400, 401, 402, 403, 429, 500, 599])
def test_upstream_failures_pause(status):
    service = demo(client=Mock(search=Mock(return_value=(status, None, None))))
    code, _, body = call(service)
    assert code == 503 and body['sample'] and body['status'] == 'paused'
    assert service.cap.spent == .001


@pytest.mark.parametrize('target', ['cache.get', 'cap.ok', 'limiter.allow', 'cap.add', 'cache.put'])
def test_redis_errors_fail_closed(target):
    service = demo()
    name, method = target.split('.')
    obj = Mock(wraps=getattr(service, name))
    setattr(service, name, obj)
    getattr(obj, method).side_effect = state.StateUnavailable()
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused' and body['sample']
    if target in ('cache.get', 'cap.ok', 'limiter.allow'):
        service._client.search.assert_not_called()


@pytest.mark.parametrize('variable', ['VERCEL', 'VERCEL_ENV'])
def test_memory_refused_on_vercel(monkeypatch, variable):
    monkeypatch.setenv(variable, '1')
    monkeypatch.setenv('DEMO_STATE', 'memory')
    service = Search(client=Mock())
    assert call(service)[0] == 503
    service._client.search.assert_not_called()


def test_missing_redis_fails_closed():
    service = Search(client=Mock())
    assert call(service)[0] == 503
    service._client.search.assert_not_called()
    assert call(service, 'x')[0] == 400


@pytest.mark.parametrize('headers,fallback,expected', [
    ({'X-Vercel-Forwarded-For':' 1.2.3.4, 5.6.7.8', 'X-Forwarded-For':'9.9.9.9'}, '', '1.2.3.4'),
    ({'X-Forwarded-For':' 1.2.3.4, 5.6.7.8'}, '', '1.2.3.4'),
    ({'X-Real-IP':' 1.2.3.4 '}, '', '1.2.3.4'),
    ({'X-Vercel-Forwarded-For':' ', 'X-Forwarded-For':'1.2.3.4'}, '', '1.2.3.4'),
    ({}, ' ::1 ', '::1')])
def test_client_ip(headers, fallback, expected):
    assert client_ip(headers, fallback) == expected


def test_parse_query():
    assert parse_query('/api/search?q=bittensor+subnet&page=2') == {'q':'bittensor subnet', 'page':'2'}


def test_key_never_in_response(monkeypatch):
    monkeypatch.setenv('DESEARCH_API_KEY', KEY)
    opener = Mock(return_value=Response(body={'data':ROWS, 'authorization':KEY}))
    service = demo(client=Client(KEY, opener))
    assert KEY not in str(service.handle({'q':'test'}, '1.2.3.4'))
    opener.return_value = Response(body={'error':KEY})
    result = service.handle({'q':'another'}, '1.2.3.4')
    assert result[0] == 503 and KEY not in str(result)


def test_http_error_and_no_redirect():
    opener = Mock(side_effect=urllib.error.HTTPError('https://api.desearch.ai/web', 401, 'bad', {}, io.BytesIO(b'{"error":"secret"}')))
    assert Client(KEY, opener).search('query', 1)[0] != 200
    assert NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test') is None
    opener.assert_called_once()


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
    cache.put('query/page', {'results':ROWS})
    command = redis.pipeline.call_args.args[0][0]
    assert command[0] == 'SET' and command[-2:] == ['EX',600]
    assert command[1].startswith('websearch:cache:') and 'query/page' not in command[1]
    redis.pipeline.return_value = [json.dumps({'results':ROWS})]
    assert cache.get('query/page') == {'results':ROWS}
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


def test_pages_do_not_overlap():
    starts = []
    def opener(request, **kwargs):
        start = int(parse_qs(urlsplit(request.full_url).query)['start'][0])
        starts.append(start)
        return Response(body={'data': [dict(title=str(i), link=str(i), snippet='')
                                      for i in range(start, start + PER_PAGE)]})
    service = demo(client=Client(KEY, opener))
    first = call(service, page='1')[2]['results']
    second = call(service, page='2')[2]['results']
    assert starts == [0, len(first)] == [0, PER_PAGE]
    assert len(second) == PER_PAGE
    assert {row['link'] for row in first}.isdisjoint(row['link'] for row in second)


@pytest.mark.parametrize('entrypoint', ['vercel', 'local'])
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_handlers_do_not_log_queries(monkeypatch, capsys, entrypoint, method):
    from api import search as api_search
    from app import make_handler
    service = demo()
    monkeypatch.setattr(api_search, 'SEARCH', service)
    handler = api_search.handler if entrypoint == 'vercel' else make_handler(service)
    query = 'private-query-sentinel'
    request = Mock()
    request.makefile.return_value = io.BytesIO(
        f'{method} /api/search?q={query}&page=1 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
    handler(request, ('127.0.0.1', 12345), Mock())
    assert request.sendall.called
    assert capsys.readouterr().err == ''


def test_public_copy_uses_network_limits():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name in ('public/index.html', 'README.md', 'DEPLOY.md'):
        text = (root / name).read_text()
        assert 'per visitor' not in text
        assert '—' not in text
    assert (root / 'public/index.html').read_text().count('per network') == 2
