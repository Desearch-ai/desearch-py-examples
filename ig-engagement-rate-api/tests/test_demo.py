import io
import json
import socket
import urllib.error

import pytest
from igrate.client import Client, USER_AGENT, sanitize
from igrate.guards import DailyCap, RateLimiter, TTLCache
from igrate.handles import validate_handle
from igrate.service import Engagement, calculate, client_ip, parse_query
from igrate import state


class Fake:
    def __init__(self, profile=(200, {'followers': 1000}, .00207), posts=None):
        self.profile = profile
        self.posts = posts or (200, [{'url':'', 'type':'image', 'likes':100, 'comments':10, 'taken_at':100000}], .02484)
        self.calls = []

    def fetch(self, handle, posts=False, timeout=45):
        self.calls.append((handle, posts, timeout))
        return self.posts if posts else self.profile


def demo(client=None, **kwargs):
    return Engagement(client=client or Fake(), limiter=kwargs.pop('limiter', RateLimiter()), cap=kwargs.pop('cap', DailyCap()), cache=kwargs.pop('cache', TTLCache()), **kwargs)


def run(d, handle='creator', ip='1.2.3.4'):
    code, headers, body = d.handle({'handle':handle}, ip)
    return code, headers, json.loads(body)


@pytest.mark.parametrize('handle', ['', None, 'a..b', '.abc', 'abc.', 'https://instagram.com/a', 'a/b', 'a?b', 'a b', ' a', 'a\n', '@@abc', 'a'*31, 'é', 'a%2fb'])
def test_invalid_before_state_or_call(handle):
    d = demo()
    assert run(d, handle)[0] == 400
    assert not d._client.calls
    assert not d.limiter.hits
    assert d.cap.spent == 0


@pytest.mark.parametrize('handle, expected', [('@A.b_2','a.b_2'), ('a','a'), ('_'*30,'_'*30), ('a'*30,'a'*30)])
def test_validation(handle, expected):
    assert validate_handle(handle) == expected


def test_success_cache_and_featured_bypass_limits():
    d = demo()
    code, headers, body = run(d, '@CREATOR')
    assert code == 200 and 's-maxage=86400' in headers['Cache-Control']
    a = body['accounts'][0]
    assert a['engagement_rate_pct'] == 11
    assert a['eligible_posts'] == a['posts_used'] == 1
    assert set(a['posts'][0]) == {'url','type','likes','comments','taken_at'}
    assert len(d._client.calls) == 2
    assert d.cap.spent == pytest.approx(.02691)
    for _ in range(12):
        assert run(d)[2]['cached'] is True
        assert run(d, d.sample['accounts'][0]['handle'])[2]['sample'] is True
    assert len(d.limiter.hits['1.2.3.4']) == 1
    assert len(d._client.calls) == 2


@pytest.mark.parametrize('status', [401,402,403,500,502,503,599])
@pytest.mark.parametrize('posts', [False,True])
def test_paused_errors_no_retry(status, posts):
    c = Fake()
    if posts: c.posts = (status, None, None)
    else: c.profile = (status, None, None)
    d = demo(c)
    code, headers, body = run(d)
    assert code == (404 if posts else 503) and headers['Cache-Control'] == 'no-store'
    if posts:
        assert body == {'error': 'account not found or private'}
    else:
        assert body['sample'] is True and body['status'] == 'paused'
    assert len(c.calls) == (2 if posts else 1)
    if status == 599: assert d.cap.spent >= .027


@pytest.mark.parametrize('profile, posts', [((404,{},0),None), ((422,{},0),None), ((302,{},0),None), ((200,{'is_private':True},0),None), ((200,{'private':True},0),None), ((200,{'followers':1},0),(200,[],0)), ((200,{'followers':1},0),(404,[],0))])
def test_missing_private(profile, posts):
    c = Fake(profile=profile)
    if posts is not None: c.posts = posts
    d = demo(c)
    code, _, body = run(d)
    assert code == 404 and body == {'error':'account not found or private'}
    assert len(c.calls) == (2 if posts else 1)


def test_budget_preflight():
    d = demo(cap=DailyCap(.0269))
    assert run(d)[0] == 503 and not d._client.calls
    d = demo(cap=DailyCap(.027))
    assert run(d)[0] == 200
    assert run(d,'other')[0] == 503


def test_rate_limits_and_no_budget_charge_when_limited():
    d = demo()
    assert run(d,'first')[0] == 200
    assert run(d,'second')[0] == 200
    spent = d.cap.spent
    assert run(d,'third')[0] == 429
    assert d.cap.spent == pytest.approx(spent)
    assert len(d._client.calls) == 4


