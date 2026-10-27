import io

import json

from pathlib import Path

import urllib.error

from unittest.mock import Mock

from urllib.parse import parse_qs, urlsplit

import pytest

from weblinks.client import Client, NoRedirect, amount

from weblinks.guards import DailyCap, RateLimiter, TTLCache

from weblinks.service import Search, client_ip, parse_query

from weblinks import state

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

def test_cache_expiry():
    clock = Mock(return_value=0)
    cache = TTLCache(clock=clock)
    cache.put('q', {'results': []})
    clock.return_value = 899
    assert cache.get('q') is not None
    clock.return_value = 900
    assert cache.get('q') is None

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
        service._client.search.assert_not_called()

@pytest.mark.parametrize('variable', ['VERCEL', 'VERCEL_ENV'])
def test_memory_refused_on_vercel(monkeypatch, variable):
    monkeypatch.setenv(variable, '1')
    monkeypatch.setenv('DEMO_STATE', 'memory')
    service = Search(client=Mock())
    assert call(service)[0] == 503
    service._client.search.assert_not_called()

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
    assert command[1].startswith('weblinks:cache:') and 'example' not in command[1]
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
    key = 'weblinks:spend:2026-01-01'
    assert cap.ok()
    cap.add(.005)
    assert fake.commands == [['GET', key], ['INCRBYFLOAT', key, .005], ['EXPIRE', key, 172800]]
    assert fake.values[key] == .005

@pytest.mark.parametrize('spent', [1, 1.01])
def test_shared_cap_at_or_over_budget_pauses(monkeypatch, spent):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    cap.add(spent)
    service = demo(cap=cap)
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused'
    service._client.search.assert_not_called()

@pytest.mark.parametrize('real_cost', [None, .005, 0, .0005, .006])
def test_reservation_before_upstream_and_adjustment(monkeypatch, real_cost):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    key = cap._key()
    service = demo(cap=cap)
    def search(*args):
        assert fake.values[key] == service.fallback_cost
        return 200, ROWS, real_cost
    service._client.search.side_effect = search
    assert call(service)[0] == 200
    assert fake.values[key] == pytest.approx(service.fallback_cost if real_cost is None else real_cost)
    additions = [c for c in fake.commands if c[0] == 'INCRBYFLOAT']
    assert len(additions) == (1 if real_cost in (None, .005) else 2)

@pytest.mark.parametrize('target', ['adjustment', 'cache.put'])
@pytest.mark.parametrize('error_type', [state.StateUnavailable, RuntimeError])
def test_paid_spend_survives_state_failure(monkeypatch, target, error_type):
    fake = FakeRedis(monkeypatch)
    cap = state.DailyCap(fake.redis, clock=lambda: 1767225600)
    service = demo(cap=cap)
    if target == 'adjustment':
        original_add = cap.add
        def add(amount):
            if service._client.search.called:
                raise error_type('private connection details')
            original_add(amount)
        monkeypatch.setattr(cap, 'add', add)
    else:
        service.cache.put = Mock(side_effect=error_type('private connection details'))
    code, _, body = call(service)
    assert code == 503 and body['status'] == 'paused'
    assert 'private' not in json.dumps(body)
    service._client.search.assert_called_once()
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
    service._client.search.assert_not_called()
    if failure == 'missing':
        opener.assert_not_called()

def test_shared_limiter_sixth_request_denied(monkeypatch):
    fake = FakeRedis(monkeypatch)
    limiter = state.Limiter(fake.redis, clock=lambda: 1767225600)
    ip = '203.0.113.1'
    assert [limiter.allow(ip) for _ in range(6)] == [True] * 5 + [False]
    hashed = hashlib.sha256(ip.encode()).hexdigest()
    key = f'weblinks:limit:ip:{hashed}:10min:{1767225600 // 600}'
    for offset in range(0, len(fake.commands), 6):
        assert fake.commands[offset:offset + 2] == [['INCR', key], ['EXPIRE', key, 1200]]

@pytest.mark.parametrize('real_cost', [0, .0005])
def test_memory_cap_accepts_negative_adjustments(real_cost):
    service = demo(client=Mock(search=Mock(return_value=(200, ROWS, real_cost))))
    assert call(service)[0] == 200
    assert service.cap.spent == pytest.approx(real_cost)

KEY = 'test-secret-credential'
ROWS = [{'title':'Example', 'link':'https://example.org/page', 'domain':'example.org', 'snippet':'Text', 'date':None}]


def demo(**kwargs):
    return Search(client=kwargs.pop('client', Mock(search=Mock(return_value=(200, ROWS, .002)))),
        limiter=kwargs.pop('limiter', RateLimiter()), cap=kwargs.pop('cap', DailyCap()),
        cache=kwargs.pop('cache', TTLCache()), live=kwargs.pop('live', True), **kwargs)


