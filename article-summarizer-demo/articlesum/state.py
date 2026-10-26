"""Shared demo state over the Upstash Redis REST pipeline API."""
import hashlib
import http.client
import math
import ipaddress
import json
import os
import time
import urllib.error
import urllib.request


class StateUnavailable(Exception):
    """State cannot be trusted. Never include connection details in this error."""


class RedisREST:
    def __init__(self, url=None, token=None):
        self._url = (url if url is not None else os.getenv('UPSTASH_REDIS_REST_URL') or os.getenv('KV_REST_API_URL') or '').rstrip('/')
        self._token = token if token is not None else os.getenv('UPSTASH_REDIS_REST_TOKEN') or os.getenv('KV_REST_API_TOKEN') or ''

    def pipeline(self, commands):
        if not self._url or not self._token:
            raise StateUnavailable() from None
        try:
            request = urllib.request.Request(self._url + '/pipeline', data=json.dumps(commands).encode(),
                headers={'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=3) as response:
                if response.status != 200:
                    raise StateUnavailable()
                entries = json.loads(response.read())
            if not isinstance(entries, list) or len(entries) != len(commands):
                raise StateUnavailable()
            if any(not isinstance(entry, dict) or 'error' in entry or 'result' not in entry for entry in entries):
                raise StateUnavailable()
            return [entry['result'] for entry in entries]
        except (OSError, TimeoutError, ValueError, TypeError, urllib.error.URLError, http.client.HTTPException):
            raise StateUnavailable() from None
        except Exception:
            raise StateUnavailable() from None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def ip_bucket(ip):
    """Group IPv6 clients by /64, preserving individual IPv4 addresses."""
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
    return str(ipaddress.ip_network((address, 64), strict=False))


class Limiter:
    """Fixed windows; every attempt increments all three counters in one pipeline."""
    def __init__(self, redis, per_ip=5, per_ip_day=15, global_window=30, namespace='articlesum', clock=time.time):
        self.redis, self.namespace, self.clock = redis, namespace, clock
        self.limits = (per_ip, per_ip_day, global_window)

    def allow(self, ip):
        now = int(self.clock())
        hashed = digest(ip_bucket(ip))
        commands = []
        for scope, seconds in ((f'ip:{hashed}:10min', 600), (f'ip:{hashed}:day', 86400), ('global:10min', 600)):
            key = f'{self.namespace}:limit:{scope}:{now // seconds}'
            commands.extend([['INCR', key], ['EXPIRE', key, seconds * 2]])
        results = self.redis.pipeline(commands)
        try:
            return all(int(results[i * 2]) <= limit for i, limit in enumerate(self.limits))
        except (ValueError, TypeError, IndexError):
            raise StateUnavailable() from None


class DailyCap:
    def __init__(self, redis, cap_usd=1.0, namespace='articlesum', clock=time.time):
        self.redis, self.cap, self.namespace, self.clock = redis, cap_usd, namespace, clock

    def _key(self):
        return f'{self.namespace}:spend:' + time.strftime('%Y-%m-%d', time.gmtime(self.clock()))

    def ok(self):
        value = self.redis.pipeline([['GET', self._key()]])[0]
        try:
            spent = float(value or 0)
            if not math.isfinite(spent) or spent < 0:
                raise StateUnavailable()
            return spent < self.cap
        except (ValueError, TypeError):
            raise StateUnavailable() from None

    def add(self, usd):
        key = self._key()
        self.redis.pipeline([['INCRBYFLOAT', key, float(usd or 0)], ['EXPIRE', key, 172800]])


class Cache:
    def __init__(self, redis, ttl=900, namespace='articlesum'):
        self.redis, self.ttl, self.namespace = redis, ttl, namespace

    def _key(self, url):
        return f'{self.namespace}:cache:{digest(url)}'

    def get(self, url):
        value = self.redis.pipeline([['GET', self._key(url)]])[0]
        try:
            result = json.loads(value) if value is not None else None
            if result is not None and not isinstance(result, dict):
                raise StateUnavailable()
            return result
        except (ValueError, TypeError):
            raise StateUnavailable() from None

    def put(self, url, value):
        self.redis.pipeline([['SET', self._key(url), json.dumps(value), 'EX', self.ttl]])
