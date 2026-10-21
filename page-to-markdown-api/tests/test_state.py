import io
import json
import urllib.error
from unittest.mock import Mock

import pytest
from pagemd import state
from pagemd.service import Converter
from test_demo import FakeClient, dns, response


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


@pytest.fixture
def shared(monkeypatch):
    redis = FakeRedis()
    monkeypatch.delenv('DEMO_STATE', raising=False)
    monkeypatch.setattr(state, 'RedisREST', lambda: redis)
    return redis


def instances():
    return [Converter(client=FakeClient(rec={'cost': .5, 'cost_known': True}), resolver=dns, live=True)
            for _ in range(2)]


def test_shared_ip_limit(shared):
    a, b = instances()
    for i in range(5):
        assert response((a, b)[i % 2], 'invalid', ip='private-ip')[0] == 400
    assert response(b, ip='private-ip')[0] == 429
    assert a._client.calls == b._client.calls == 0
    assert len(shared.commands) == 6
    assert 'private-ip' not in json.dumps(shared.commands)


def test_shared_global_limit(shared, monkeypatch):
    monkeypatch.setenv('DEMO_GLOBAL_10MIN', '2')
    a, b = instances()
    assert response(a, 'invalid', ip='a')[0] == 400
    assert response(b, 'invalid', ip='b')[0] == 400
    assert response(a, ip='c')[0] == 429


def test_shared_daily_ip_limit(shared, monkeypatch):
    monkeypatch.setenv('DEMO_PER_IP_DAY', '1')
    a, b = instances()
    assert response(a, 'invalid')[0] == 400
    assert response(b)[0] == 429


def test_shared_cap(shared, monkeypatch):
    monkeypatch.setenv('DEMO_DAILY_CAP_USD', '.5')
    a, b = instances()
    assert response(a)[0] == 200
    code, body = response(b, 'https://example.com/another')
    assert code == 503 and body['status'] == 'paused' and b._client.calls == 0
    assert any(key.startswith('p2m:spend:') and ttl == 172800 for key, ttl in shared.expires.items())


def test_shared_cache(shared):
    a, b = instances()
    assert response(a)[0] == 200
    code, body = response(b)
    assert code == 200 and body['cached'] and body['cost_usd_this_request'] == 0
    assert b._client.calls == 0
    assert any(key.startswith('p2m:cache:') and ttl == 21600 for key, ttl in shared.expires.items())


def clear_config(monkeypatch):
    for key in ('DEMO_STATE', 'UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN',
                'KV_REST_API_URL', 'KV_REST_API_TOKEN'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('DEMO_LIVE', '1')


def assert_paused(c):
    code, body = response(c)
    assert code == 503 and body['status'] == 'paused'
    assert body['markdown'] == c.sample['markdown']
    assert 'secret-token' not in json.dumps(body) and 'redis.example' not in json.dumps(body)
    assert c._client.calls == 0


def test_unconfigured(monkeypatch):
    clear_config(monkeypatch)
    assert_paused(Converter(client=FakeClient(), resolver=dns))


@pytest.mark.parametrize('failure', ['unreachable', '500', '401', 'error', 'non200', 'badjson'])
def test_redis_failure(monkeypatch, failure):
    clear_config(monkeypatch)
    monkeypatch.setenv('KV_REST_API_URL', 'https://redis.example')
    monkeypatch.setenv('KV_REST_API_TOKEN', 'secret-token')
    opener = Mock()
    if failure == 'unreachable':
        opener.side_effect = urllib.error.URLError('secret-token')
    elif failure in ('500', '401'):
        opener.side_effect = urllib.error.HTTPError('https://redis.example', int(failure), 'secret-token', {}, io.BytesIO())
    else:
        reply = Mock(status=503 if failure == 'non200' else 200)
        reply.read.return_value = b'bad' if failure == 'badjson' else b'[{"error":"secret-token"}]'
        reply.__enter__ = Mock(return_value=reply)
        reply.__exit__ = Mock(return_value=False)
        opener.return_value = reply
    monkeypatch.setattr(state.urllib.request, 'urlopen', opener)
    assert_paused(Converter(client=FakeClient(), resolver=dns))
    opener.assert_called_once()
    request = opener.call_args.args[0]
    assert request.full_url == 'https://redis.example/pipeline'
    assert request.get_method() == 'POST'
    assert request.get_header('Authorization') == 'Bearer secret-token'
    assert opener.call_args.kwargs == {'timeout': 3}
    assert len(json.loads(request.data)) == 6


def test_memory_opt_in(monkeypatch):
    clear_config(monkeypatch)
    monkeypatch.setenv('DEMO_STATE', 'memory')
    c = Converter(client=FakeClient(), resolver=dns)
    assert response(c)[0] == 200 and c._client.calls == 1


def test_rest_success(monkeypatch):
    reply = Mock(status=200)
    reply.read.return_value = b'[{"result":"OK"}]'
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(state.urllib.request, 'urlopen', Mock(return_value=reply))
    assert state.RedisREST('https://redis.example/', 'secret-token').pipeline([['SET', 'key', 'value']]) == ['OK']


@pytest.mark.parametrize('stage', ['cache', 'cap'])
def test_read_failure_before_paid_call(shared, stage):
    original = shared.pipeline

    def pipeline(commands):
        if commands[0][0] == 'GET' and f':{stage if stage == "cache" else "spend"}:' in commands[0][1]:
            raise state.StateUnavailable()
        return original(commands)

    shared.pipeline = pipeline
    assert_paused(instances()[0])


def test_spend_utc_rollover_and_cache_keys(shared):
    clock = [0]
    cap = state.DailyCap(shared, .5, clock=lambda: clock[0])
    cap.add(.5)
    assert not cap.ok()
    clock[0] = 86400
    assert cap.ok()
    cache = state.Cache(shared)
    cache.put('https://example.com/private-query', {'markdown': 'hello'})
    assert cache.get('https://example.com/private-query') == {'markdown': 'hello'}
    assert all('private-query' not in key for key in shared.values)
