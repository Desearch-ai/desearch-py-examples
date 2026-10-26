import io, hashlib, http.client, json, re, shutil, subprocess, urllib.error
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import pytest
from redditsearch.client import Client, NoRedirect
from redditsearch.guards import DailyCap, RateLimiter, TTLCache
from redditsearch.service import Search, client_ip, parse_query
from redditsearch import state, threads
ROOT=Path(__file__).resolve().parents[1]
KEY='test-secret-credential'
ROW={'title':'Winter plants','link':'https://www.reddit.com/r/plants/comments/abc123/winter_plants/','snippet':''}
def demo(**kwargs):
 return Search(client=kwargs.pop('client',Mock(search=Mock(return_value=(200,[ROW],.001)))),limiter=kwargs.pop('limiter',RateLimiter()),cap=kwargs.pop('cap',DailyCap()),cache=kwargs.pop('cache',TTLCache()),live=kwargs.pop('live',True),**kwargs)
def call(service,topic='plants'):
 code,headers,body=service.handle({'topic':topic},'203.0.113.1')
 return code,headers,json.loads(body)
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

def test_redis_aliases_and_failure(monkeypatch):
    monkeypatch.setenv('KV_REST_API_URL', 'https://redis.test/')
    monkeypatch.setenv('KV_REST_API_TOKEN', 'token')
    redis = state.RedisREST()
    assert redis._url == 'https://redis.test' and redis._token == 'token'
    monkeypatch.setattr('urllib.request.urlopen', Mock(side_effect=OSError('private connection details')))
    with pytest.raises(state.StateUnavailable) as error:
        redis.pipeline([['GET','key']])
    assert 'private' not in str(error.value)

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
    key = 'redditsearch:spend:2026-01-01'
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
    key = f'redditsearch:limit:ip:{hashed}:10min:{1767225600 // 600}'
    for offset in range(0, len(fake.commands), 6):
        assert fake.commands[offset:offset + 2] == [['INCR', key], ['EXPIRE', key, 1200]]

