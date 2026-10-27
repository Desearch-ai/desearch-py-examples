"""Shared, fail-closed hosted search and answer service; direct methods also support the CLI."""
import json
import math
import os
from pathlib import Path
import threading
import urllib.parse
from . import core, state
from .client import Client

CACHE_HEADER = NO_STORE = 'no-store'


def env_float(name, default):
    try:
        value = float(os.getenv(name, default))
        return value if math.isfinite(value) and value >= 0 else default
    except ValueError:
        return default


def shape_search(q, body, mode='fast', count=10, start=None, end=None, cost=0, latency=0):
    results, stats = core.clean_results(body, start, end)
    return dict(query=q, mode=mode, count=count, start_date=start, end_date=end,
                results=results, stats=stats, cost_usd=cost, latency_s=latency)


def shape_answer(q, body, search_urls=None, cost=0, latency=0):
    return dict(core.build_answer(q, body, search_urls), cost_usd=cost, latency_s=latency)


class Engine:
    def __init__(self, client=None, limiter=None, cap=None, cache=None, live=None):
        self._client, self.live = client, live
        memory = os.getenv('DEMO_STATE') == 'memory' or any(x is not None for x in (limiter, cap, cache))
        self.refused = memory and bool(os.getenv('VERCEL') or os.getenv('VERCEL_ENV'))
        redis = state.RedisREST()
        self.limits = dict(per_ip=int(env_float('DEMO_PER_IP_10MIN', 5)),
                          per_ip_day=int(env_float('DEMO_PER_IP_DAY', 15)),
                          global_window=int(env_float('DEMO_GLOBAL_10MIN', 30)))
        self.limiter = limiter if limiter is not None else (core.RateLimiter(**self.limits) if memory else state.Limiter(redis, **self.limits))
        budget = env_float('DEMO_DAILY_CAP_USD', 1)
        self.cap = cap if cap is not None else (core.DailyCap(budget) if memory else state.DailyCap(redis, budget))
        self.cache = cache if cache is not None else (core.TTLCache(ttl=900) if memory else state.Cache(redis))
        self.fallback_cost = env_float('DEMO_FALLBACK_COST_USD', .005)
        self.lock = threading.Lock()
        self.sample = json.loads((Path(__file__).resolve().parents[1] / 'public/sample.json').read_text())

    def client(self):
        if self._client is None:
            self._client = Client(os.getenv('DESEARCH_API_KEY', '').strip(), quiet=True)
        return self._client

    def cap_cost(self, status, rec):
        value = rec.get('cost') if rec.get('cost_known', True) else None
        return value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else self.fallback_cost

    def search(self, q, mode='fast', count=10, start=None, end=None):
        st, body, rec = self.client().search(core.search_body(q, mode, count, start, end), 'search')
        return st, shape_search(q, body, mode, count, start, end, rec.get('cost', 0), rec.get('latency_s', 0)) if st == 200 and isinstance(body, dict) else None, rec

    def answer(self, q, search_urls=None):
        st, body, rec = self.client().ai_search(core.answer_body(q), 'answer')
        return st, shape_answer(q, body, search_urls, rec.get('cost', 0), rec.get('latency_s', 0)) if st == 200 and isinstance(body, dict) else None, rec

    def redact(self, value):
        secrets = [os.getenv(name, '') for name in (
            'DESEARCH_API_KEY', 'KV_REST_API_URL', 'KV_REST_API_TOKEN',
            'UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN')]
        secrets.append(getattr(self._client, 'key', ''))
        if isinstance(value, str):
            for secret in secrets:
                if isinstance(secret, str) and secret:
                    value = value.replace(secret, '[redacted]')
            return value
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    def out(self, code, body, cost=0):
        return code, {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': NO_STORE,
                      'X-Content-Type-Options': 'nosniff', 'X-Desearch-Cost-Usd': str(cost)}, json.dumps(
            self.redact({'cached': False, **body, 'cost_usd_this_request': cost, 'limits': self.limits}), allow_nan=False)

    def paused(self, cost=0):
        return self.out(503, {**self.sample, 'sample': True, 'status': 'paused', 'cached': False,
            'error': 'The live demo is paused. View the saved sample.', 'sample_url': '/sample.json'}, cost)

    def handle_search(self, query, ip):
        return self.handle('search', query, ip)

    def handle_answer(self, query, ip):
        return self.handle('answer', query, ip)

    def handle(self, kind, query, ip):
        try:
            if not isinstance(query.get('q'), str):
                raise core.FormError('Type something to search for.')
            q = core.clean_query(query.get('q'))
            args = ()
            if kind == 'search':
                if 'count' in query and str(query['count']) != '10':
                    raise core.FormError('The live demo returns 10 results.')
                mode = core.parse_mode(query.get('mode'))
                start, end = core.date_window(query.get('range'), query.get('from'), query.get('to'))
                args = (mode, 10, start, end)
        except (core.FormError, ValueError) as error:
            return self.out(400, {'status': 'invalid', 'error': str(error)})
        except Exception:
            return self.paused()
        cost = 0
        with self.lock:
            try:
                key = core.cache_key(kind, q=q, options=args)
                hit = self.cache.get(key)
                if hit is not None:
                    return self.out(200, {**hit, 'cached': True})
                live = self.live if self.live is not None else os.getenv('DEMO_LIVE') == '1'
                if self.refused or not live or not self.cap.ok():
                    return self.paused()
                try:
                    self.client()
                except RuntimeError:
                    return self.paused()
                if not self.limiter.allow(ip):
                    return self.out(429, {'status': 'limited', 'error': 'Too many requests. Try again later.'})
                self.cap.add(self.fallback_cost)
                cost = self.fallback_cost
                try:
                    st, result, rec = getattr(self, kind)(q, *args)
                except (OSError, TimeoutError):
                    st, result, rec = 599, None, {'cost_known': False}
                actual = self.cap_cost(st, rec)
                if actual != cost:
                    self.cap.add(actual - cost)
                cost = actual
                if st != 200 or result is None:
                    return self.out(502, {'status': 'error', 'error': 'Desearch could not complete this request. Try again later.'}, cost)
                result.update(status='ok' if result.get('results', result.get('links')) else 'empty', sample=False, cached=False)
                self.cache.put(key, result)
                return self.out(200, result, cost)
            except Exception:
                return self.paused(cost)


def client_ip(headers, fallback=''):
    headers = {k.lower(): v for k, v in headers.items()}
    for name in ('x-vercel-forwarded-for', 'x-forwarded-for', 'x-real-ip'):
        value = headers.get(name) or ''
        if name != 'x-real-ip':
            value = value.split(',')[0]
        if value.strip():
            return value.strip()
    return fallback.strip()


def parse_query(path):
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(path).query, keep_blank_values=True).items()}
