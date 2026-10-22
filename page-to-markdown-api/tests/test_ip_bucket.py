import pytest

from pagemd import state
from pagemd.guards import RateLimiter
from test_demo import FakeClient, make, response
from test_state import FakeRedis


INVALID_IPS = [None, '', '  ', 'unknown', 'garbage', '1.2.3.4:80',
               '[::1]', '[::1]:443', '2001:db8::nope', '1.2.3.999']


@pytest.mark.parametrize('ip', INVALID_IPS)
def test_invalid_bucket(ip):
    assert state.ip_bucket(ip) == 'invalid'


@pytest.mark.parametrize('ip,bucket', [
    (' 1.2.3.4 \n', '1.2.3.4'),
    ('1.2.3.5', '1.2.3.5'),
    ('::ffff:1.2.3.4', '1.2.3.4'),
    (' 2a09:bac5:38a0:2828::1 ', '2a09:bac5:38a0:2828::/64'),
    ('2a09:bac5:38a0:2828:ffff:ffff:ffff:ffff', '2a09:bac5:38a0:2828::/64'),
    ('2a09:bac5:38a0:2829::1', '2a09:bac5:38a0:2829::/64'),
])
def test_normalized_bucket(ip, bucket):
    assert state.ip_bucket(ip) == bucket


@pytest.fixture(params=['redis', 'memory'])
def converter(request):
    limiter = (state.Limiter(FakeRedis(), clock=lambda: 0)
               if request.param == 'redis' else RateLimiter(clock=lambda: 0))
    return make(FakeClient(), limiter=limiter)


@pytest.mark.parametrize('first,same,separate', [
    ('2a09:bac5:38a0:2828::1', '2a09:bac5:38a0:2828::abcd', '2a09:bac5:38a0:2829::1'),
    ('1.2.3.4', '1.2.3.4', '1.2.3.5'),
    ('1.2.3.4', '::ffff:1.2.3.4', '1.2.3.5'),
    ('unknown', '1.2.3.4:80', '1.2.3.4'),
])
def test_shared_per_ip_limit(converter, first, same, separate):
    for ip in [first, same, first, same, first]:
        assert response(converter, 'invalid', ip=ip)[0] == 400
    assert response(converter, ip=same)[0] == 429
    assert response(converter, 'invalid', ip=separate)[0] == 400


def test_redis_keys_hash_bucket():
    redis = FakeRedis()
    limiter = state.Limiter(redis, clock=lambda: 0)
    ip = '2a09:bac5:38a0:2828::1'
    assert limiter.allow(ip)
    hashed = state.digest(state.ip_bucket(ip))
    assert set(redis.values) == {
        f'p2m:limit:ip:{hashed}:10min:0',
        f'p2m:limit:ip:{hashed}:day:0',
        'p2m:limit:global:10min:0',
    }


def test_invalid_values_share_limit(converter):
    statuses = [response(converter, 'invalid', ip=ip)[0] for ip in INVALID_IPS]
    assert statuses == [400] * 5 + [429] * (len(INVALID_IPS) - 5)
