import io
import json
import threading
import urllib.error
import urllib.request
from unittest.mock import Mock

import pytest
from newsboard.client import Client, api_key
from newsboard.core import DailyCap, RateLimiter, TTLCache
from newsboard.service import Board, CACHE_HEADER, client_ip, parse_query
from ai_news_board import build_board, plan_requests


class FakeClient:
    def __init__(self, status=200, cost=0, known=False, failed_tag=None, barrier=None):
        self.status, self.cost, self.known = status, cost, known
        self.failed_tag, self.barrier = failed_tag, barrier

    def call(self, params, tag):
        if self.barrier:
            self.barrier.wait(timeout=5)
        status = 599 if tag == self.failed_tag else self.status
        return status, [], {"cost": self.cost, "cost_known": self.known}

    x_search = call
    ai_search = call


def response(board, query=None):
    status, headers, body = board.handle(query or {}, "test-ip")
    return status, headers, json.loads(body)


def test_paused():
    client = Mock()
    status, headers, body = response(Board(client=client, live=False))
    assert status == 503 and body['sample'] == '/sample.json'
    assert headers['Cache-Control'] == 'no-store'
    client.x_search.assert_not_called()


@pytest.mark.parametrize('status', [401, 402, 403])
def test_auth_pauses_and_counts_zero(status):
    board = Board(client=FakeClient(status, cost=9, known=True))
    result = response(board)
    assert result[0] == 503
    assert result[2] == response(Board(live=False))[2]
    assert board.cap.spent == 0


def test_fallback_cache_and_parallel_calls():
    board = Board(client=FakeClient(barrier=threading.Barrier(10)))
    status, headers, body = response(board)
    assert status == 200 and body['calls'] == 10
    assert body['cost_usd_this_request'] == pytest.approx(.05)
    assert board.cap.spent == pytest.approx(.05)
    assert headers['Cache-Control'] == CACHE_HEADER
    board.live = False
    hit = response(board)
    assert hit[0] == 200 and hit[2]['cached'] is True
    assert hit[2]['cost_usd_this_request'] == 0


def test_partial_and_total_failures():
    board = Board(client=FakeClient(failed_tag='model release'))
    result = response(board)
    assert result[0] == 200 and result[2]['partial'] is True
    assert result[2]['calls'] == 10
    for kind in ('x_search', 'ai_search'):
        client = FakeClient()
        setattr(client, kind, lambda *args: (500, {}, {'cost': 0, 'cost_known': False}))
        status, headers, _ = response(Board(client=client))
        assert status == 502 and headers['Cache-Control'] == 'no-store'


def test_cap_and_missing_key():
    cap = DailyCap(0)
    assert response(Board(cap=cap))[0] == 503
    status, headers, body = response(Board())
    assert status == 500 and body == {'error': 'The demo is not configured.'}
    assert headers['Cache-Control'] == 'no-store'
    with pytest.raises(RuntimeError):
        api_key()


def test_limits_through_handler():
    clock = [0]
    limiter = RateLimiter(clock=lambda: clock[0], global_window=100)
    board = Board(client=FakeClient(status=500), limiter=limiter)
    for batch in range(3):
        for _ in range(5):
            assert response(board)[0] == 502
        assert response(board)[0] == 429
        clock[0] += 601
    assert response(board)[0] == 429
    clock[0] = 86401
    assert response(board)[0] == 502


@pytest.mark.parametrize('headers,body,expected,known', [
    ({'X-Desearch-Cost-USD': '.002'}, {'cost_usd': .009}, .002, True),
    ({}, {'cost_usd': .003}, .003, True),
    ({}, {}, 0, False),
    ({'X-Desearch-Cost-USD': 'invalid'}, {'cost_usd': .004}, .004, True),
])
def test_client_cost_precedence(monkeypatch, headers, body, expected, known):
    reply = Mock(status=200, headers=headers)
    reply.read.return_value = json.dumps(body).encode()
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(urllib.request, 'urlopen', Mock(return_value=reply))
    _, _, rec = Client('test-only-placeholder').x_search({'query': 'AI'})
    assert rec == {'cost': expected, 'cost_known': known}


def test_http_auth_error_mock(monkeypatch):
    error = urllib.error.HTTPError('https://example.test', 402, 'paused', {}, io.BytesIO(b'{}'))
    monkeypatch.setattr(urllib.request, 'urlopen', Mock(side_effect=error))
    assert Client('test-only-placeholder').ai_search({})[0] == 402


def test_query_and_plan():
    assert response(Board(live=False), {'unexpected': ''})[0] == 400
    assert parse_query('/api/board?unknown=') == {'unknown': ''}
    assert client_ip({'X-Forwarded-For': 'one, two'}) == 'one'
    jobs = plan_requests()
    assert len(jobs) == 10
    assert all(params['min_likes'] == '20' for kind, _, params in jobs if kind == 'x')
    assert all('include_domains' in params for kind, _, params in jobs if kind == 'web')


def test_sample_reproducible():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root/'samples/sample-raw.json').read_text())
    expected = build_board(raw, raw['started'])
    assert json.loads((root/'public/sample.json').read_text()) == expected
