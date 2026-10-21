import datetime as dt
import itertools
import json
from unittest.mock import Mock

import pytest

from newsboard.core import DailyCap, RateLimiter, TTLCache
from newsboard.service import Board, client_ip


@pytest.mark.parametrize('present', list(itertools.product([False, True], repeat=3)))
@pytest.mark.parametrize('case', [str.lower, str.upper, str.title])
def test_client_ip_precedence(present, case):
    names = ['x-vercel-forwarded-for', 'x-forwarded-for', 'x-real-ip']
    values = ['  vercel , ignored ', ' forwarded , ignored ', ' real ']
    headers = {case(name): value for name, value, use in zip(names, values, present) if use}
    expected = next((value.strip().split(',')[0].strip()
                     for value, use in zip(values, present) if use), 'fallback')
    assert client_ip(headers, ' fallback ') == expected


@pytest.mark.parametrize('empty', ['', '   ', ' , ignored'])
def test_client_ip_empty_forwarded_headers(empty):
    assert client_ip({'X-Vercel-Forwarded-For': empty,
                      'X-Forwarded-For': empty, 'X-Real-IP': '  '}, ' fallback ') == 'fallback'
    assert client_ip({'X-Vercel-Forwarded-For': empty,
                      'X-Forwarded-For': ' forwarded, ignored'}) == 'forwarded'
    assert client_ip({'X-Vercel-Forwarded-For': empty,
                      'X-Forwarded-For': empty, 'X-Real-IP': ' real '}) == 'real'
    assert client_ip({}) == ''


def response(board, query=None, ip='192.0.2.1'):
    status, headers, body = board.handle(query or {}, ip)
    return status, headers, json.loads(body)


@pytest.mark.parametrize('vercel', ['1', '0', 'false', ' '])
def test_vercel_refuses_memory(monkeypatch, vercel):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    monkeypatch.setenv('VERCEL', vercel)
    client = Mock()
    board = Board(client=client, live=True)
    # Even available shared state and a cache hit must not enable this configuration.
    board.limiter = Mock(allow=Mock(return_value=True))
    board.cache = Mock()
    status, headers, body = response(board)
    assert status == 503
    assert body == {'status': 'paused', 'error': 'The live demo is paused. See the saved sample run.',
                    'sample': '/sample.json'}
    assert headers['Cache-Control'] == 'no-store'
    board.limiter.allow.assert_called_once_with('192.0.2.1')
    board.cache.get.assert_not_called()
    assert client.mock_calls == []


@pytest.mark.parametrize('vercel', [None, ''])
def test_local_memory_works(monkeypatch, vercel):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    if vercel is None:
        monkeypatch.delenv('VERCEL', raising=False)
    else:
        monkeypatch.setenv('VERCEL', vercel)
    client = Mock()
    client.x_search.return_value = client.ai_search.return_value = (200, [], {'cost': 0})
    assert response(Board(client=client, live=True))[0] == 200
    assert len(client.mock_calls) == 10


@pytest.mark.parametrize('store', ['limiter', 'cap', 'cache'])
def test_injected_stores_work_on_vercel(monkeypatch, store):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    monkeypatch.setenv('VERCEL', '1')
    stores = {'limiter': RateLimiter(), 'cap': DailyCap(), 'cache': TTLCache()}
    board = Board(**{store: stores[store]}, live=False)
    assert getattr(board, store) is stores[store]
    assert not board.memory_refused
    assert response(board)[0] == 503


@pytest.mark.parametrize('mode,expected', [('cached', 200), ('paused', 503), ('invalid', 400), ('cap', 503)])
@pytest.mark.parametrize('global_limit', [False, True])
def test_every_request_counts(monkeypatch, mode, expected, global_limit):
    monkeypatch.delenv('VERCEL', raising=False)
    limiter = RateLimiter(per_ip=100 if global_limit else 5, global_window=5 if global_limit else 100)
    client = Mock()
    board = Board(client=client, limiter=limiter, live=False,
                  cap=DailyCap(0 if mode == 'cap' else 1))
    if mode == 'cached':
        utc = dt.datetime.now(dt.timezone.utc)
        board.cache.put((utc.date().isoformat(), utc.hour // 6), {'cost_usd': 0})
    if mode == 'cap':
        board.live = True
    query = {'unexpected': ''} if mode == 'invalid' else {}
    for i in range(6):
        ip = f'192.0.2.{i + 1}' if global_limit else '192.0.2.1'
        status, headers, body = response(board, query, ip)
        assert status == (expected if i < 5 else 429)
        if i == 5:
            assert body == {'error': 'Too many requests from your network. Try again in a few minutes.'}
            assert headers['Cache-Control'] == 'no-store'
    assert client.mock_calls == []
