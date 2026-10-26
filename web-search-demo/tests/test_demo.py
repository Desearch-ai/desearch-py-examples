import io
import threading
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
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
    assert float(headers['X-Desearch-Cost-Usd']) == body['cost_usd_this_request'] == cost
    assert service.cap.spent == max(.005, cost)


def test_limit_429():
    service = demo(limiter=RateLimiter(per_ip=1))
    assert call(service, 'first query')[0] == 200
    status, headers, body = call(service, 'second query')
    assert status == 429 and body['status'] == 'limited'
    assert headers['X-Desearch-Cost-Usd'] == '0'
    assert service._client.search.call_count == 1


def test_daily_cap_paused_with_sample(monkeypatch):
    monkeypatch.setenv('DEMO_RESERVE_COST_USD', '0.002')
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
    assert service.cap.spent == (0 if status == 599 else .005)


@pytest.mark.parametrize('error_type', [state.StateUnavailable, RuntimeError])
@pytest.mark.parametrize('target', ['cache.get', 'cap.ok', 'limiter.allow', 'cap.reserve', 'cache.put'])
def test_redis_errors_fail_closed(target, error_type):
    service = demo()
    name, method = target.split('.')
    obj = Mock(wraps=getattr(service, name))
    setattr(service, name, obj)
    getattr(obj, method).side_effect = error_type('private state details')
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused' and body['sample']
    if target in ('cache.get', 'cap.ok', 'limiter.allow', 'cap.reserve'):
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


class FakeRedis:
    """Exercise RedisREST's decoding with Upstash-shaped pipeline responses."""
    def __init__(self, monkeypatch):
        self.values = {}
        self.commands = []
        self.lock = threading.Lock()
        self.batches = []
        monkeypatch.setattr('urllib.request.urlopen', self.urlopen)
        self.redis = state.RedisREST('https://redis.test', 'token')

    def urlopen(self, request, **kwargs):
        with self.lock:
            return self._urlopen(request, **kwargs)

    def _urlopen(self, request, **kwargs):
        commands = json.loads(request.data)
        self.batches.append(commands)
        self.commands.extend(commands)
        entries = []
        for command in commands:
            op, key, *args = command
            if op == 'EVAL':
                script, count, spend_key, *arguments = command[1:]
                assert count == 1
                spend = float(self.values.get(spend_key, 0))
                if script == state.DailyCap.RESERVE_SCRIPT:
                    assert all(isinstance(arg, str) for arg in arguments)
                    amount, cap = map(float, arguments)
                    result = int(spend + amount <= cap + 1e-9)
                    if result:
                        self.values[spend_key] = spend + amount
                else:
                    assert script == state.DailyCap.SETTLE_SCRIPT
                    assert all(isinstance(arg, str) for arg in arguments)
                    self.values[spend_key] = max(0, spend + float(arguments[0]))
                    result = 1
            elif op == 'GET':
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
    key = 'websearch:spend:2026-01-01'
    assert cap.ok()
    cap.add(.001)
    assert fake.commands == [['GET', key], ['INCRBYFLOAT', key, .001], ['EXPIRE', key, 172800]]
    assert fake.values[key] == .001


@pytest.mark.parametrize('spent', [1, 1.01])
def test_shared_cap_at_or_over_budget_pauses(monkeypatch, spent):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    cap.add(spent)
    service = demo(cap=cap)
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused'
    service._client.search.assert_not_called()


@pytest.mark.parametrize('real_cost', [None, .001, 0, .0005, .003])
def test_reservation_before_upstream_and_adjustment(monkeypatch, real_cost):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    key = cap._key()
    service = demo(cap=cap)
    def search(*args):
        assert fake.values[key] == service.reserve_amount
        return 200, ROWS, real_cost
    service._client.search.side_effect = search
    assert call(service)[0] == 200
    assert fake.values[key] == pytest.approx(service.reserve_amount if real_cost is None else real_cost)
    evaluations = [c for c in fake.commands if c[0] == 'EVAL']
    assert len(evaluations) == (1 if real_cost is None else 2)
    assert all(len(batch) == 1 for batch in fake.batches)


