import importlib.util
import io
import json
from pathlib import Path
import re
from unittest.mock import Mock
import pytest
from searchapp import core, state
from searchapp.service import Engine, client_ip
from searchapp.client import Client

ROOT = Path(__file__).resolve().parents[1]
KEY = 'fake-private-key'
TOKEN = 'fake-private-token'


class Redis:
    def __init__(self):
        self.commands, self.values = [], {}

    def pipeline(self, commands):
        self.commands.extend(commands)
        out = []
        for op, key, *args in commands:
            assert key.startswith('aisearch:')
            if op == 'GET':
                value = self.values.get(key)
            elif op in ('INCR', 'INCRBYFLOAT'):
                value = self.values[key] = float(self.values.get(key, 0)) + (1 if op == 'INCR' else float(args[0]))
            elif op == 'SET':
                self.values[key] = args[0]
                value = 'OK'
            else:
                assert op == 'EXPIRE'
                value = 1
            out.append(value)
        return out


def demo(monkeypatch, paid=.006, **kwargs):
    redis = Redis()
    monkeypatch.setattr(state, 'RedisREST', lambda: redis)
    client = Mock()
    client.search.return_value = (200, {'results': []}, {'cost': paid, 'cost_known': paid is not None})
    client.ai_search.return_value = (200, {'search': [], 'completion': ''}, {'cost': paid, 'cost_known': paid is not None})
    return Engine(client=client, **kwargs), redis


def call(engine, kind='search', query=None):
    code, headers, text = getattr(engine, 'handle_' + kind)({'q': 'test query'} if query is None else query, '203.0.113.1')
    body = json.loads(text)
    assert headers['Cache-Control'] == 'no-store'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert body['cost_usd_this_request'] == float(headers['X-Desearch-Cost-Usd'])
    assert KEY not in text + str(headers) and TOKEN not in text + str(headers)
    assert 'cached' in body and len(body['limits']) == 3
    return code, body


def test_state_parity_and_frozen_lines():
    assert (ROOT/'searchapp/state.py').read_bytes() == (ROOT.parent/'reddit-search-demo/redditsearch/state.py').read_bytes().replace(b"namespace='redditsearch'", b"namespace='aisearch'")
    import subprocess
    for name, count in [('core.py', 106), ('client.py', 42)]:
        original = subprocess.check_output(['git', 'show', 'HEAD:ai-search-engine-web-app/searchapp/' + name])
        assert (ROOT/'searchapp'/name).read_bytes().splitlines(keepends=True)[:count] == original.splitlines(keepends=True)[:count]


@pytest.mark.parametrize('paid', [None, 0, .003, .01])
def test_reserve_adjust_and_shared_cap(monkeypatch, paid):
    e, redis = demo(monkeypatch, paid, live=True)
    original = e._client.search.return_value
    def search(*args):
        assert sum(v for k,v in redis.values.items() if ':spend:' in k) == .005
        return original
    e._client.search.side_effect = search
    assert call(e)[0] == 200
    assert call(e, 'answer')[0] == 200
    spend = [c for c in redis.commands if c[0] == 'INCRBYFLOAT']
    assert len({c[1] for c in spend}) == 1
    assert sum(c[2] for c in spend) == pytest.approx(2 * (.005 if paid is None else paid))
    e.cap.add(1)
    assert call(e, 'answer', {'q': 'other query'})[0] == 503


def test_shared_between_engine_instances(monkeypatch):
    e, redis = demo(monkeypatch, live=True)
    second = Engine(client=e._client, live=True)
    assert call(e)[0] == 200
    assert call(second, 'answer')[0] == 200
    e.cap.add(1)
    assert call(second, 'answer', {'q': 'new query'})[0] == 503


def test_shared_limiter_cache(monkeypatch):
    monkeypatch.setenv('DEMO_PER_IP_10MIN', '1')
    e, redis = demo(monkeypatch, live=True)
    assert call(e)[0] == 200
    assert call(e)[1]['cached'] is True
    assert call(e)[1]['cost_usd_this_request'] == 0
    assert e._client.search.call_count == 1
    assert call(e, 'answer')[0] == 429
    assert all('203.0.113.1' not in c[1] for c in redis.commands)
    assert all(c[-2:] == ['EX', 900] for c in redis.commands if c[0] == 'SET')


@pytest.mark.parametrize('query', [{}, {'q': ''}, {'q': 12}, {'q': 'test', 'mode': 'bad'}, {'q': 'test', 'count': '15'}, {'q': 'test', 'count': '20'}, {'q': 'test', 'count': ''}, {'q': 'test', 'range': 'bad'}, {'q': 'test', 'from': '2026-02-30'}])
def test_invalid_free(monkeypatch, query):
    e, redis = demo(monkeypatch, live=True)
    code, body = call(e, query=query)
    assert code == 400 and body['cost_usd_this_request'] == 0
    if 'count' in query:
        assert body['error'] == 'The live demo returns 10 results.'
    assert redis.commands == [] and not e._client.mock_calls


