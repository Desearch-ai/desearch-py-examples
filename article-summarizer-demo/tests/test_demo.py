import io
import ast
import hashlib
import http.client
import json
import re
import shutil
import socket
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import pytest
from articlesum.client import Client, NoRedirect, connection_status
from articlesum.guards import DailyCap, RateLimiter, TTLCache
from articlesum.service import Summarize, client_ip, parse_query
from articlesum import state, summary, urlguard

URL='https://example.com/news/article'
KEY='test-secret-credential'
ARTICLE='\n'.join([
 'The garden reading room opened its doors to residents on Monday morning.',
 'The project added 40 seats beside the public garden for local readers.',
 'Volunteers will organize weekly workshops and invite suggestions from all residents.',
 'Evening opening hours will help people visit after returning home from work.',
 'The council plans to review the collection after the first winter season.',
 'Unusual zebras quietly juggle polished quartz beneath distant violet mountains.'
]+['Garden readers enjoy the public reading room and discuss books together.']*30)

def demo(**kwargs):
 return Summarize(client=kwargs.pop('client',Mock(extract=Mock(return_value=(200,ARTICLE,.002)))),
  limiter=kwargs.pop('limiter',RateLimiter()),cap=kwargs.pop('cap',DailyCap()),
  cache=kwargs.pop('cache',TTLCache()),live=kwargs.pop('live',True),**kwargs)

def call(service,url=URL):
 code,headers,body=service.handle({'url':url},'203.0.113.1')
 return code,headers,json.loads(body)

@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
 monkeypatch.setattr(urlguard,'validate_url_original',urlguard.validate_url,raising=False)
 import articlesum.service as service
 monkeypatch.setattr(service,'validate_url',lambda value, **kw: urlguard.validate_url_original(value, **kw) if kw else urlguard.validate_url_original(value,resolver=lambda *a,**k:[(2,1,6,'',('8.8.8.8',443))]))

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
        service._client.extract.assert_not_called()

@pytest.mark.parametrize('variable', ['VERCEL', 'VERCEL_ENV'])
def test_memory_refused_on_vercel(monkeypatch, variable):
    monkeypatch.setenv(variable, '1')
    monkeypatch.setenv('DEMO_STATE', 'memory')
    service = Summarize(client=Mock())
    assert call(service)[0] == 503
    service._client.extract.assert_not_called()

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
    key = 'articlesum:spend:2026-01-01'
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
    service._client.extract.assert_not_called()

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
    service._client.extract.assert_not_called()
    if failure == 'missing':
        opener.assert_not_called()

def test_shared_limiter_sixth_request_denied(monkeypatch):
    fake = FakeRedis(monkeypatch)
    limiter = state.Limiter(fake.redis, clock=lambda: 1767225600)
    ip = '203.0.113.1'
    assert [limiter.allow(ip) for _ in range(6)] == [True] * 5 + [False]
    hashed = hashlib.sha256(ip.encode()).hexdigest()
    key = f'articlesum:limit:ip:{hashed}:10min:{1767225600 // 600}'
    for offset in range(0, len(fake.commands), 6):
        assert fake.commands[offset:offset + 2] == [['INCR', key], ['EXPIRE', key, 1200]]