def call(service, prompt='example', count='10'):
    code, headers, body = service.handle({'prompt':prompt, 'count':count}, '203.0.113.1')
    return code, headers, json.loads(body)


@pytest.mark.parametrize('prompt,count', [('', '10'), ('  ', '10'), ('a'*201,'10'), ('a\nb','10'), ('a\x00b','10'), (None,'10'), (12,'10'), ('fine','0'), ('fine','11'), ('fine','abc'), ('fine',1)])
def test_validation_before_state(prompt, count):
    objects = [Mock() for _ in range(4)]
    service = demo(client=objects[0], limiter=objects[1], cap=objects[2], cache=objects[3])
    assert call(service,prompt,count)[0] == 400
    assert all(not obj.mock_calls for obj in objects)


def test_request_and_count_cache():
    opener=Mock(return_value=Response(body={'search_results':ROWS*10}))
    service=demo(client=Client(KEY,opener),limiter=RateLimiter(per_ip=1))
    code,_,body=call(service,'  Example   Prompt  ','2')
    assert code==200 and len(body['results'])==2 and body['prompt']=='Example Prompt'
    request=opener.call_args.args[0]
    assert request.full_url=='https://api.desearch.ai/desearch/ai/search/links/web'
    assert request.method=='POST' and request.get_header('Authorization')==KEY
    assert request.get_header('Content-type')=='application/json'
    assert request.get_header('User-agent')=='desearch-py-examples/web-links-search-demo'
    assert json.loads(request.data)=={'prompt':'Example Prompt','tools':['web'],'count':10}
    assert opener.call_args.kwargs=={'timeout':50}
    service.live=False
    code,headers,body=call(service,'example prompt','7')
    assert code==200 and len(body['results'])==7 and body['cached']
    assert body['cost_usd_this_request']==0 and headers['X-Desearch-Cost-Usd']=='0'
    opener.assert_called_once()
    assert service.handle({'prompt':'default'},'203.0.113.2')[0]==503


def test_default_count_and_normalization():
    service=demo()
    code,_,body=service.handle({'prompt':'  One   two '},'203.0.113.1')
    assert code==200 and json.loads(body)['count']==10
    service._client.search.assert_called_once_with('One two')


def test_row_shape():
    from weblinks.client import shape
    rows=shape([None,1,{}, {'link':'javascript:alert(1)'},{'link':'/relative'},
        {'link':'https://WWW.Example.org/a','title':' ','snippet':None},
        {'link':'http://example.net','title':' x'+'a'*400,'snippet':' '+'b'*600,'published_date':'2026-10-26','highlights':['unused']},
        {'link':'https://example.com','published_date':'yesterday'}])
    assert len(rows)==3 and rows[0]=={'title':'example.org','link':'https://WWW.Example.org/a','domain':'example.org','snippet':'','date':None}
    assert len(rows[1]['title'])==300 and len(rows[1]['snippet'])==500
    assert rows[1]['date']=='2026-10-26' and rows[2]['date'] is None
    assert all(set(row)=={'title','link','domain','snippet','date'} for row in rows)


@pytest.mark.parametrize('header,body_cost,expected', [('.004',.9,.004),(None,.006,.006),('NaN',.006,.006),(None,None,.005),('-1','inf',.005),('0',.5,0)])
def test_cost_priority(header,body_cost,expected):
    service=demo(client=Client(KEY,Mock(return_value=Response({'X-DeSearch-Cost-Usd':header},{'search_results':ROWS,'cost_usd':body_cost}))))
    code,headers,body=call(service)
    assert code==200 and body['cost_usd_this_request']==expected
    assert float(headers['X-Desearch-Cost-Usd'])==expected
    assert service.cap.spent==pytest.approx(expected)


@pytest.mark.parametrize('status',[422,500,599])
def test_upstream_errors(status):
    service=demo(client=Mock(search=Mock(return_value=(status,None,None))))
    code,_,body=call(service)
    assert code==502 and body['status']=='upstream_error' and 'sample' not in body
    assert body['error']=='Search is not available right now. Try again in a minute.'
    assert service.cap.spent==.005 and KEY not in str(body)


@pytest.mark.parametrize('body',[b'bad json',b'{}',b'{"search_results":null}',b'[]'])
def test_bad_upstream(body):
    response=Response();response.body=body
    service=demo(client=Client(KEY,Mock(return_value=response)))
    assert call(service)[0]==502


def test_empty_not_cached_and_limit():
    service=demo(client=Mock(search=Mock(return_value=(200,[],.004))),limiter=RateLimiter(per_ip=1))
    assert call(service)[2]['results']==[]
    assert service.cache.get('example') is None
    code,_,body=call(service)
    assert code==429 and body['error']=='Too many searches. Try again later.'