@pytest.mark.parametrize('entrypoint',['local','vercel'])
@pytest.mark.parametrize('method',['GET','POST'])
def test_handlers_no_logs(monkeypatch,capsys,entrypoint,method):
    from api import search
    from app import make_handler
    service=demo();monkeypatch.setattr(search,'SEARCH',service)
    handler=search.handler if entrypoint=='vercel' else make_handler(service)
    request=Mock();request.makefile.return_value=io.BytesIO(f'{method} /api/search?topic=plants HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
    handler(request,('127.0.0.1',12345),Mock())
    assert request.sendall.called and capsys.readouterr().err==''

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
    assert config['functions']=={'api/search.py':{'maxDuration':60,'includeFiles':'{redditsearch/**,public/sample.json}'}}
    assert config['headers'][0]['headers']==[
        {'key':'X-Content-Type-Options','value':'nosniff'},
        {'key':'Referrer-Policy','value':'no-referrer'}]

@pytest.mark.parametrize('topic',['','  ',None,12,'a'*201,'hello\x00','hello\x07world','SITE:reddit.com','sItE:foo'])
def test_invalid_free(topic):
 service=demo()
 service.cache=Mock();service.cap=Mock();service.limiter=Mock()
 code,headers,body=call(service,topic)
 assert code==400 and body['cost_usd_this_request']==0
 for obj in (service.cache,service.cap,service.limiter,service._client):assert not obj.mock_calls

@pytest.mark.parametrize('topic', ['  hello\tworld  ', '  hello\nworld  '])
def test_whitespace_normalization(topic):
 service=demo()
 code,_,body=call(service,topic)
 assert code==200 and body['topic']=='hello world'
 service._client.search.assert_called_once_with('site:reddit.com hello world')

def test_normalization_cache():
 service=demo(limiter=RateLimiter(per_ip=1))
 assert call(service,'  Plants   in winter  ')[0]==200
 service._client.search.assert_called_once_with('site:reddit.com Plants in winter')
 service.live=False
 body=call(service,'plants in WINTER')[2]
 assert body['cached'] and body['cost_usd_this_request']==0
 assert call(demo(),'x'*200)[0]==200

@pytest.mark.parametrize('paid',[None,0,.0005,.002])
def test_reserve_adjust(paid):
 service=demo()
 def search(query):
  assert service.cap.spent==.001
  return 200,[ROW],paid
 service._client.search.side_effect=search
 body=call(service)[2]
 assert body['cost_usd_this_request']==(.001 if paid is None else paid)
 assert service.cap.spent==pytest.approx(body['cost_usd_this_request'])

@pytest.mark.parametrize('status',[302,404,500,599])
def test_error_not_cached(status):
 service=demo(client=Mock(search=Mock(return_value=(status,None,None))))
 code,_,body=call(service)
 assert code==502 and 'sample' not in body and service.cache.get('plants') is None
 assert body['cost_usd_this_request']==.001

def test_empty_paid_cached_limits_cap():
 service=demo(client=Mock(search=Mock(return_value=(200,[],.001))),limiter=RateLimiter(per_ip=1))
 assert call(service)[2]['status']=='empty'
 assert call(service)[2]['cached']
 assert call(service,'other')[0]==429
 service.cap.add(1)
 assert call(service,'third')[0]==503

@pytest.mark.parametrize('header,cost,expected',[('.002',.9,.002),(None,.003,.003),('NaN',.004,.004),(None,None,None)])
def test_client(header,cost,expected):
 opener=Mock(return_value=Response({'X-DeSearch-Cost-Usd':header},{'data':[ROW], 'cost_usd':cost,'secret':KEY}))
 status,rows,paid=Client(KEY,opener).search('site:reddit.com plants & winter')
 assert status==200 and rows==[ROW] and paid==expected
 req=opener.call_args.args[0]
 assert parse_qs(urlsplit(req.full_url).query)=={'query':['site:reddit.com plants & winter'],'start':['0']}
 assert req.get_header('Authorization')==KEY and req.get_header('User-agent')=='desearch-py-examples/reddit-search-demo'
 assert opener.call_args.kwargs=={'timeout':45} and req.get_method()=='GET'
 for raw in [b'bad json',b'{}',b'[]']:
  opener.return_value.body=raw
  assert Client(KEY,opener).search('plants')[0]==502

@pytest.mark.parametrize('error',[OSError(),TimeoutError(),urllib.error.URLError('no'),http.client.IncompleteRead(b'',1)])
def test_network(error):
 assert Client(KEY,Mock(side_effect=error)).search('plants')==(599,None,None)
 assert NoRedirect().redirect_request(None,None,302,'',{},'https://example.com') is None

@pytest.mark.parametrize('host',['reddit.com','www.reddit.com','old.reddit.com','new.reddit.com','np.reddit.com','m.reddit.com'])
def test_hosts(host):
 assert threads.thread_parts('http://'+host+'/r/plants/COMMENTS/abc123/winter/?q=1#x')==('plants','abc123','winter')

@pytest.mark.parametrize('link',['https://evilreddit.com/r/plants/comments/ab/','https://reddit.com.example.org/r/plants/comments/ab/','reddit.com/r/plants/comments/ab/','javascript:alert(1)','https://reddit.com/user/example','https://reddit.com/u/example','https://reddit.com/r/plants/','https://i.redd.it/abc','https://v.redd.it/abc','https://preview.redd.it/abc','https://reddit.com/r/plants/wiki/a','https://reddit.com/search?q=a','https://reddit.com/r/plants/comments/ABC/'])
def test_rejected_links(link):assert threads.thread_parts(link) is None

@pytest.mark.parametrize('suffix,slug', [('', ''), ('/', ''), ('/winter_plants', 'winter_plants'), ('/winter_plants/', 'winter_plants')])
def test_thread_link_optional_trailing_slash(suffix, slug):
 link='https://www.reddit.com/r/houseplants/comments/sbrqzx'+suffix
 assert threads.thread_parts(link)==('houseplants','sbrqzx',slug)
 row=threads.shape_threads([{**ROW,'link':link}])[0]
 assert row['link']=='https://www.reddit.com/r/houseplants/comments/sbrqzx/'+(slug+'/' if slug else '')

def test_shape():
 rows=[{**ROW,'title':'r/plants on Reddit: Winter tips : r/plants','snippet':'  Ask u/example and /u/someone or @example  '+ 'a'*400}]
 rows += [{**ROW,'link':ROW['link'].replace('www.','old.')+'?a=1'}]
 rows += [{**ROW,'link':f'https://reddit.com/r/plants/comments/ab{i}/winter/','title':'Tips - Reddit'} for i in range(20)]
 shaped=threads.shape_threads(rows)
 assert len(shaped)==10 and shaped[0]['title']=='Winter tips' and shaped[1]['title']=='Tips'
 assert shaped[0]['link']==ROW['link'] and all(r['date'] is None for r in shaped)
 assert shaped[0]['snippet'].startswith('Ask u/[hidden] and u/[hidden] or @[hidden]') and len(shaped[0]['snippet'])==300
 assert threads.shape_threads([{**ROW,'title':'Tips | Reddit'}])[0]['title']=='Tips'
 assert threads.hide_handles('u/example /u/example @example')=='u/[hidden] u/[hidden] @[hidden]'

@pytest.mark.parametrize('title',list(threads.SHELL_TITLES)+['','WELCOME TO REDDIT extra'])
def test_shell(title):
 row=threads.shape_threads([{**ROW,'title':title}])[0]
 assert row['title']=='Winter plants' and row['title_from_link']
 row=threads.shape_threads([{**ROW,'title':title,'link':'https://reddit.com/r/plants/comments/abc123/'}])[0]
 assert row['title']=='Thread in r/plants'

def test_parity_sample_public():
 for name in ['state.py','guards.py']:
  assert (ROOT/'redditsearch'/name).read_text()==(ROOT.parent/'article-summarizer-demo/articlesum'/name).read_text().replace('articlesum','redditsearch')
 sample=json.loads((ROOT/'public/sample.json').read_text())
 fixture=json.loads((ROOT/'tests/fixtures/web-2026-10-26.json').read_text())
 assert sample['threads']==threads.shape_threads(fixture['data'][:20]) and len(sample['threads'])==10
 for path in list((ROOT/'public').iterdir())+[ROOT/'README.md',ROOT/'DEPLOY.md']:
  text=path.read_text()
  assert '\u2013' not in text and '\u2014' not in text
  assert not re.search(r'(?<![\w/])(?:@[A-Za-z0-9_]+|/?u/[A-Za-z0-9_-]+)',text)
  assert KEY not in text
  if path.parent.name=='public':
   assert 'DESEARCH_API_KEY' not in text
   assert not re.search(r'\b(?:sk-|ds_)[A-Za-z0-9_-]{16,}',text)
 html=(ROOT/'public/index.html').read_text()
 assert 'innerHTML' not in html
 assert KEY not in json.dumps(call(demo())[1:])

def test_inline_js():
 node=shutil.which('node')
 if not node:pytest.skip('node unavailable')
 script=re.search(r'<script>(.*?)</script>',(ROOT/'public/index.html').read_text(),re.S)[1]
 subprocess.run([node,'--check'],input=script,text=True,check=True,capture_output=True)

def test_title_handles_and_slug_limit():
 row=threads.shape_threads([{**ROW,'title':'Advice from /u/example and @example'}])[0]
 assert row['title']=='Advice from u/[hidden] and @[hidden]'
 row=threads.shape_threads([{**ROW,'title':'Login','link':'https://reddit.com/r/plants/comments/abc123/'+('winter-'*40)+'/'}])[0]
 assert len(row['title'])==120 and row['title_from_link']

def test_bad_json_service_and_no_secret():
 response=Response({'X-Desearch-Cost-Usd':'.001'})
 response.body=b'not json test-secret-credential'
 client=Client(KEY,Mock(return_value=response))
 service=demo(client=client)
 code,headers,body=call(service)
 assert code==502 and service.cache.get('plants') is None
 assert KEY not in json.dumps([headers,body])
 assert KEY not in json.dumps(call(demo(live=False))[1:])

def test_cache_expiration_and_key():
 clock=Mock(return_value=0)
 cache=TTLCache(clock=clock)
 cache.put('plants',{'status':'empty'})
 clock.return_value=900
 assert cache.get('plants') is None
 redis=Mock();shared=state.Cache(redis)
 shared.put('plants',{'status':'empty'})
 command=redis.pipeline.call_args.args[0][0]
 assert command[1]=='redditsearch:cache:'+hashlib.sha256(b'plants').hexdigest()
 assert command[-2:]==['EX',900]
 assert state.ip_bucket('::ffff:192.0.2.1')=='192.0.2.1'
 assert state.ip_bucket('2001:db8:1234:5678::1')==state.ip_bucket('2001:db8:1234:5678::2')
