"""Validated article extraction with shared cache, paid limits and fail-closed spend accounting."""
import json
import ipaddress
import math
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from . import state
from .client import Client
from .urlguard import validate_url, URLValidationError, URLUnreachableError
from .summary import word_count, is_near_empty, hide_handles, key_sentences, numbers_mentioned
from .guards import DailyCap, RateLimiter, TTLCache


def env_float(name, default):
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) and value >= 0 else default
    except ValueError:
        return default


def validate(query):
    value = query.get('url', '')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Paste a link to a public article.')
    if len(value) > 2000:
        raise ValueError('Use a full http or https link to a public page.')
    try:
        return validate_url(value)
    except URLValidationError as error:
        try:
            host = urlsplit(value).hostname
        except ValueError:
            raise ValueError('Use a full http or https link to a public page.') from None
        private = isinstance(error, URLUnreachableError)
        try:
            private = private or (host is not None and not ipaddress.ip_address(host).is_global)
        except ValueError:
            private = private or host == 'localhost' or bool(host and host.endswith(('.local', '.localhost', '.internal')))
        # DNS rejection of an otherwise valid public-looking hostname is private.
        if not private and host and '.' in host:
            try:
                validate_url(value, resolver=lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
            except URLValidationError:
                pass
            else:
                private = True
        raise ValueError('This link points to a private or unknown address.' if private else
                         'Use a full http or https link to a public page.') from None


class Summarize:
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
            url = validate(query)
        except ValueError as error:
            return self.out(400, {'status': 'invalid', 'error': str(error)})
        with self.lock:
            try:
                return self._handle(url, ip)
            except Exception:
                return self.paused()

    def _handle(self, url, ip):
        if self.refused:
            return self.paused()
        hit = self.cache.get(url)
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
        cost, unknown, calls = 0, False, 0
        for _ in range(2):
            calls += 1
            try:
                status, text, paid = client.extract(url)
            except (OSError, TimeoutError):
                status, text, paid = 599, '', None
            unknown = unknown or paid is None
            cost += paid if paid is not None else 0
            if 'No content found' not in text:
                break
        cost = max(cost, self.fallback_cost) if unknown else cost
        if cost != self.fallback_cost:
            self.cap.add(cost - self.fallback_cost)
        if status != 200 or 'No content found' in text:
            return self.out(502, {'status': 'error',
                'error': 'Desearch could not read this page right now. Try again in a minute.'}, cost)
        result = {'sample': False, 'url': url, 'domain': urlsplit(url).hostname.removeprefix('www.'),
            'words': word_count(text), 'calls': {'extract': calls}, 'cached': False}
        if is_near_empty(text):
            return self.out(200, {**result, 'status': 'near_empty',
                'preview': hide_handles(' '.join(text.split()))[:400]}, cost)
        result.update(status='ok', label='Extractive summary: key sentences quoted from the article',
            key_points=[hide_handles(s) for s in key_sentences(text, 5)],
            numbers=[{'figures': row['figures'], 'sentence': hide_handles(row['sentence'])}
                     for row in numbers_mentioned(text)])
        self.cache.put(url, result)
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