def test_paused_defaults_missing_key_and_redis(monkeypatch):
    for service in (Search(client=Mock()),demo(live=False),demo(cap=DailyCap(0))):
        assert call(service)[2]['status']=='paused'
        service._client.search.assert_not_called()
    monkeypatch.setenv('DEMO_STATE','memory')
    service=Search()
    assert call(service)[0]==503
    monkeypatch.setenv('DEMO_LIVE','1')
    assert call(service)[0]==503


def test_transport_no_redirect():
    for error in (OSError('private'),http.client.IncompleteRead(b'',1)):
        assert Client(KEY,Mock(side_effect=error)).search('example')==(599,None,None)
    error=urllib.error.HTTPError('https://example.org',422,'private',{},io.BytesIO(b'{"error":"private"}'))
    assert Client(KEY,Mock(side_effect=error)).search('example')[0]==422
    assert NoRedirect().redirect_request(None,None,302,'',{},'https://example.org') is None


@pytest.mark.parametrize('entrypoint',['local','vercel'])
@pytest.mark.parametrize('method',['GET','POST'])
def test_handlers_no_logs(monkeypatch,capsys,entrypoint,method):
    from api import search
    from app import make_handler
    service=demo();monkeypatch.setattr(search,'SEARCH',service)
    handler=search.handler if entrypoint=='vercel' else make_handler(service)
    request=Mock();request.makefile.return_value=io.BytesIO(f'{method} /api/search?prompt=private HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
    handler(request,('127.0.0.1',12345),Mock())
    assert request.sendall.called and capsys.readouterr().err==''


def test_copy_secrets_config_and_buckets(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    for path in root.rglob('*'):
        if path.is_file() and path.suffix in ('.py','.md','.html','.json'):
            text=path.read_text();assert '\u2013' not in text and '\u2014' not in text
    html=(root/'public/index.html').read_text()
    assert 'innerHTML' not in html and 'textContent' in html
    assert 'DESEARCH_API_KEY' not in html and "rel='noopener noreferrer'" in html
    assert html.count('fetch(')==1 and "fetch('/api/search?'" in html
    sample=json.loads((root/'public/sample.json').read_text())
    assert sample['status']=='sample' and 3<=len(sample['results'])<=5
    assert all(row['domain'] in ('example.com','example.org','example.net') for row in sample['results'])
    assert state.ip_bucket('::ffff:203.0.113.1')==state.ip_bucket('203.0.113.1')
    assert state.ip_bucket('2001:db8::1')==state.ip_bucket('2001:db8::ffff')
    assert parse_query('/api/search?prompt=one+two&count=2')=={'prompt':'one two','count':'2'}
    monkeypatch.setenv('DESEARCH_API_KEY',KEY)
    for service in (demo(),demo(live=False),demo(client=Mock(search=Mock(side_effect=RuntimeError(KEY))))):
        assert KEY not in str(service.handle({'prompt':'example'},'203.0.113.1'))
    for path in (root/'public').iterdir():
        assert KEY not in path.read_text()


@pytest.mark.parametrize('live_value',[None,'0','true','yes','1'])
def test_explicit_live_switch(monkeypatch,live_value):
    if live_value is not None:
        monkeypatch.setenv('DEMO_LIVE',live_value)
    service=demo(live=None)
    assert call(service)[0]==(200 if live_value=='1' else 503)
    if live_value!='1':
        service._client.search.assert_not_called()


@pytest.mark.parametrize('payload',[{'error':'private'},[{'error':'private'}],[{}],[{'result':None},{'result':1}]])
def test_bad_redis_reply(monkeypatch,payload):
    monkeypatch.setattr('urllib.request.urlopen',Mock(return_value=Response(body=payload)))
    with pytest.raises(state.StateUnavailable):
        state.RedisREST('https://redis.test','token').pipeline([['GET','key']])


def test_missing_key_and_response_headers(monkeypatch):
    service=demo();service._client=None
    assert call(service)[0]==503
    code,headers,body=call(demo())
    assert code==200 and headers['Cache-Control']=='no-store'
    assert headers['X-Content-Type-Options']=='nosniff'
    assert body['sample'] is False and body['cached'] is False


def test_vercel_configuration():
    root=Path(__file__).resolve().parents[1]
    config=json.loads((root/'vercel.json').read_text())
    assert config['functions']=={'api/search.py':{'maxDuration':60,'includeFiles':'{weblinks/**,public/sample.json}'}}
    assert config['headers'][0]['headers']==[
        {'key':'X-Content-Type-Options','value':'nosniff'},
        {'key':'Referrer-Policy','value':'no-referrer'}]
