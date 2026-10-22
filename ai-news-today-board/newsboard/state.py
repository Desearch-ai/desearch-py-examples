"""Shared demo state through the Upstash Redis REST pipeline API."""
import hashlib
import ipaddress
import json
import os
import time
import urllib.error
import urllib.request


class StateUnavailable(Exception):
    """Shared state could not be checked safely."""


class RedisREST:
    def __init__(self, url=None, token=None):
        self.url = url or os.environ.get('UPSTASH_REDIS_REST_URL') or os.environ.get('KV_REST_API_URL')
        self.token = token or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or os.environ.get('KV_REST_API_TOKEN')

    def pipeline(self, commands):
        if not self.url or not self.token:
            raise StateUnavailable('Shared state unavailable')
        try:
            request = urllib.request.Request(
                self.url.rstrip('/') + '/pipeline', data=json.dumps(commands).encode(),
                headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
                method='POST')
            with urllib.request.urlopen(request, timeout=3) as response:
                if response.status != 200:
                    raise ValueError('Unexpected status')
                results = json.loads(response.read())
            if not isinstance(results, list) or len(results) != len(commands):
                raise ValueError('Invalid pipeline response')
            if any(not isinstance(item, dict) or 'error' in item or 'result' not in item for item in results):
                raise ValueError('Invalid command response')
            return [item['result'] for item in results]
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, TypeError):
            raise StateUnavailable('Shared state unavailable') from None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def ip_bucket(ip):
    """Group IPv6 clients by /64 and use one bucket for invalid addresses."""
    if not isinstance(ip, str):
        return 'invalid'
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return 'invalid'
    if isinstance(address, ipaddress.IPv4Address):
        return str(address)
    if address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    return str(ipaddress.IPv6Network((address, 64), strict=False))


class Limiter:
    """Fixed windows; each check increments all counters in one pipeline."""
    def __init__(self, redis, per_ip=5, window=600, per_ip_day=15, global_window=30,
                 namespace='news', clock=time.time):
        self.redis, self.namespace, self.clock = redis, namespace, clock
        self.per_ip, self.window = per_ip, window
        self.per_ip_day, self.global_window = per_ip_day, global_window

    def allow(self, ip):
        now = self.clock()
        ident = _hash(ip_bucket(ip))
        windows = [(f'ip:{ident}:short', self.window, self.per_ip),
                   (f'ip:{ident}:day', 86400, self.per_ip_day),
                   ('global', self.window, self.global_window)]
        commands = []
        for name, seconds, limit in windows:
            key = f'{self.namespace}:limit:{name}:{int(now // seconds)}'
            commands.extend([['INCR', key], ['EXPIRE', key, seconds * 2]])
        results = self.redis.pipeline(commands)
        try:
            return all(int(results[i * 2]) <= entry[2] for i, entry in enumerate(windows))
        except (TypeError, ValueError):
            raise StateUnavailable('Shared state unavailable') from None


class DailyCap:
    def __init__(self, redis, cap_usd=1.0, namespace='news', clock=time.time):
        self.redis, self.cap, self.namespace, self.clock = redis, cap_usd, namespace, clock

    def _key(self):
        return f'{self.namespace}:spend:{time.strftime("%Y-%m-%d", time.gmtime(self.clock()))}'

    @property
    def spent(self):
        result = self.redis.pipeline([['GET', self._key()]])[0]
        try:
            return float(result or 0)
        except (TypeError, ValueError):
            raise StateUnavailable('Shared state unavailable') from None

    def ok(self):
        return self.spent < self.cap

    def add(self, usd):
        key = self._key()
        self.redis.pipeline([['INCRBYFLOAT', key, float(usd or 0)], ['EXPIRE', key, 172800]])


class Cache:
    def __init__(self, redis, ttl=21600, namespace='news'):
        self.redis, self.ttl, self.namespace = redis, ttl, namespace

    def _key(self, key):
        return f'{self.namespace}:cache:{_hash(key)}'

    def get(self, key):
        value = self.redis.pipeline([['GET', self._key(key)]])[0]
        try:
            result = json.loads(value) if value is not None else None
            if result is not None and not isinstance(result, dict):
                raise ValueError('Invalid cache value')
            return result
        except (ValueError, TypeError):
            raise StateUnavailable('Shared state unavailable') from None

    def put(self, key, value):
        self.redis.pipeline([['SET', self._key(key), json.dumps(value), 'EX', self.ttl]])
