import sys
import socket
from pathlib import Path
import urllib.request
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for name in ('DESEARCH_API_KEY', 'VERCEL', 'VERCEL_ENV', 'DEMO_STATE', 'DEMO_LIVE',
                 'DEMO_PER_IP_10MIN', 'DEMO_PER_IP_DAY', 'DEMO_GLOBAL_10MIN',
                 'DEMO_DAILY_CAP_USD', 'DEMO_FALLBACK_COST_USD',
                 'UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN',
                 'KV_REST_API_URL', 'KV_REST_API_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    def blocked(*args, **kwargs):
        raise AssertionError('Real HTTP is forbidden in offline tests')
    monkeypatch.setattr(urllib.request, 'urlopen', blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