@pytest.mark.parametrize('entrypoint',['local','vercel'])
@pytest.mark.parametrize('method',['GET','POST'])
def test_handlers_no_logs(monkeypatch,capsys,entrypoint,method):
    from api import summarize
    from app import make_handler
    service=demo();monkeypatch.setattr(summarize,'SUMMARIZE',service)
    handler=summarize.handler if entrypoint=='vercel' else make_handler(service)
    request=Mock();request.makefile.return_value=io.BytesIO(f'{method} /api/summarize?url=https%3A%2F%2Fexample.com%2Fx HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
    handler(request,('127.0.0.1',12345),Mock())
    assert request.sendall.called and capsys.readouterr().err==''

@pytest.mark.parametrize('live_value',[None,'0','true','yes','1'])
def test_explicit_live_switch(monkeypatch,live_value):
    if live_value is not None:
        monkeypatch.setenv('DEMO_LIVE',live_value)
    service=demo(live=None)
    assert call(service)[0]==(200 if live_value=='1' else 503)
    if live_value!='1':
        service._client.extract.assert_not_called()

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
    assert config['functions']=={'api/summarize.py':{'maxDuration':60,'includeFiles':'{articlesum/**,public/sample.json}'}}
    assert config['headers'][0]['headers']==[
        {'key':'X-Content-Type-Options','value':'nosniff'},
        {'key':'Referrer-Policy','value':'no-referrer'}]
@pytest.mark.parametrize('value',['','  ',None,12,'https://[broken','ftp://example.com/x','https://localhost','http://127.0.0.1','http://10.1.2.3','http://169.254.169.254','http://[::1]','https://user:pass@example.com','https://example.com/file.pdf','https://example.com/'+('a'*2000)])
def test_validation_no_state(value):
 objects=[Mock() for _ in range(4)]
 service=demo(client=objects[0],limiter=objects[1],cap=objects[2],cache=objects[3])
 code,_,body=call(service,value)
 assert code==400 and body['status']=='invalid' and body['cost_usd_this_request']==0
 assert all(not obj.mock_calls for obj in objects)

@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','169.254.169.254','::1'])
def test_dns_private(address):
 with pytest.raises(urlguard.URLValidationError):
  urlguard.validate_url(URL,resolver=lambda *a,**k:[(2,1,6,'',(address,443))])

def test_unknown_dns(monkeypatch):
 import articlesum.service as service
 monkeypatch.setattr(service,'validate_url',Mock(side_effect=urlguard.URLUnreachableError()))
 assert call(demo())[2]['error']=='This link points to a private or unknown address.'

@pytest.mark.parametrize('second,expected',[(ARTICLE,200),('No content found.',502)])
def test_retry_once_and_sum(second,expected):
 client=Mock(extract=Mock(side_effect=[(404,'{"detail":"No content found."}',.0005),(200,second,.0005)]))
 service=demo(client=client)
 code,_,body=call(service)
 assert code==expected and client.extract.call_count==2
 assert body['cost_usd_this_request']==.001 and service.cap.spent==pytest.approx(.001)
 if code==200: assert body['calls']=={'extract':2}
 else: assert body['status']=='error' and 'sample' not in body

@pytest.mark.parametrize('status',[302,404,500,598,599])
def test_non_200(status):
 service=demo(client=Mock(extract=Mock(return_value=(status,'unavailable',None))))
 code,_,body=call(service)
 assert code==502 and body['status']=='error' and 'sample' not in body
 assert body['error']=='Desearch could not read this page right now. Try again in a minute.'
 service._client.extract.assert_called_once()


def test_near_empty_and_limits():
 service=demo(client=Mock(extract=Mock(return_value=(200,'Short text',.0005))),limiter=RateLimiter(per_ip=1))
 body=call(service)[2]
 assert body['status']=='near_empty' and body['words']==2 and body['preview']=='Short text'
 assert service.cache.get(URL) is None
 assert call(service)[0]==429
 assert call(service)[2]['error']=='Too many requests. Try again later.'


def test_shape_cache_and_no_full_text():
 service=demo(limiter=RateLimiter(per_ip=1))
 code,headers,body=call(service,'HTTPS://EXAMPLE.COM/news/article#section')
 assert code==200 and body['url']==URL and body['domain']=='example.com'
 assert body['label']=='Extractive summary: key sentences quoted from the article'
 assert body['key_points']==summary.key_sentences(ARTICLE,5)
 assert body['calls']=={'extract':1} and body['numbers'][0]['figures']==['40']
 omitted=next(s for s in summary.sentences(ARTICLE) if s not in body['key_points'] and s not in [r['sentence'] for r in body['numbers']])
 assert omitted not in json.dumps(body) and ARTICLE not in json.dumps(body)
 assert omitted not in json.dumps(service.cache.get(URL))
 service.live=False
 code,headers,body=call(service)
 assert code==200 and body['cached'] and body['cost_usd_this_request']==0
 assert headers['X-Desearch-Cost-Usd']=='0'
 service._client.extract.assert_called_once()

@pytest.mark.parametrize('real',[None,0,.0005,.002])
def test_reserve_adjust(real):
 service=demo()
 def extract(url):
  assert service.cap.spent==.001
  return 200,ARTICLE,real
 service._client.extract.side_effect=extract
 body=call(service)[2]
 assert body['cost_usd_this_request']==(.001 if real is None else real)
 assert service.cap.spent==pytest.approx(body['cost_usd_this_request'])

@pytest.mark.parametrize('header,body,expected',[('.0005',.9,.0005),(None,.002,.002),('NaN',.003,.003),(None,None,None),('-1','inf',None)])
def test_client_cost_and_request(header,body,expected):
 response=Response({'X-DeSearch-Cost-Usd':header},{'cost_usd':body})
 opener=Mock(return_value=response)
 status,text,cost=Client(KEY,opener).extract(URL)
 assert status==200 and cost==expected
 req=opener.call_args.args[0]
 assert req.get_method()=='GET' and req.data is None
 assert req.get_header('Authorization')==KEY
 assert req.get_header('User-agent')=='desearch-py-examples/article-summarizer-demo'
 assert parse_qs(urlsplit(req.full_url).query)=={'url':[URL],'format':['text'],'js':['false']}
 assert opener.call_args.kwargs=={'timeout':50}
 response.body=ARTICLE.encode()
 assert Client(KEY,opener).extract(URL)[1]==ARTICLE

@pytest.mark.parametrize('error,status',[(TimeoutError(),599),(urllib.error.URLError(TimeoutError()),599),(OSError(),598),(http.client.IncompleteRead(b'',1),598)])
def test_transport(error,status):
 assert Client(KEY,Mock(side_effect=error)).extract(URL)==(status,'',None)
 assert NoRedirect().redirect_request(None,None,302,'',{},URL) is None


def test_parity():
 root=Path(__file__).resolve().parents[1]
 names=['MIN_WORDS','HANDLE_RE','NUMBER_RE','STOP','word_count','is_near_empty','sentences','_words','key_sentences','_overlap','numbers_mentioned','hide_handles']
 def segments(path):
  source=path.read_text();result={}
  for node in ast.parse(source).body:
   name=node.name if isinstance(node,ast.FunctionDef) else node.targets[0].id if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) else None
   if name in names: result[name]=ast.get_source_segment(source,node)
  return result
 original=segments(root.parent/'article-summarizer-mcp/article_summarizer.py')
 assert set(original)==set(names)
 assert segments(root/'articlesum/summary.py')==original