@pytest.mark.parametrize('target', ['adjustment', 'cache.put'])
@pytest.mark.parametrize('error_type', [state.StateUnavailable, RuntimeError])
def test_paid_spend_survives_state_failure(monkeypatch, target, error_type):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    service = demo(cap=cap)
    if target == 'adjustment':
        monkeypatch.setattr(cap, 'settle', Mock(side_effect=error_type('private connection details')))
    else:
        service.cache.put = Mock(side_effect=error_type('private connection details'))
    code, _, body = call(service)
    expected = 200 if target == 'adjustment' and error_type is state.StateUnavailable else 503
    assert code == expected
    if expected == 200:
        assert body['results'] == ROWS
    assert 'private' not in json.dumps(body)
    service._client.search.assert_called_once()
    assert fake.values[cap._key()] == pytest.approx(service.reserve_amount if target == 'adjustment' else .002)


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
    service._client.search.assert_not_called()
    if failure == 'missing':
        opener.assert_not_called()


def test_shared_limiter_sixth_request_denied(monkeypatch):
    fake = FakeRedis(monkeypatch)
    limiter = state.Limiter(fake.redis, clock=lambda: 1767225600)
    ip = '203.0.113.1'
    assert [limiter.allow(ip) for _ in range(6)] == [True] * 5 + [False]
    hashed = hashlib.sha256(ip.encode()).hexdigest()
    key = f'websearch:limit:ip:{hashed}:10min:{1767225600 // 600}'
    for offset in range(0, len(fake.commands), 6):
        assert fake.commands[offset:offset + 2] == [['INCR', key], ['EXPIRE', key, 1200]]


@pytest.mark.parametrize('real_cost', [0, .0005])
def test_memory_cap_accepts_negative_adjustments(real_cost):
    service = demo(client=Mock(search=Mock(return_value=(200, ROWS, real_cost))))
    assert call(service)[0] == 200
    assert service.cap.spent == pytest.approx(real_cost)


@pytest.mark.parametrize('shared', [False, True])
def test_reserve_boundary_refusal_and_refunds(monkeypatch, shared):
    fake = FakeRedis(monkeypatch) if shared else None
    cap = state.DailyCap(fake.redis, .01) if shared else DailyCap(.01)
    def spent():
        return fake.values[cap._key()] if shared else cap.spent
    reservation = cap.reserve(.005)
    assert reservation
    assert cap.reserve(.005)
    assert spent() == pytest.approx(.01)
    assert not cap.reserve(.001)
    cap.settle(reservation, .001)
    assert spent() == pytest.approx(.006)
    cap.settle(reservation, None)
    assert spent() == pytest.approx(.006)
    cap.release(reservation)
    assert spent() == pytest.approx(.001)
    cap.settle(reservation, 0)
    assert spent() == 0
    cap.settle(reservation, .009)
    assert spent() == pytest.approx(.004)


def test_refused_reservation_has_sample_and_no_call():
    service = demo(cap=DailyCap(.004))
    status, headers, body = call(service)
    assert status == 503 and body['status'] == 'paused'
    assert body['sample'] and body['results'] and body['sample_url'] == '/sample.json'
    assert headers['Cache-Control'] == 'no-store'
    assert body['cost_usd_this_request'] == 0
    service._client.search.assert_not_called()


@pytest.mark.parametrize('failure', [OSError, TimeoutError])
def test_connection_exception_releases(failure):
    service = demo(client=Mock(search=Mock(side_effect=failure('private'))))
    status, _, body = call(service)
    assert status == 503 and body['cost_usd_this_request'] == 0
    assert service.cap.spent == 0


def test_shared_concurrent_reservations(monkeypatch):
    fake = FakeRedis(monkeypatch)
    barrier = threading.Barrier(40)
    client = Mock(search=Mock(return_value=(200, ROWS, None)))
    def request(index):
        cap = state.DailyCap(fake.redis, .025)
        service = demo(cap=cap, client=client, limiter=Mock(allow=Mock(return_value=True)))
        barrier.wait()
        return call(service, 'query ' + str(index))[0]
    with ThreadPoolExecutor(max_workers=40) as pool:
        statuses = list(pool.map(request, range(40)))
    assert statuses.count(200) == client.search.call_count == 5
    assert next(iter(fake.values.values())) <= .025 + 1e-9


def test_memory_cap_utc_roll():
    clock = Mock(return_value=1767225599)
    cap = DailyCap(.005, clock)
    assert cap.reserve(.005)
    assert not cap.reserve(.001)
    clock.return_value += 1
    assert cap.reserve(.005)
    assert cap.spent == .005


@pytest.mark.parametrize('result', [None, [], [None], ['1'], [2], [True], [1, 1]])
@pytest.mark.parametrize('method,args', [('reserve', (.005,)), ('settle', (state.Reservation('websearch:spend:2026-01-01', .005), .001))])
def test_malformed_eval_results(result, method, args):
    cap = state.DailyCap(Mock(pipeline=Mock(return_value=result)))
    with pytest.raises(state.StateUnavailable):
        getattr(cap, method)(*args)


