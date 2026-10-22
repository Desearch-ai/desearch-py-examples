import hashlib
import json

import pytest

from newsboard import core, state
from newsboard.service import Board
from test_service import FakeClient
from test_state import FakeRedis


@pytest.mark.parametrize('value,expected', [
    ('2a09:bac5:38a0:2828::1', '2a09:bac5:38a0:2828::/64'),
    ('2a09:bac5:38a0:2828:ffff:ffff:ffff:ffff', '2a09:bac5:38a0:2828::/64'),
    ('2a09:bac5:38a0:2829::1', '2a09:bac5:38a0:2829::/64'),
    ('1.2.3.4', '1.2.3.4'),
    ('1.2.3.5', '1.2.3.5'),
    ('::ffff:1.2.3.4', '1.2.3.4'),
    (' \t::ffff:102:304\n', '1.2.3.4'),
    (' 1.2.3.4 ', '1.2.3.4'),
    (' 2a09:bac5:38a0:2828::1 ', '2a09:bac5:38a0:2828::/64'),
])
def test_ip_bucket(value, expected):
    assert state.ip_bucket(value) == expected


INVALID = [None, '', '  ', 'unknown', 'garbage', '1.2.3.4:80',
           '[::1]', '[::1]:80', '999.2.3.4', '1.2.3', '::gg', '::/64']


@pytest.mark.parametrize('value', INVALID)
def test_invalid_bucket(value):
    assert state.ip_bucket(value) == 'invalid'


@pytest.mark.parametrize('backend', ['redis', 'memory'])
@pytest.mark.parametrize('addresses,separate', [
    (['2a09:bac5:38a0:2828::1', '2a09:bac5:38a0:2828::abcd'],
     '2a09:bac5:38a0:2829::1'),
    (['1.2.3.4', ' ::ffff:1.2.3.4 '], '1.2.3.5'),
    (INVALID, '1.2.3.4'),
])
def test_per_ip_limit(backend, addresses, separate):
    redis = FakeRedis()
    limiter = (state.Limiter(redis, clock=lambda: 0) if backend == 'redis'
               else core.RateLimiter(clock=lambda: 0))
    board = Board(client=FakeClient(status=500), limiter=limiter)
    for i in range(5):
        assert board.handle({}, addresses[i % len(addresses)])[0] == 502
    assert board.handle({}, addresses[1])[0] == 429
    assert board.handle({}, separate)[0] == 502
    if backend == 'redis':
        digest = hashlib.sha256(json.dumps(state.ip_bucket(addresses[0])).encode()).hexdigest()
        assert f'news:limit:ip:{digest}:short:0' in redis.data
        assert all(key == 'news:limit:global:0' or
                   (len(key.split(':')[3]) == 64 and
                    all(c in '0123456789abcdef' for c in key.split(':')[3]))
                   for key in redis.data)
