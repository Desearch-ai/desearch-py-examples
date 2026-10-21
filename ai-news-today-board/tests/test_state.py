import io
import json
import urllib.error
from unittest.mock import Mock

import pytest

from newsboard import state
from newsboard.service import Board
from test_service import FakeClient


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.expiry = {}
        self.now = 0
        self.requests = []

    def pipeline(self, commands):
        self.requests.append(commands)
        result = []
        for op, key, *args in commands:
            if self.expiry.get(key, float('inf')) <= self.now:
                self.data.pop(key, None)
            if op == 'GET':
                value = self.data.get(key)
            elif op in ('INCR', 'INCRBYFLOAT'):
                value = float(self.data.get(key, 0)) + (1 if op == 'INCR' else float(args[0]))
                self.data[key] = str(value)
                value = int(value) if op == 'INCR' else str(value)
            elif op == 'EXPIRE':
                self.expiry[key] = self.now + int(args[0])
                value = 1
            elif op == 'SET':
                self.data[key] = args[0]
                assert args[1] == 'EX'
                self.expiry[key] = self.now + int(args[2])
                value = 'OK'
            else:
                raise AssertionError(op)
            result.append(value)
        return result


def result(board, ip='private-ip'):
    status, headers, body = board.handle({}, ip)
    assert 'secret-token' not in body
    assert 'redis.example' not in body
    return status, json.loads(body)


def boards(monkeypatch, client=None):
    redis = FakeRedis()
    monkeypatch.setattr(state, 'RedisREST', lambda: redis)
    client = client or FakeClient(status=500)
    return redis, Board(client=client), Board(client=client)


def test_shared_ip_limit(monkeypatch):
    redis, a, b = boards(monkeypatch)
    for i in range(5):
        assert result((a, b)[i % 2])[0] == 502
    assert result(b)[0] == 429
    assert 'private-ip' not in json.dumps(redis.requests)
    assert all(key.startswith('news:') for key in redis.data)


def test_shared_global_limit(monkeypatch):
    monkeypatch.setenv('DEMO_GLOBAL_10MIN', '3')
    _, a, b = boards(monkeypatch)
    for i in range(3):
        assert result((a, b)[i % 2], str(i))[0] == 502
    assert result(b, 'another-ip')[0] == 429


def test_shared_day_limit(monkeypatch):
    monkeypatch.setenv('DEMO_PER_IP_DAY', '2')
    _, a, b = boards(monkeypatch)
    assert result(a)[0] == 502
    assert result(b)[0] == 502
    assert result(a)[0] == 429


def test_shared_cap(monkeypatch):
    monkeypatch.setenv('DEMO_DAILY_CAP_USD', '.5')
    redis, a, b = boards(monkeypatch, FakeClient(status=500, cost=.1, known=True))
    assert result(a)[0] == 502
    b._client = Mock()
    status, body = result(b)
    assert status == 503 and body['status'] == 'paused'
    b._client.x_search.assert_not_called()
    b._client.ai_search.assert_not_called()
    assert b.cap.spent == pytest.approx(1)
    assert any(key.startswith('news:spend:') for key in redis.data)


def test_shared_cache(monkeypatch):
    redis, a, b = boards(monkeypatch, FakeClient(cost=.01, known=True))
    assert result(a)[0] == 200
    b._client = Mock()
    status, body = result(b)
    assert status == 200 and body['cached'] is True
    assert body['cost_usd_this_request'] == 0
    b._client.x_search.assert_not_called()
    b._client.ai_search.assert_not_called()
    b.cache.put(('expiry', 0), {'saved': True})
    assert b.cache.get(('expiry', 0)) == {'saved': True}
    redis.now += 21601
    assert b.cache.get(('expiry', 0)) is None
    cache_key = next(key for key in redis.data if ':cache:' in key)
    assert redis.expiry[cache_key] == 21600


@pytest.mark.parametrize('failure', ['missing', 'unreachable', '500', '401', 'error', 'non200'])
def test_fail_closed(monkeypatch, failure, capsys):
    monkeypatch.setenv('DEMO_LIVE', '1')
    opener = Mock()
    monkeypatch.setattr(state.urllib.request, 'urlopen', opener)
    if failure != 'missing':
        monkeypatch.setenv('UPSTASH_REDIS_REST_URL', 'https://redis.example')
        monkeypatch.setenv('UPSTASH_REDIS_REST_TOKEN', 'secret-token')
        if failure == 'unreachable':
            opener.side_effect = urllib.error.URLError('secret-token')
        elif failure in ('500', '401'):
            opener.side_effect = urllib.error.HTTPError('https://redis.example', int(failure), 'secret-token', {}, io.BytesIO())
        else:
            reply = Mock(status=500 if failure == 'non200' else 200)
            reply.read.return_value = b'[{"error":"secret-token"}]'
            opener.return_value.__enter__ = Mock(return_value=reply)
            opener.return_value.__exit__ = Mock(return_value=False)
    client = Mock()
    status, body = result(Board(client=client))
    assert status == 503 and body['status'] == 'paused' and body['sample'] == '/sample.json'
    client.x_search.assert_not_called()
    client.ai_search.assert_not_called()
    assert 'secret-token' not in capsys.readouterr().err
    if failure == 'missing':
        opener.assert_not_called()


def test_memory_opt_in(monkeypatch):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    assert result(Board(client=FakeClient()))[0] == 200


def test_rest_transport_and_aliases(monkeypatch):
    monkeypatch.setenv('KV_REST_API_URL', 'https://redis.example/')
    monkeypatch.setenv('KV_REST_API_TOKEN', 'secret-token')
    reply = Mock(status=200)
    reply.read.return_value = b'[{"result":null}]'
    opener = Mock()
    opener.return_value.__enter__ = Mock(return_value=reply)
    opener.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(state.urllib.request, 'urlopen', opener)
    assert state.RedisREST().pipeline([['GET', 'news:key']]) == [None]
    request = opener.call_args.args[0]
    assert request.full_url == 'https://redis.example/pipeline'
    assert request.method == 'POST'
    assert json.loads(request.data) == [['GET', 'news:key']]
    assert request.get_header('Authorization') == 'Bearer secret-token'
    assert opener.call_args.kwargs['timeout'] == 3