def test_unexpected_exception_logs_only_type(caplog):
    service = demo()
    service.cache.get = Mock(side_effect=RuntimeError('private-query-sentinel private-key private-ip'))
    assert call(service, 'private-query-sentinel')[0] == 503
    assert [record.getMessage() for record in caplog.records] == ['search paused: RuntimeError']


@pytest.mark.parametrize('configured,expected', [('0.009', .009), ('0', .001), ('bad', .005), ('NaN', .005)])
def test_reservation_configuration(monkeypatch, configured, expected):
    monkeypatch.setenv('DEMO_RESERVE_COST_USD', configured)
    assert demo().reserve_amount == expected


def test_overrun_warning_numbers_only(caplog):
    service = demo(client=Mock(search=Mock(return_value=(200, ROWS, .008))))
    assert call(service)[0] == 200
    assert service.cap.spent == pytest.approx(.008)
    assert [record.getMessage() for record in caplog.records] == ['reservation overrun: 0.005 0.008']


def test_release_state_failure_still_pauses(caplog):
    cap = DailyCap()
    cap.release = Mock(side_effect=state.StateUnavailable('private'))
    service = demo(cap=cap, client=Mock(search=Mock(return_value=(599, None, None))))
    status, _, body = call(service)
    assert status == 503 and body['cost_usd_this_request'] == 0
    assert cap.spent == .005
    assert 'private' not in caplog.text


def test_eval_single_command_and_unknown_noop():
    redis = Mock(pipeline=Mock(return_value=[1]))
    cap = state.DailyCap(redis, .01, clock=lambda: 1767225600)
    key = 'websearch:spend:2026-01-01'
    reservation = cap.reserve(.005)
    assert reservation
    redis.pipeline.assert_called_once_with([
        ['EVAL', state.DailyCap.RESERVE_SCRIPT, 1, key, '0.005', '0.01']])
    redis.pipeline.reset_mock()
    cap.settle(reservation, None)
    redis.pipeline.assert_not_called()
    cap.release(reservation)
    redis.pipeline.assert_called_once_with([
        ['EVAL', state.DailyCap.SETTLE_SCRIPT, 1, key, '-0.005']])
    for script in (cap.RESERVE_SCRIPT, cap.SETTLE_SCRIPT):
        assert "redis.call('EXPIRE', KEYS[1], 172800)" in script


@pytest.mark.parametrize('status,cost,expected_spend,reported', [
    (599, None, 0, 0), (500, None, .005, .001), (200, 0, 0, 0),
    (200, .008, .008, .008)])
def test_shared_service_settlement(monkeypatch, status, cost, expected_spend, reported):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis)
    rows = ROWS if status == 200 else None
    service = demo(cap=cap, client=Mock(search=Mock(return_value=(status, rows, cost))))
    code, _, body = call(service)
    assert code == (200 if status == 200 else 503)
    assert body['cost_usd_this_request'] == reported
    assert fake.values[cap._key()] == pytest.approx(expected_spend)


@pytest.mark.parametrize('shared', [False, True])
@pytest.mark.parametrize('status,cost,old_spend', [(200, .001, .001), (599, None, 0)])
def test_service_reservation_crosses_utc_midnight(monkeypatch, shared, status, cost, old_spend):
    clock = Mock(return_value=1767225599)
    fake = FakeRedis(monkeypatch) if shared else None
    cap = state.DailyCap(fake.redis, clock=clock) if shared else DailyCap(clock=clock)
    old_key = cap._key() if shared else None

    def search(*args):
        clock.return_value += 1
        # Another request has already spent money on the new day.
        cap.add(.003)
        return status, ROWS if status == 200 else None, cost

    service = demo(cap=cap, client=Mock(search=Mock(side_effect=search)))
    assert call(service)[0] == (200 if status == 200 else 503)
    if shared:
        assert fake.values[old_key] == pytest.approx(old_spend)
        assert fake.values[cap._key()] == pytest.approx(.003)
        evaluations = [command for command in fake.commands if command[0] == 'EVAL']
        assert len(evaluations) == 2
        assert all(command[3] == old_key for command in evaluations)
        assert all(isinstance(arg, str) for command in evaluations for arg in command[4:])
    else:
        assert cap.day == '2026-01-01'
        assert cap.spent == pytest.approx(.003)