@pytest.mark.parametrize('value', ['', '0', 'true', 'yes', '2', '1'])
def test_live(monkeypatch, value):
    monkeypatch.setenv('DEMO_LIVE', value)
    e, _ = demo(monkeypatch)
    assert call(e)[0] == (200 if value == '1' else 503)


@pytest.mark.parametrize('target', ['cache.get', 'cap.ok', 'limiter.allow', 'cap.add', 'cache.put'])
@pytest.mark.parametrize('error', [state.StateUnavailable, RuntimeError])
def test_fail_closed(monkeypatch, target, error):
    e, _ = demo(monkeypatch, live=True)
    obj, method = target.split('.')
    monkeypatch.setattr(getattr(e, obj), method, Mock(side_effect=error(KEY + TOKEN)))
    assert call(e)[0] == 503


@pytest.mark.parametrize('variable', ['VERCEL', 'VERCEL_ENV'])
@pytest.mark.parametrize('injected', [False, True])
def test_memory_refused(monkeypatch, variable, injected):
    monkeypatch.setenv(variable, '1')
    if not injected:
        monkeypatch.setenv('DEMO_STATE', 'memory')
    e = Engine(client=Mock(), live=True, **({'cache': core.TTLCache()} if injected else {}))
    assert call(e)[0] == 503
    assert not e._client.mock_calls


def test_missing_key(monkeypatch):
    e, _ = demo(monkeypatch, live=True)
    e._client = None
    assert call(e)[0] == 503


@pytest.mark.parametrize('failure', [500, 599, OSError(), TimeoutError()])
def test_error_reservation(monkeypatch, failure):
    e, redis = demo(monkeypatch, paid=None, live=True)
    if isinstance(failure, int):
        e._client.search.return_value = (failure, None, {'cost_known': False})
    else:
        e._client.search.side_effect = failure
    code, body = call(e)
    assert code == 502 and body['cost_usd_this_request'] == .005
    assert not any(c[0] == 'SET' for c in redis.commands)
    assert sum(c[2] for c in redis.commands if c[0] == 'INCRBYFLOAT') == .005


@pytest.mark.parametrize('header,body,expected', [('.002', .5, .002), (None, .003, .003), ('NaN', .004, .004), (None, None, .005)])
def test_client_cost_reservation(monkeypatch, header, body, expected):
    e, _ = demo(monkeypatch, live=True)
    class Response(io.BytesIO):
        status = 200
        headers = {'X-Desearch-Cost-USD': header}
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **kw: Response(json.dumps({'results': [], 'cost_usd': body}).encode()))
    e._client = Client(KEY, quiet=True)
    assert call(e)[1]['cost_usd_this_request'] == expected


def test_public_config():
    page = (ROOT/'public/index.html').read_text()
    assert 'innerHTML' not in page and 'id="count"' not in page
    assert '<title>AI Search Engine | Made by Desearch</title>' in page
    assert 'overflow-wrap:anywhere' in page
    from tools.refresh_sample import BANNED
    for p in (ROOT/'public').glob('*'):
        text = p.read_text()
        assert '\u2013' not in text and '\u2014' not in text
        assert not BANNED.search(text)
    config = json.loads((ROOT/'vercel.json').read_text())
    for kind, seconds in [('search',30), ('answer',60)]:
        assert config['functions']['api/'+kind+'.py'] == dict(maxDuration=seconds, includeFiles='{searchapp/**,public/sample.json}')


def test_build_sample():
    if not (ROOT/'tests/fixtures/sample-search.json').exists():
        pytest.skip('Real capture fixtures will be supplied by the operator.')
    from tools.refresh_sample import build, dump
    assert (ROOT/'public/sample.json').read_text() == dump(build())


