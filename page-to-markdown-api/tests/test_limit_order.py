import pytest

from pagemd.guards import RateLimiter, TTLCache
from test_demo import FakeClient, make, response


@pytest.fixture
def converter():
    clock = lambda: 0
    return make(FakeClient(), limiter=RateLimiter(clock=clock), cache=TTLCache(clock=clock))


def test_invalid_requests_limit_valid_request(converter):
    for url in ('invalid', 'http://127.0.0.1', '', 'file:///etc/passwd', 'http://localhost'):
        assert response(converter, url)[0] == 400
    status, body = response(converter)
    assert status == 429 and body['status'] == 'limited'
    assert body['markdown'] == converter.sample['markdown']
    assert converter._client.calls == 0


def test_cached_repeats_count(converter):
    assert response(converter)[0] == 200
    for _ in range(4):
        status, body = response(converter)
        assert status == 200 and body['cached']
    assert response(converter)[0] == 429
    assert converter._client.calls == 1


def test_invalid_burst_then_cached_repeat(converter):
    assert response(converter, ip='prime')[0] == 200
    statuses = [response(converter, 'invalid')[0] for _ in range(7)]
    statuses.append(response(converter)[0])
    assert statuses == [400] * 5 + [429] * 3
    assert converter._client.calls == 1


def test_another_ip_is_unaffected(converter):
    for _ in range(5):
        assert response(converter, 'invalid', ip='one')[0] == 400
    assert response(converter, ip='one')[0] == 429
    assert response(converter, ip='two')[0] == 200
    assert converter._client.calls == 1


def test_global_limit_across_ips(converter):
    for i in range(30):
        assert response(converter, 'invalid', ip=f'ip-{i}')[0] == 400
    assert response(converter, ip='new-ip')[0] == 429
    assert converter._client.calls == 0


def test_paused_requests_count(converter):
    converter.live = False
    for _ in range(5):
        assert response(converter)[0] == 503
    assert response(converter)[0] == 429
    assert converter._client.calls == 0
