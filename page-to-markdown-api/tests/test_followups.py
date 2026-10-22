from itertools import product

import pytest

from pagemd.guards import DailyCap, RateLimiter, TTLCache
from pagemd.service import Converter, client_ip
from test_demo import FakeClient, dns, response


@pytest.mark.parametrize('present', list(product((False, True), repeat=3)))
@pytest.mark.parametrize('case', [str.lower, str.upper, str.title])
def test_client_ip_precedence(present, case):
    names = ('x-vercel-forwarded-for', 'x-forwarded-for', 'x-real-ip')
    values = ('  vercel  , proxy ', '  forwarded  , proxy ', '  real  ')
    headers = {case(name): value for name, value, enabled in zip(names, values, present) if enabled}
    expected = next((value.split(',')[0].strip() for value, enabled in zip(values, present) if enabled), 'fallback')
    assert client_ip(headers, '  fallback  ') == expected


@pytest.mark.parametrize('empty', ['', '   ', '\t'])
@pytest.mark.parametrize('winner', range(4))
def test_client_ip_empty_headers(empty, winner):
    names = ('x-vercel-forwarded-for', 'x-forwarded-for', 'x-real-ip')
    headers = {name: empty for name in names}
    if winner < 3:
        headers[names[winner]] = ' chosen '
    assert client_ip(headers, ' fallback ') == ('chosen' if winner < 3 else 'fallback')
    assert client_ip({}) == ''


def test_client_ip_only_uses_leftmost_forwarded_entry():
    assert client_ip({'x-vercel-forwarded-for': ' , later',
                      'x-forwarded-for': ' , later', 'X-Real-IP': ' real '}) == 'real'


@pytest.mark.parametrize('variable,vercel', [('VERCEL', v) for v in ['1', '0', 'false', ' ']] + [('VERCEL_ENV', 'preview')])
def test_vercel_refuses_memory(monkeypatch, variable, vercel):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    monkeypatch.setenv(variable, vercel)
    c = Converter(client=FakeClient(), resolver=dns, live=True)
    for _ in range(7):
        status, body = response(c)
        assert status == 503 and body['status'] == 'paused'
        assert body['markdown'] == c.sample['markdown']
        assert body['sample'] == '/sample.json'
        assert body['cost_usd_this_request'] == 0
    assert c._client.calls == 0


@pytest.mark.parametrize('vercel', [None, ''])
def test_memory_without_vercel(monkeypatch, vercel):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    monkeypatch.delenv('VERCEL', raising=False)
    if vercel is not None:
        monkeypatch.setenv('VERCEL', vercel)
    c = Converter(client=FakeClient(), resolver=dns, live=True)
    assert response(c)[0] == 200
    assert c._client.calls == 1


@pytest.mark.parametrize('name,factory', [('limiter', RateLimiter), ('cap', lambda: DailyCap(1)), ('cache', TTLCache)])
def test_injected_state_still_works_on_vercel(monkeypatch, name, factory):
    monkeypatch.setenv('DEMO_STATE', 'memory')
    monkeypatch.setenv('VERCEL', '1')
    injected = factory()
    c = Converter(client=FakeClient(), resolver=dns, live=True, **{name: injected})
    assert getattr(c, name) is injected
    assert response(c)[0] == 200
    assert c._client.calls == 1