def test_limiter_day_global_ipv6_and_windows():
    now=[0]
    limit=RateLimiter(clock=lambda:now[0])
    for index in range(5):
        if index: now[0]+=601
        assert limit.allow('1.2.3.4')
    now[0]+=601
    assert not limit.allow('1.2.3.4')
    now[0]=86401
    assert limit.allow('1.2.3.4')
    limit=RateLimiter()
    for i in range(10): assert limit.allow('10.0.0.'+str(i))
    assert not limit.allow('11.0.0.1')
    limit=RateLimiter()
    assert limit.allow('2001:db8::1') and limit.allow('2001:db8::2')
    assert not limit.allow('2001:db8::3')


def test_cache_expiry():
    now=[0]
    cache=TTLCache(clock=lambda:now[0])
    cache.put('a', {'value':1})
    now[0]=86399
    assert cache.get('a')
    now[0]=86400
    assert cache.get('a') is None


def test_kill_switch_missing_key_and_unavailable_state(monkeypatch):
    d=demo(live=False)
    assert run(d)[0] == 503 and not d._client.calls
    d=demo()
    d._client=None
    assert run(d)[0] == 503
    monkeypatch.delenv('DEMO_STATE',raising=False)
    monkeypatch.delenv('UPSTASH_REDIS_REST_URL',raising=False)
    monkeypatch.delenv('KV_REST_API_URL',raising=False)
    assert run(Engagement(client=Fake()))[0] == 503
    monkeypatch.setenv('DEMO_STATE','memory')
    monkeypatch.setenv('VERCEL','1')
    d=Engagement(client=Fake())
    assert run(d)[0] == 503 and not d._client.calls
    assert run(d,d.sample['accounts'][0]['handle'])[0] == 200


class Response(io.BytesIO):
    status=200
    def __init__(self, body, headers=None):
        super().__init__(json.dumps(body).encode())
        self.headers=headers or {}


@pytest.mark.parametrize('header, bodycost, expected', [('0.003',.5,.003), ('bad',.004,.004), ('nan',.004,.004), ('-1',None,None), (None,None,None)])
def test_client_cost_and_routes(header,bodycost,expected):
    calls=[]
    def opener(req, timeout):
        calls.append((req.full_url,req.method,timeout,req.get_header('Authorization')))
        return Response({'followers':123,'cost_usd':bodycost,'caption':'SECRET'}, {'X-Desearch-Cost-Usd':header} if header is not None else {})
    c=Client('offline-placeholder',opener)
    status,body,cost=c.fetch('creator',timeout=44)
    assert (status,body,cost)==(200,{'followers':123,'is_private':False},expected)
    c.fetch('creator',posts=True,timeout=20)
    assert calls[0][0]=='https://api.desearch.ai/desearch/instagram/profile/creator'
    assert calls[1][0].endswith('/creator/posts?count=12')
    assert calls[0][1:] == ('GET',44,'offline-placeholder')


def test_sanitize_http_response_and_no_cursor():
    raw=[{'shortcode':'Ab_2','mediaType':'carousel','stats':{'likeCount':10,'commentCount':2},'createTime':100000,'caption':'SECRET','usertags':['SECRET'],'children':[{'SECRET':1}]}]*20
    calls=[]
    def opener(req,timeout):
        calls.append(req.full_url)
        return Response(raw)
    status,posts,cost=Client('offline-placeholder',opener).fetch('a',posts=True)
    assert len(posts)==12 and len(calls)==1
    assert 'SECRET' not in json.dumps(posts) and 'children' not in json.dumps(posts)
    assert set(posts[0])=={'url','type','likes','comments','taken_at'}
    assert posts[0]['url']=='https://www.instagram.com/p/Ab_2/'


def test_client_http_error_timeout_and_no_redirect():
    def err(req,timeout): raise urllib.error.HTTPError(req.full_url,403,'denied',{},io.BytesIO(b'{}'))
    assert Client('offline-placeholder',err).fetch('a')[0]==403
    def timeout(req,timeout): raise TimeoutError()
    assert Client('offline-placeholder',timeout).fetch('a')==(599,None,None)
    from igrate.client import NoRedirect
    assert NoRedirect().redirect_request(None,None,None,None,None,None) is None


@pytest.mark.parametrize('posts', [False, True])
def test_client_user_agent(posts):
    calls = []
    def opener(request, timeout):
        calls.append(request)
        return Response({})
    Client('offline-placeholder', opener).fetch('creator', posts=posts)
    assert USER_AGENT == 'desearch-py-examples/ig-engagement-demo'
    assert calls[0].get_header('User-agent') == USER_AGENT


