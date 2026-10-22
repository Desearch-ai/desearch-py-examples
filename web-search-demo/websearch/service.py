"""Validated search with shared cache, paid limits and fail-closed spend accounting."""
import json
import math
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from . import state
from .client import Client
from .guards import DailyCap, RateLimiter, TTLCache


def env_float(name, default):
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) and value >= 0 else default
    except ValueError:
        return default


def validate(query):
    q = query.get('q', '')
    page = query.get('page', '1')
    if not isinstance(q, str) or not 2 <= len(q.strip()) <= 200:
        raise ValueError('Query must contain 2 to 200 characters.')
    if page not in ('1', '2'):
        raise ValueError('Page must be 1 or 2.')
    return q.strip(), int(page)


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
            q, page = validate(query)
        except ValueError as error:
            return self.out(400, {'status': 'invalid', 'error': str(error)})
        with self.lock:
            try:
                return self._handle(q, page, ip)
            except state.StateUnavailable:
                return self.paused()

    def _handle(self, q, page, ip):
        if self.refused:
            return self.paused()
        key = json.dumps([' '.join(q.lower().split()), page])
        hit = self.cache.get(key)
        if hit is not None:
            return self.out(200, {**hit, 'cached': True})
        live = self.live if self.live is not None else os.getenv('DEMO_LIVE', '1').lower() in ('1', 'true')
        if not live or not self.cap.ok():
            return self.paused()
        try:
            client = self._client or Client(os.getenv('DESEARCH_API_KEY', '').strip())
        except RuntimeError:
            return self.paused()
        if not self.limiter.allow(ip):
            return self.out(429, {'status': 'limited', 'error': 'Too many searches. Try again later.'})
        try:
            status, results, cost = client.search(q, page)
        except (OSError, TimeoutError):
            status, results, cost = 599, None, None
        cost = self.fallback_cost if cost is None else cost
        self.cap.add(cost)
        if status != 200 or results is None:
            return self.paused(cost)
        result = {'status': 'ok', 'sample': False, 'query': q, 'page': page, 'results': results}
        self.cache.put(key, result)
        return self.out(200, {**result, 'cached': False}, cost)


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
