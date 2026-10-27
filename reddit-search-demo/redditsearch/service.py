"""Validated Reddit search with shared cache, paid limits and fail-closed spend accounting."""
import json
import re
import unicodedata
import math
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from . import state
from .client import Client
from .threads import build_query, shape_threads
from .guards import DailyCap, RateLimiter, TTLCache


def env_float(name, default):
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) and value >= 0 else default
    except ValueError:
        return default


def validate(query):
    value = query.get('topic', '')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Type a topic to search Reddit.')
    value = ' '.join(value.split())
    if any(unicodedata.category(c) == 'Cc' for c in value) or re.search('site:', value, re.I):
        raise ValueError('Type plain words, without search operators.')
    if len(value) > 200:
        raise ValueError('Use 200 characters or fewer.')
    return value


class Search:
    def __init__(self, client=None, limiter=None, cap=None, cache=None, live=None):
        self._client = client
        injected = any(v is not None for v in (limiter, cap, cache))
        memory_requested = os.getenv('DEMO_STATE') == 'memory'
        self.refused = memory_requested and bool(os.getenv('VERCEL') or os.getenv('VERCEL_ENV'))
        memory = injected or (memory_requested and not self.refused)
        redis = state.RedisREST() if not memory else None
        self.limits = dict(per_ip=int(env_float('DEMO_PER_IP_10MIN', 5)),
            per_ip_day=int(env_float('DEMO_PER_IP_DAY', 15)),
            global_window=int(env_float('DEMO_GLOBAL_10MIN', 30)))
        self.limiter = limiter if limiter is not None else (RateLimiter(**self.limits) if memory else state.Limiter(redis, **self.limits))
        budget = env_float('DEMO_DAILY_CAP_USD', 1)
        self.cap = cap if cap is not None else (DailyCap(budget) if memory else state.DailyCap(redis, budget))
        self.cache = cache if cache is not None else (TTLCache() if memory else state.Cache(redis))
        self.live = live
        self.fallback_cost = env_float('DEMO_FALLBACK_COST_USD', .001)
        self.lock = threading.Lock()
        self.sample = json.loads((Path(__file__).resolve().parents[1] / 'public/sample.json').read_text())

    def out(self, code, body, cost=0):
        return code, {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff', 'X-Desearch-Cost-Usd': str(cost)}, json.dumps({
                **body, 'cost_usd_this_request': cost, 'limits': self.limits}, allow_nan=False)

    def paused(self, cost=0):
        return self.out(503, {**self.sample, 'status': 'paused', 'cached': False,
            'error': 'The live demo is paused. View the saved sample.', 'sample_url': '/sample.json'}, cost)

    def handle(self, query, ip):
        # Invalid requests must not touch Redis, cache, limits or upstream.
        try:
            topic = validate(query)
        except ValueError as error:
            return self.out(400, {'status': 'invalid', 'error': str(error)})
        with self.lock:
            try:
                return self._handle(topic, ip)
            except Exception:
                return self.paused()

    def _handle(self, topic, ip):
        key = topic.lower()
        if self.refused:
            return self.paused()
        hit = self.cache.get(key)
        if hit is not None:
            return self.out(200, {**hit, 'cached': True})
        live = self.live if self.live is not None else os.getenv('DEMO_LIVE', '') == '1'
        if not live or not self.cap.ok():
            return self.paused()
        try:
            client = self._client or Client(os.getenv('DESEARCH_API_KEY', '').strip())
        except RuntimeError:
            return self.paused()
        if not self.limiter.allow(ip):
            return self.out(429, {'status': 'limited', 'error': 'Too many requests. Try again later.'})
        self.cap.add(self.fallback_cost)
        query = build_query(topic)
        try:
            status, rows, paid = client.search(query)
        except (OSError, TimeoutError):
            status, rows, paid = 599, None, None
        cost = paid if paid is not None else self.fallback_cost
        if cost != self.fallback_cost:
            self.cap.add(cost - self.fallback_cost)
        if status != 200 or not isinstance(rows, list):
            return self.out(502, {'status': 'error',
                'error': 'Desearch could not search Reddit right now. Try again in a minute.'}, cost)
        threads = shape_threads(rows)
        result = {'status': 'ok' if threads else 'empty', 'sample': False, 'topic': topic,
            'query': query, 'source': 'Desearch web search, limited to reddit.com',
            'threads': threads, 'count': len(threads), 'calls': {'web_search': 1}, 'cached': False}
        if not threads:
            result['message'] = 'No public Reddit threads came back for this topic. Try other words.'
        self.cache.put(key, result)
        return self.out(200, result, cost)



def client_ip(headers, fallback=''):
    headers = {key.lower(): value for key, value in headers.items()}
    for name in ('x-vercel-forwarded-for', 'x-forwarded-for', 'x-real-ip'):
        value = headers.get(name) or ''
        if name != 'x-real-ip':
            value = value.split(',')[0]
        if value.strip():
            return value.strip()
    return fallback.strip()


def parse_query(path):
    return {k: v[0] for k, v in parse_qs(urlsplit(path).query, keep_blank_values=True).items()}