def test_client_plain_text_forbidden_pauses_with_sample():
    calls = []
    def opener(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(
            request.full_url, 403, 'Forbidden', {'Content-Type': 'text/plain'},
            io.BytesIO(b'error code: 1010'))
    client = Client('offline-placeholder', opener)
    assert client.fetch('creator') == (403, {'followers': None, 'is_private': False}, None)
    calls.clear()
    code, headers, body = run(demo(client))
    assert code == 503
    assert headers['Cache-Control'] == 'no-store'
    assert body['status'] == 'paused' and body['sample'] is True
    assert body['accounts']
    assert len(calls) == 1


def test_fallback_and_deadline(monkeypatch):
    monkeypatch.setenv('DEMO_FALLBACK_COST_USD','.01')
    d=demo(Fake(profile=(200,{'followers':10},None),posts=(200,[{'url':'','type':'image','likes':1,'comments':0,'taken_at':1}],None)))
    assert run(d)[0]==200 and d.cap.spent==pytest.approx(.02)
    values=iter([0,0,46])
    d=demo(clock=lambda:next(values))
    assert run(d)[0]==503
    assert d.cap.spent==pytest.approx(.027)
    assert len(d._client.calls)==1


def test_math_null_hidden_fresh_and_pinned():
    def post(t,likes=100,kind='image'): return {'url':'','type':kind,'likes':likes,'comments':10,'taken_at':t}
    now=1000000
    posts=[post(1),post(2),post(3),post(now-100000,100,'carousel'),post(now-200000,None),post(now-100)]
    result=calculate(1000,posts,now)
    assert result['posts_used']==1 and result['engagement_rate_pct']==11
    assert result['by_format']=={'image':None,'carousel':11,'video':None}
    assert calculate(0,posts,now)['engagement_rate_pct'] is None
    assert calculate(1000,[post(now)],now)['engagement_rate_pct'] is None
    assert calculate(1000,[post('bad')],now)['eligible_posts']==0


def test_shared_cap_limiter_and_cache():
    redis = FakeRedis()
    cap = state.DailyCap(redis)
    assert cap.ok()
    cap.add(1)
    assert not cap.ok()
    assert redis.commands[-2][0][0] == 'INCRBYFLOAT'
    assert redis.expires[cap._key()] == 172800
    assert state.Limiter(redis).allow('1.2.3.4')
    commands = redis.commands[-1]
    assert [c[0] for c in commands] == ['INCR', 'EXPIRE'] * 3
    assert '1.2.3.4' not in json.dumps(commands)
    cache = state.Cache(redis)
    cache.put('creator', {'safe': 1})
    assert redis.commands[-1][0][-1] == 86400
    assert 'creator' not in json.dumps(redis.commands[-1])
    assert cache.get('creator') == {'safe': 1}
    redis.values[cache._key('a')] = 'invalid'
    with pytest.raises(state.StateUnavailable):
        cache.get('a')


def test_sample_and_entrypoints():
    import app
    from api.engagement import handler
    d=demo()
    assert d.sample['sample'] is True and 'EXAMPLE' in d.sample['label']
    for account in d.sample['accounts']:
        for post in account['posts']: assert set(post)=={'url','type','likes','comments','taken_at'}
    assert handler.log_message(None,'anything') is None
    assert parse_query('/api/engagement?handle=%40Ab')=={'handle':'@Ab'}
    assert client_ip({'X-Vercel-Forwarded-For':'1.2.3.4, 5.6.7.8'})=='1.2.3.4'


def test_network_is_blocked():
    with pytest.raises(AssertionError): socket.create_connection(('example.com',443))


@pytest.mark.parametrize('shared', [False, True])
def test_budget_utc_rollover(shared):
    now = [0]
    cap = state.DailyCap(FakeRedis(), clock=lambda: now[0]) if shared else DailyCap(clock=lambda: now[0])
    cap.add(1)
    assert not cap.ok()
    now[0] = 86400
    assert cap.ok()


def test_redis_transport_failures_and_response_validation(monkeypatch):
    redis=state.RedisREST('https://state.invalid','offline-placeholder')
    for body in ({}, [{'error':'denied'}], [], [{'result':1},{'result':2}]):
        monkeypatch.setattr('urllib.request.urlopen',lambda *a, _body=body, **kw:Response(_body))
        with pytest.raises(state.StateUnavailable): redis.pipeline([['GET','a']])
    monkeypatch.setattr('urllib.request.urlopen',lambda *a, **kw:Response([{'result':'ok'}]))
    assert redis.pipeline([['GET','a']])==['ok']
    def failed(*a,**kw): raise TimeoutError()
    monkeypatch.setattr('urllib.request.urlopen',failed)
    with pytest.raises(state.StateUnavailable): redis.pipeline([['GET','a']])


def test_state_failure_prevents_paid_call():
    class Unavailable:
        def allow(self, ip): raise state.StateUnavailable()
    d=demo(limiter=Unavailable())
    assert run(d)[0]==503 and not d._client.calls
    assert d.cap.spent == 0


def test_local_and_vercel_handlers_without_sockets(monkeypatch):
    import app
    import api.engagement as api
    d=demo(live=False)
    def request(cls,path):
        h=object.__new__(cls)
        h.path=path
        h.headers={}
        h.client_address=('127.0.0.1',1)
        h.wfile=io.BytesIO()
        codes=[]
        h.send_response=codes.append
        h.send_header=lambda *a:None
        h.end_headers=lambda:None
        h.do_GET()
        return codes[0],h.wfile.getvalue()
    H=app.make_handler(d)
    assert request(H,'/')[0]==200
    assert request(H,'/sample.json')[0]==200
    assert request(H,'/../README.md')[0]==404
    assert request(H,'/api/engagement?handle=bad/url')[0]==400
    monkeypatch.setattr(api,'ENGAGEMENT',d)
    assert request(api.handler,'/api/engagement?handle=creator')[0]==503


def test_copy_and_timeout_configuration():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    html=(root/'public/index.html').read_text()
    assert '45000' in html and 'AbortController' in html and '<progress' in html
    assert 'textContent' in html and 'innerHTML' not in html
    assert 'Made by' in html and 'https://desearch.ai' in html
    config=json.loads((root/'vercel.json').read_text())
    assert config['functions']['api/engagement.py']['maxDuration']==60
    for path in root.rglob('*'):
        if path.suffix in ('.html','.md','.json'):
            text=path.read_text()
            assert '\u2014' not in text and 'real-time' not in text


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.commands = []
        self.expires = {}

    def pipeline(self, commands):
        self.commands.append(commands)
        results = []
        for command in commands:
            op, key, *args = command
            if op == 'GET':
                value = self.values.get(key)
            elif op == 'INCR':
                value = self.values[key] = int(self.values.get(key, 0)) + 1
            elif op == 'INCRBYFLOAT':
                value = self.values[key] = float(self.values.get(key, 0)) + args[0]
            elif op == 'EXPIRE':
                self.expires[key] = args[0]
                value = 1
            elif op == 'SET':
                self.values[key] = args[0]
                assert args[1] == 'EX'
                self.expires[key] = args[2]
                value = 'OK'
            else:
                raise AssertionError(op)
            results.append(value)
        return results



@pytest.mark.parametrize('fixture, expected_calls', [('profile_private.json', 1), ('posts_empty.json', 2)])
def test_private_and_empty_response_fixtures(fixture, expected_calls):
    from pathlib import Path
    payload = json.loads((Path(__file__).parent / 'fixtures' / fixture).read_text())
    calls = []
    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(payload if fixture == 'profile_private.json' or len(calls) == 2 else {'followers': 123})
    d = demo(Client('offline-placeholder', opener))
    code, _, body = run(d)
    assert code == 404
    assert body == {'error': 'account not found or private'}
    assert len(calls) == expected_calls


@pytest.mark.parametrize('scope', ['short', 'day', 'global'])
def test_shared_reference_limiter_windows(scope):
    now = [0]
    redis = FakeRedis()
    a = state.Limiter(redis, clock=lambda: now[0])
    b = state.Limiter(redis, clock=lambda: now[0])
    count = {'short': 2, 'day': 5, 'global': 10}[scope]
    for i in range(count):
        if scope == 'day':
            now[0] = i * 600
        ip = '192.0.2.' + str(i) if scope == 'global' else '192.0.2.1'
        assert (a if i % 2 else b).allow(ip)
    ip = '192.0.2.99' if scope == 'global' else '192.0.2.1'
    assert not b.allow(ip)
    # The reference counts denied attempts in every counter as well.
    assert len(redis.commands[-1]) == 6
    assert redis.values[redis.commands[-1][4][1]] == (2 if scope == 'day' else count + 1)
    now[0] = 86400 if scope == 'day' else 600
    assert a.allow(ip)


@pytest.mark.parametrize('cap_value', [None, 'invalid', 'nan', '-1', '1'])
def test_shared_default_cap_cache_and_estimate(monkeypatch, cap_value):
    redis = FakeRedis()
    monkeypatch.delenv('DEMO_STATE', raising=False)
    if cap_value is None:
        monkeypatch.delenv('DEMO_DAILY_CAP_USD', raising=False)
    else:
        monkeypatch.setenv('DEMO_DAILY_CAP_USD', cap_value)
    monkeypatch.setattr(state, 'RedisREST', lambda: redis)
    a, b = Engagement(client=Fake()), Engagement(client=Fake())
    assert a.cap.cap == b.cap.cap == 1
    assert run(a)[0] == 200
    assert run(b)[2]['cached'] is True
    assert not b._client.calls
    redis.values[a.cap._key()] = .974
    assert run(b, 'other')[0] == 503
    assert not b._client.calls
    redis.values[a.cap._key()] = .973
    assert run(b, 'other')[0] == 200


def test_reference_limit_environment_conventions(monkeypatch):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    monkeypatch.setenv('DEMO_PER_IP_10MIN', '3')
    monkeypatch.setenv('DEMO_PER_IP_DAY', '7')
    monkeypatch.setenv('DEMO_GLOBAL_10MIN', '12')
    d = Engagement(client=Fake())
    assert (d.limiter.per_ip, d.limiter.per_ip_day, d.limiter.global_window) == (3, 7, 12)
    monkeypatch.delenv('DEMO_STATE')
    d = Engagement(client=Fake())
    assert d.limiter.limits == (3, 7, 12)


def test_redis_environment_aliases(monkeypatch):
    for key in ('UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('KV_REST_API_URL', 'https://alias.invalid/')
    monkeypatch.setenv('KV_REST_API_TOKEN', 'offline-alias')
    redis = state.RedisREST()
    assert (redis._url, redis._token) == ('https://alias.invalid', 'offline-alias')
    monkeypatch.setenv('UPSTASH_REDIS_REST_URL', 'https://primary.invalid/')
    monkeypatch.setenv('UPSTASH_REDIS_REST_TOKEN', 'offline-primary')
    redis = state.RedisREST()
    assert (redis._url, redis._token) == ('https://primary.invalid', 'offline-primary')


@pytest.mark.parametrize('flag', ['private', 'is_private'])
def test_client_private_flags(flag):
    payload = {'followers': 123, 'private': False, flag: True}
    client = Client('offline-placeholder', lambda req, timeout: Response(payload))
    d = demo(client)
    assert run(d)[0:1] == (404,)
    assert run(d)[2] == {'error': 'account not found or private'}


def test_live_shape_fixtures_and_header_cost(monkeypatch):
    from pathlib import Path
    from datetime import datetime
    fixtures = Path(__file__).parent / 'fixtures'
    payloads = [json.loads((fixtures / name).read_text()) for name in ('profile_public.json', 'posts_public.json')]
    calls = []
    def opener(request, timeout):
        index = len(calls)
        calls.append(request.full_url)
        return Response(payloads[index], {'x-desearch-cost-usd': ['0.00207', '0.02484'][index]})
    monkeypatch.setattr('igrate.service.time.time', lambda: datetime.fromisoformat('2026-10-21T18:17+04:00').timestamp())
    d = demo(Client('offline-placeholder', opener))
    code, _, body = run(d)
    assert code == 200 and len(calls) == 2
    account = body['accounts'][0]
    assert account['followers'] == 268325407
    assert account['posts_used'] == account['eligible_posts'] == 1
    assert account['engagement_rate_pct'] == 0.0197
    assert account['by_format'] == {'image': None, 'carousel': None, 'video': 0.0197}
    assert account['posts'][1] == {'url': 'https://www.instagram.com/p/DeuOR-CjKE9/', 'type': 'image', 'likes': 11547, 'comments': 130, 'taken_at': '2026-10-20T16:06:30+00:00'}
    assert d.cap.spent == pytest.approx(0.02691)


def test_sample_snapshot_computation():
    from datetime import datetime
    sample = demo().sample
    assert sample['generated_at'] == sample['source_date'] == '2026-10-21T18:17+04:00'
    assert sample['source_note'] == 'one live build of natgeo'
    assert len(sample['accounts']) == 1
    account = sample['accounts'][0]
    assert account['handle'] == 'natgeo' and len(account['posts']) == 12
    now = datetime.fromisoformat(sample['source_date']).timestamp()
    assert account == {'handle': 'natgeo', **calculate(account['followers'], account['posts'], now=now)}
    assert account['posts_used'] == 5
    assert account['engagement_rate_pct'] == 0.0315