@pytest.mark.parametrize('kind', ['search', 'answer'])
def test_entrypoint_without_env(kind):
    spec = importlib.util.spec_from_file_location('entry_'+kind, ROOT/'api'/f'{kind}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert call(module.ENGINE, kind)[0] == 503
    request = Mock()
    request.makefile.return_value = io.BytesIO(f'GET /api/{kind}?q=test HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
    module.handler(request, ('127.0.0.1', 1234), Mock())
    assert b'503' in b''.join(c.args[0] for c in request.sendall.call_args_list)


def test_ip_order():
    assert client_ip({'X-Vercel-Forwarded-For': '1.2.3.4, 5.6.7.8', 'X-Forwarded-For':'9.9.9.9'}) == '1.2.3.4'


def test_reflected_secrets_redacted(monkeypatch):
    e, _ = demo(monkeypatch, live=True)
    monkeypatch.setenv('DESEARCH_API_KEY', KEY)
    monkeypatch.setenv('KV_REST_API_TOKEN', TOKEN)
    monkeypatch.setenv('KV_REST_API_URL', 'https://private-state.test')
    e._client.search.return_value = (200, {'results': [{'url': 'https://example.org', 'title': KEY + TOKEN + 'https://private-state.test'}]}, {'cost': .005})
    code, body = call(e)
    assert code == 200 and 'https://private-state.test' not in json.dumps(body)


def test_cli_counts_and_json(monkeypatch, tmp_path):
    import app
    from test_core import FakeClient
    monkeypatch.setenv('DESEARCH_API_KEY', KEY)
    monkeypatch.setattr(app, 'Client', lambda *a, **kw: FakeClient())
    target = tmp_path/'result.json'
    assert app.main(['--cli', 'rate limiting', '--count', '20', '--answer', '--json', str(target)]) == 0
    data = json.loads(target.read_text())
    assert data['search']['count'] == 20 and 'links' in data['answer']


def test_sample_tool_capture_build(monkeypatch, tmp_path, capsys):
    from tools import refresh_sample as tool
    monkeypatch.setattr(tool, 'ROOT', tmp_path)
    monkeypatch.setenv('DESEARCH_API_KEY', KEY)
    client = Mock()
    client.search.return_value = (200, {'results': [{'url': 'https://example.org', 'title': 'Title\u2014with\u2013hyphens', 'highlights':['A passage']}]}, {'cost': .005, 'cost_known': True, 'latency_s': .1})
    client.ai_search.return_value = (200, {'search': [], 'completion': ''}, {'cost': .004, 'cost_known': True, 'latency_s': .2})
    monkeypatch.setattr(tool, 'Client', lambda key, **kw: client)
    assert tool.main(['capture', 'sample query', '--range', 'year']) == 0
    client.search.assert_called_once()
    client.ai_search.assert_called_once_with(core.answer_body('sample query'))
    payload = client.search.call_args.args[0]
    assert payload['mode'] == 'fast' and payload['count'] == 10 and payload['highlights'] is True
    assert payload['start_date'] == core.date_window('year')[0]
    for path in (tmp_path/'tests/fixtures').glob('*.json'):
        assert KEY not in path.read_text() and 'Authorization' not in path.read_text()
    (tmp_path/'public').mkdir()
    capsys.readouterr()
    assert tool.main(['build']) == 0
    output = capsys.readouterr().out.splitlines()
    assert len(output) == 1 and 'Built saved sample: sample query | 1 results' in output[0]
    first = (tmp_path/'public/sample.json').read_bytes()
    assert tool.main(['build']) == 0
    assert first == (tmp_path/'public/sample.json').read_bytes()
    sample = json.loads(first)
    assert sample['sample'] and sample['search']['results'][0]['title'] == 'Title-with-hyphens'
    assert (tmp_path/'samples/sample-query.json').read_bytes() == first


def test_capture_key_refusal(monkeypatch, tmp_path):
    from tools import refresh_sample as tool
    monkeypatch.setattr(tool, 'ROOT', tmp_path)
    monkeypatch.setenv('DESEARCH_API_KEY', KEY)
    client = Mock()
    client.search.return_value = (200, {'secret': KEY}, {'cost': 0, 'cost_known': True, 'latency_s': 0})
    monkeypatch.setattr(tool, 'Client', lambda *a, **kw: client)
    assert tool.main(['capture', 'sample query']) == 1
    assert not list(tmp_path.rglob('*.json'))


@pytest.mark.parametrize('name', ['perplexity','tavily','exa','serpapi','serper','brave','bing','google','firecrawl','jina','apify','kagi','you.com','scrapingdog','chatgpt','openai'])
def test_sample_banned_field(name):
    from tools.refresh_sample import normalize
    with pytest.raises(ValueError, match=r'\$\.search\[0\]\.title'):
        normalize({'search': [{'title': name.upper()}]})


def test_js_syntax():
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('node unavailable')
    page = (ROOT/'public/index.html').read_text()
    script = re.search(r'<script>(.*?)</script>', page, re.S)[1]
    subprocess.run([node, '--check'], input=script, text=True, check=True, capture_output=True)


def test_search_exhausts_answer_budget(monkeypatch):
    e, _ = demo(monkeypatch, paid=1, live=True)
    assert call(e)[0] == 200
    assert call(e, 'answer')[0] == 503
    e._client.ai_search.assert_not_called()
    e.live = False
    assert call(e)[1]['cached'] is True


def test_handlers_silent(monkeypatch, capsys):
    import importlib.util
    for kind in ('search', 'answer'):
        spec = importlib.util.spec_from_file_location('silent_'+kind, ROOT/'api'/f'{kind}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        request = Mock()
        request.makefile.return_value = io.BytesIO(f'GET /api/{kind}?q=test HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
        module.handler(request, ('127.0.0.1', 1234), Mock())
    assert capsys.readouterr().err == ''


def test_tracked_text_has_no_long_dashes():
    import subprocess
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', '.'], cwd=ROOT)
    offending = []
    for name in tracked.decode().split('\0'):
        if not name or name.startswith('tests/fixtures/'):
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        if any(char in text for char in ('\u2014', '\u2013')):
            offending.append(name)
    assert not offending, offending


def test_samples_contains_only_fixture_build():
    from tools.refresh_sample import build, dump
    sample = build()
    slug = re.sub(r'[^a-z0-9]+', '-', sample['search']['query'].lower()).strip('-')
    expected = ROOT / 'samples' / (slug + '.json')
    assert list((ROOT / 'samples').iterdir()) == [expected]
    assert expected.read_text() == dump(sample)