def test_public_copy_and_js(tmp_path):
 root=Path(__file__).resolve().parents[1]
 for path in [* (root/'public').iterdir(),root/'README.md',root/'DEPLOY.md']:
  text=path.read_text()
  assert '\u2013' not in text and '\u2014' not in text
  assert not re.search(r'(?<![\w/@.])@\w{1,15}\b',text)
  if path.parent.name=='public':
   assert 'DESEARCH_API_KEY' not in text and KEY not in text
   assert not re.search(r'(?:sk-|ds_)[a-zA-Z0-9]{20,}',text)
 html=(root/'public/index.html').read_text()
 assert 'innerHTML' not in html and 'textContent' in html and 'overflow-wrap:anywhere' in html
 assert "rel='noopener noreferrer'" in html and "target='_blank'" in html
 sample=json.loads((root/'public/sample.json').read_text())
 assert sample['sample'] and sample['url'].startswith('https://example.com/news/')
 if not shutil.which('node'): pytest.skip('node unavailable')
 script=tmp_path/'inline.js';script.write_text(html.split('<script>')[1].split('</script>')[0])
 subprocess.run(['node','--check',str(script)],check=True,capture_output=True)


def test_key_never_returned(monkeypatch):
 monkeypatch.setenv('DESEARCH_API_KEY',KEY)
 for service in [demo(),demo(live=False),demo(client=Mock(extract=Mock(side_effect=RuntimeError(KEY))))]:
  assert KEY not in str(call(service))


def test_buckets():
 assert state.ip_bucket('::ffff:203.0.113.1')==state.ip_bucket('203.0.113.1')
 assert state.ip_bucket('2001:db8::1')==state.ip_bucket('2001:db8::ffff')


def test_redis_cache_key_and_ttl():
 redis=Mock()
 cache=state.Cache(redis)
 cache.put(URL,{'status':'ok'})
 command=redis.pipeline.call_args.args[0][0]
 assert command==['SET','articlesum:cache:'+hashlib.sha256(URL.encode()).hexdigest(),json.dumps({'status':'ok'}),'EX',900]


def test_state_and_guards_match_sibling():
 root=Path(__file__).resolve().parents[1]
 for name in ['state.py','guards.py']:
  assert (root/'articlesum'/name).read_text()==(root.parent/'web-links-search-demo/weblinks'/name).read_text().replace('weblinks','articlesum')
 assert (root/'articlesum/urlguard.py').read_bytes()==(root.parent/'page-to-markdown-api/pagemd/urlguard.py').read_bytes()
